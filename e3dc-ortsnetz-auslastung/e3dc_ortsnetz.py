#!/usr/bin/env python3
"""
e3dc_ortsnetz.py

Liest die Phasenspannungen, die Netzfrequenz, die Netzleistung und den Ladezustand des
Netzzählers (PM_TYPE_ROOT) eines E3/DC-Hauskraftwerks über das lokale RSCP-Protokoll und
sendet die Messung an https://www.ortsnetz-auslastung.de/v1/measurements

Benötigt Python 3.8 oder höher und das pye3dc-Modul:  pip install pye3dc

Aufruf:
    e3dc_ortsnetz.py            -> Stichprobe lesen, alle 5 Minuten eine Messung senden
    e3dc_ortsnetz.py --dry-run  -> Stichprobe lesen und Payload nur ausgeben

Das Script wird im Minutentablauf gestartet (cron oder systemd-Timer). Jede Laufzeit
liest eine Stichprobe und hängt sie an die State-Datei. Gesendet wird erst, wenn seit
der letzten Annahme das Sendeintervall von 300 Sekunden vergangen ist. Aus den
Stichproben desselben Intervalls werden die Min-, Max- und Durchschnittswerte der
Spannungen und der Netzfrequenz gebildet.

Die PV-Tagesprognose (pv_forecast_kwh) kommt aus Home Assistant (REST API), aus einer
Datei oder aus einem Befehl; das Hauskraftwerk selbst kann sie nicht liefern.

Die Konfiguration steht in Environment-Variablen oder in einer .env-Datei neben dem
Script (siehe .env.example), nicht im Script selbst. Gesetzte Environment-Variablen
haben Vorrang vor der .env-Datei.

Exit-Codes:
    0  Erfolg (Stichprobe gespeichert oder Messung gesendet)
    1  Konfiguration fehlt oder ist ungültig
    2  RSCP-Verbindung zum Hauskraftwerk gestört
    3  Keine plausible Messung (Zähler fehlt, Typ passt nicht, Spannungen unplausibel)
    4  API-Antwort unbrauchbar (HTTP-Fehler, Verbindungsabbruch)
    130 Process abgebrochen
"""

import argparse
import http.client
import json
import math
import os
import re
import shlex
import signal
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from e3dc import E3DC

try:
    # pye3dc ab 0.10.0; ältere Versionen haben diese Hilfsfunktionen nicht
    from e3dc._rscpTags import RscpTag, RscpType, getStrPowermeterType
    from e3dc._rscpLib import rscpFindTagIndex
except ImportError:
    RscpTag = None
    RscpType = None
    getStrPowermeterType = None
    rscpFindTagIndex = None

# ============================ Konfiguration ============================

# Alle Werte können als gleichnamige Environment-Variable oder in einer .env-Datei
# neben dem Script gesetzt werden. Environment-Variablen haben Vorrang.

E3DC_HOST = ""          # IP-Adresse des E3/DC-Hauskraftwerks, muss gesetzt werden
E3DC_USERNAME = ""      # Benutzername des E3/DC-Portals, muss gesetzt werden
E3DC_PASSWORD = ""      # Passwort des E3/DC-Portals, muss gesetzt werden
RSCP_KEY = ""           # Lokaler RSCP-Schlüssel: Display > Einstellungen > Personalisieren

# Ungefährer Standort in Dezimalgrad, muss gesetzt werden
LATITUDE = None         # z. B. 48.109569
LONGITUDE = None        # z. B. 11.726477

# Index des Netzzählers. None = automatisch den Zähler vom Typ PM_TYPE_ROOT suchen.
# Nur setzen, wenn die Installation von der Standardbelegung abweicht; der Index muss
# zwingend vom Typ PM_TYPE_ROOT sein, sonst bricht das Script ab.
METER_INDEX = None

# Optional: installierte PV-Leistung in kWp, größer 0 und maximal 1000.
# Leer lassen = die installierte Spitzenleistung des Kraftwerks wird benutzt.
PLANT_CAPACITY_KWP = None

# Optional: nutzbare Batteriespeicherkapazität in kWh, größer 0.
# Leer lassen = die installierte Kapazität des Kraftwerks als Näherung.
BATTERY_CAPACITY_KWH = None

# Optional: PV-Tagesprognose in kWh aus Home Assistant (REST API), aus einer Datei
# (evcc, Home Assistant, ioBroker) oder aus einem Befehl, der die kWh-Zahl in die
# Standardsausgabe schreibt. Alles leer = pv_forecast_kwh wird nicht übertragen.
# Reihenfolge: Home Assistant, dann Datei, dann Befehl.
PV_FORECAST_HA_URL = ""      # Basis-URL des Home Assistant, z. B. http://192.168.60.10:8123
PV_FORECAST_HA_TOKEN = ""    # Long-lived Token, Scope "Read & Historical"
PV_FORECAST_HA_ENTITY = ""   # Kommata-Liste der Sensoren, z. B. sensor.pv_prognose_sud,sensor.pv_prognose_west

# Prognosewerte, die älter als diese Sekunden sind, werden nicht gesendet (nachts behält
# ein Sensor den Abendwert). 0 schaltet die Altersprüfung ab.
PV_FORECAST_MAX_AGE_S = 3600

# Alternative Prognosequellen, wenn kein Home Assistant vorhanden ist.
PV_FORECAST_DATEI = ""
PV_FORECAST_BEFEHL = ""

# Optional: freie Bezeichnung des Messgeräts. Leer lassen = Modell und Seriennummer
# des Hauskraftwerks, wie sie pye3dc aus der Seriennummer erkennt.
SMARTMETER_MODEL = ""

# State-Datei für die Stichproben des Übertragungsintervalls. Leer = Standard
# ~/.local/state/ortsnetz-e3dc/state.json, bei systemd /var/lib/ortsnetz-e3dc/state.json
STATE_DATEI = ""

# Sendeintervall in Sekunden. Die API erwartet 300, kürzer darf es nicht sein.
SENDINTERVALL_S = 300

# Alternative .env-Datei (Environment-Variable ENV_DATEI), Standard ist .env neben dem Script
ENV_DATEI = None

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "e3dc-rscp-1.3"

# Maximale Laufzeit eines Aufrufs in Sekunden. Die RSCP-Timeouts begrenzen nur einzelne
# Netzwerkoperationen; eine halb offene Verbindung würde den cron-/systemd-Lauf sonst
# beliebig lange offenhalten.
MAX_LAUFZEIT_S = 60

# =======================================================================

# Spannungen außerhalb dieses Bereichs gelten als nicht plausibel
SPANNUNG_MIN = 150
SPANNUNG_MAX = 300

# Netzfrequenz außerhalb dieses Bereichs wird nicht übertragen (API erlaubt 45 bis 55 Hz)
FREQUENZ_MIN = 45
FREQUENZ_MAX = 55

# Netzleistung außerhalb dieses Bereichs wird nicht übertragen
LEISTUNG_MIN = -60000
LEISTUNG_MAX = 60000

# Stichproben älter als dieses Fenster werden verworfen, damit ein verschobener Timer
# die Min/Max-Werte nicht mit Werten von vor einer halben Stunde füllt
AUFBEWAHRUNG_S = 900

# Höchstzahl der Stichproben in der State-Datei
MAX_STICHPROBEN = 40

# Bezeichnung, wenn das Kraftwerk kein Modell nennen kann
AUSWICH_MODELL = "E3/DC Hauskraftwerk"

# Einheiten der Prognosesensoren in kWh; fehlende oder unbekannte Einheit wird nicht geraten
EINHEITEN = {"kWh": 1.0, "kwh": 1.0, "KWH": 1.0, "Wh": 0.001, "wh": 0.001, "MWh": 1000.0, "GWh": 1000000.0}

# Zeit eines Home-Assistant-Abfrufs in Sekunden
HA_TIMEOUT_S = 15

# Zählertyp des Netzzählers, in allen pye3dc-Versionen gleich lautender Name
WURZEL_TYP = "PM_TYPE_ROOT"

EXIT_KONFIGURATION = 1
EXIT_RSCP = 2
EXIT_MESSUNG = 3
EXIT_API = 4


class KonfigurationsFehler(Exception):
    pass


class MesswertFehler(Exception):
    pass


class ApiFehler(Exception):
    pass


def log(text):
    zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{zeit} {text}", flush=True)


def jetzt():
    """Aktuelle Zeit als Unix-Zeitpunkt in Sekunden; in den Tests ersetzbar."""
    return int(time.time())


def laufzeit_begrenzen():
    """Beendet den Prozess mit Fehler, wenn er länger als MAX_LAUFZEIT_S läuft (nur Linux/Unix)."""
    if not hasattr(signal, "SIGALRM"):
        return

    def abbruch(signalnummer, frame):
        raise SystemExit(f"FEHLER: Maximale Laufzeit von {MAX_LAUFZEIT_S} s überschritten.")

    signal.signal(signal.SIGALRM, abbruch)
    signal.alarm(MAX_LAUFZEIT_S)


def zahl(wert):
    """Liefert wert als float oder None, wenn es keine Zahl ist."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return None
    if not math.isfinite(wert):
        return None
    return float(wert)


def zahl_aus_text(text):
    """Liefert die Zahl in einem Text; JSON wird nach einem Prognoseschlüssel durchsucht."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            daten = json.loads(text)
        except ValueError:
            return None
        for schluessel in ("pv_forecast_kwh", "pv_forecast", "kwh", "kWh", "forecast", "value"):
            if schluessel in daten:
                return zahl(daten[schluessel])
        return None
    treffer = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not treffer:
        return None
    return float(treffer.group().replace(",", "."))


def env_datei_laden(pfad=None):
    """Liest KEY=VALUE-Zeilen aus einer .env-Datei; Environment-Variablen bleiben vorn.

    Leere Werte und Kommentarzeilen werden ignoriert, umschließende Anführungszeichen
    werden entfernt. Nicht gesetzte Environment-Variablen werden aus der Datei ergänzt,
    damit cron und systemd ohne zusätzliche Shell-Befehle auskommen.
    """
    global ENV_DATEI
    datei = pfad or os.environ.get("ENV_DATEI") or ENV_DATEI
    if not datei:
        datei = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    ENV_DATEI = datei

    if not os.path.isfile(datei):
        return

    try:
        with open(datei, "r", encoding="utf-8") as datei_objekt:
            zeilen = datei_objekt.readlines()
    except OSError as fehler:
        raise KonfigurationsFehler(f".env-Datei {datei} kann nicht gelesen werden: {fehler}")

    for nummer, zeile in enumerate(zeilen, 1):
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        if "=" not in zeile:
            raise KonfigurationsFehler(f".env-Datei {datei}, Zeile {nummer}: kein KEY=VALUE")
        schluessel, wert = zeile.split("=", 1)
        schluessel = schluessel.strip()
        wert = wert.strip().strip("'\"")
        if not schluessel or wert == "":
            continue
        # Environment-Variablen haben Vorrang, leere Environment-Variablen gelten als nicht gesetzt
        if os.environ.get(schluessel, "").strip() == "":
            os.environ[schluessel] = wert


def einstellung(name, standard, umwandeln=str):
    """Liefert die Environment-Variable name umgewandelt oder standard, wenn sie fehlt oder leer ist."""
    wert = os.environ.get(name, "").strip()
    if not wert:
        return standard
    try:
        return umwandeln(wert)
    except ValueError:
        raise KonfigurationsFehler(f"Environment-Variable {name}={wert!r} ist ungültig.")


def konfiguration_laden():
    global E3DC_HOST, E3DC_USERNAME, E3DC_PASSWORD, RSCP_KEY
    global LATITUDE, LONGITUDE, METER_INDEX, PLANT_CAPACITY_KWP
    global BATTERY_CAPACITY_KWH, PV_FORECAST_DATEI, PV_FORECAST_BEFEHL
    global PV_FORECAST_HA_URL, PV_FORECAST_HA_TOKEN, PV_FORECAST_HA_ENTITY
    global PV_FORECAST_MAX_AGE_S
    global SMARTMETER_MODEL, STATE_DATEI, SENDINTERVALL_S

    E3DC_HOST = einstellung("E3DC_HOST", E3DC_HOST)
    E3DC_USERNAME = einstellung("E3DC_USERNAME", E3DC_USERNAME)
    E3DC_PASSWORD = einstellung("E3DC_PASSWORD", E3DC_PASSWORD)
    RSCP_KEY = einstellung("RSCP_KEY", RSCP_KEY)
    LATITUDE = einstellung("LATITUDE", LATITUDE, float)
    LONGITUDE = einstellung("LONGITUDE", LONGITUDE, float)
    METER_INDEX = einstellung("METER_INDEX", METER_INDEX, int)
    PLANT_CAPACITY_KWP = einstellung("PLANT_CAPACITY_KWP", PLANT_CAPACITY_KWP, float)
    BATTERY_CAPACITY_KWH = einstellung("BATTERY_CAPACITY_KWH", BATTERY_CAPACITY_KWH, float)
    PV_FORECAST_HA_URL = einstellung("PV_FORECAST_HA_URL", PV_FORECAST_HA_URL)
    PV_FORECAST_HA_TOKEN = einstellung("PV_FORECAST_HA_TOKEN", PV_FORECAST_HA_TOKEN)
    PV_FORECAST_HA_ENTITY = einstellung("PV_FORECAST_HA_ENTITY", PV_FORECAST_HA_ENTITY)
    PV_FORECAST_MAX_AGE_S = einstellung("PV_FORECAST_MAX_AGE_S", PV_FORECAST_MAX_AGE_S, int)
    PV_FORECAST_DATEI = einstellung("PV_FORECAST_DATEI", PV_FORECAST_DATEI)
    PV_FORECAST_BEFEHL = einstellung("PV_FORECAST_BEFEHL", PV_FORECAST_BEFEHL)
    SMARTMETER_MODEL = einstellung("SMARTMETER_MODEL", SMARTMETER_MODEL)
    STATE_DATEI = einstellung("STATE_DATEI", STATE_DATEI)
    SENDINTERVALL_S = einstellung("SENDINTERVALL_S", SENDINTERVALL_S, int)


def prognose_quellen_pruefen():
    """Prüft die Home-Assistant-Prognosequelle, nur wenn Sensoren gesetzt sind."""
    if PV_FORECAST_MAX_AGE_S < 0:
        raise KonfigurationsFehler("PV_FORECAST_MAX_AGE_S darf nicht negativ sein.")
    if not PV_FORECAST_HA_ENTITY:
        return
    entities = [e.strip() for e in PV_FORECAST_HA_ENTITY.split(",") if e.strip()]
    if not entities:
        raise KonfigurationsFehler("PV_FORECAST_HA_ENTITY enthält keine Sensor-Identifikation.")
    for entity in entities:
        if "." not in entity:
            raise KonfigurationsFehler(
                f"PV_FORECAST_HA_ENTITY: {entity!r} ist keine Sensor-Identifikation "
                "sensor.name / number.name.")
    if not PV_FORECAST_HA_URL.lower().startswith(("http://", "https://")):
        raise KonfigurationsFehler(
            "PV_FORECAST_HA_URL muss mit http:// oder https:// beginnen, "
            "z. B. http://192.168.60.10:8123.")
    if not PV_FORECAST_HA_TOKEN:
        raise KonfigurationsFehler(
            "PV_FORECAST_HA_TOKEN fehlt: für die Prognose aus Home Assistant wird ein "
            "Long-lived Token mit Scope Read & Historical benötigt.")


def konfiguration_pruefen():
    for name, wert in (("E3DC_HOST", E3DC_HOST), ("E3DC_USERNAME", E3DC_USERNAME),
                       ("E3DC_PASSWORD", E3DC_PASSWORD)):
        if not wert:
            raise KonfigurationsFehler(f"{name} ist nicht gesetzt (siehe .env.example)")
    if LATITUDE is None or LONGITUDE is None:
        raise KonfigurationsFehler("LATITUDE und LONGITUDE müssen als Dezimalgrad gesetzt sein.")
    if not -90 <= LATITUDE <= 90 or not -180 <= LONGITUDE <= 180:
        raise KonfigurationsFehler("LATITUDE muss zwischen -90 und 90, LONGITUDE zwischen -180 und 180 liegen.")
    if METER_INDEX is not None and not 0 <= METER_INDEX <= 7:
        raise KonfigurationsFehler("METER_INDEX muss zwischen 0 und 7 liegen.")
    if PLANT_CAPACITY_KWP is not None and not 0 < PLANT_CAPACITY_KWP <= 1000:
        raise KonfigurationsFehler("PLANT_CAPACITY_KWP muss größer 0 und maximal 1000 sein.")
    if BATTERY_CAPACITY_KWH is not None and not 0 < BATTERY_CAPACITY_KWH <= 2000:
        raise KonfigurationsFehler("BATTERY_CAPACITY_KWH muss größer 0 und maximal 2000 sein.")
    if SENDINTERVALL_S < 300:
        raise KonfigurationsFehler(
            "SENDINTERVALL_S darf nicht kleiner als 300 Sekunden sein (Sendeintervall der API).")
    prognose_quellen_pruefen()


def state_pfad():
    """Liefert den Pfad der State-Datei: STATE_DATEI, sonst der XDG-Standard."""
    if STATE_DATEI:
        return STATE_DATEI
    grund = os.environ.get("XDG_STATE_HOME", "").strip()
    if not grund:
        grund = os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(grund, "ortsnetz-e3dc", "state.json")


def staat_lesen(pfad):
    """Liefert {"last_send": Zeitpunkt oder None, "samples": [[Zeit, L1, L2, L3, f], ...]}.

    Eine fehlende oder unlesbare State-Datei ist kein Fehler: ohne gespeicherte
    Stichproben werden Min, Max und Mittelwert aus der aktuellen Stichprobe gebildet.
    """
    try:
        with open(pfad, "r", encoding="utf-8") as objekt:
            inhalt = json.load(objekt)
    except FileNotFoundError:
        return {"last_send": None, "samples": []}
    except (OSError, ValueError) as fehler:
        log(f"Warnung: State-Datei {pfad} ist unlesbar ({fehler}) – ohne gespeicherte Stichproben.")
        return {"last_send": None, "samples": []}

    proben = []
    letzte = None
    if isinstance(inhalt, dict):
        for eintrag in inhalt.get("samples", []):
            if not isinstance(eintrag, (list, tuple)) or len(eintrag) < 5:
                continue
            zeit = zahl(eintrag[0])
            if zeit is None:
                continue
            proben.append([int(zeit), zahl(eintrag[1]), zahl(eintrag[2]), zahl(eintrag[3]), zahl(eintrag[4])])
        letzte = zahl(inhalt.get("last_send"))
        if letzte is not None:
            letzte = int(letzte)
    return {"last_send": letzte, "samples": proben}


def staat_schreiben(pfad, proben, last_send):
    """Schreibt die State-Datei atomar; ein Schreibfehler ist kein Abbruchgrund."""
    ordner = os.path.dirname(pfad)
    if ordner:
        os.makedirs(ordner, mode=0o700, exist_ok=True)
    daten = {"version": 1, "last_send": last_send, "samples": proben}
    temp = f"{pfad}.tmp"
    with open(temp, "w", encoding="utf-8") as objekt:
        objekt.write(json.dumps(daten))
    os.replace(temp, pfad)


def stichproben_pruenen(proben, zeitpunkt):
    """Liefert die Stichproben des Aufbewahrungsfensters, zeitlich aufsteigend."""
    aktuell = [s for s in proben if zahl(s[0]) is not None]
    aktuell = [s for s in aktuell if zeitpunkt - AUFBEWAHRUNG_S <= s[0] <= zeitpunkt]
    aktuell.sort(key=lambda s: s[0])
    return aktuell[-MAX_STICHPROBEN:]


def stichproben_fenster(proben, zeitpunkt):
    """Liefert die Stichproben desselben Übertragungsintervalls, also [Zeit - Intervall, Zeit]."""
    return [s for s in proben if zeitpunkt - SENDINTERVALL_S <= s[0] <= zeitpunkt]


def kennzahlen(proben, spalte):
    """Liefert (min, max, avg) einer Stichprobenspalte oder None, wenn kein gültiger Wert da ist.

    Fehlende Werte (None, in der API als -1) werden ignoriert, wie API.md es verlangt.
    """
    werte = [zahl(s[spalte]) for s in proben]
    werte = [wert for wert in werte if wert is not None]
    if not werte:
        return None
    return round(min(werte), 2), round(max(werte), 2), round(sum(werte) / len(werte), 2)


def senden_faellig(last_send, zeitpunkt):
    """True, wenn das Sendeintervall seit der letzten Annahme vergangen ist."""
    if last_send is None:
        return True
    return zeitpunkt - last_send >= SENDINTERVALL_S


def typname(eintrag):
    """Liefert den Namen des Zählertyps oder None, wenn er nicht bestimmt werden kann."""
    name = eintrag.get("typeName")
    if isinstance(name, str) and name:
        return name
    typ = eintrag.get("type")
    if isinstance(typ, int) and getStrPowermeterType is not None:
        return getStrPowermeterType(typ)
    return None


def netzhaehler_finden(e3dc):
    """Liefert (index, typname) des Netzzählers und prüft den Zählertyp.

    `powermeters[0]` ist nur in der Standardinstallation der Netzzähler. Abweichende
    Installationen (S0-, Wallbox-, PV-, Batteriezähler in anderer Reihenfolge) würden
    sonst einen fremden Zähler melden, deshalb wird der Typ PM_TYPE_ROOT verlangt.
    """
    zaehler = e3dc.get_powermeters(keepAlive=True)
    if not zaehler:
        raise MesswertFehler("Das Hauskraftwerk meldet keine Zähler.")

    zaehlerliste = ", ".join(f"Index {e.get('index')} Typ {typname(e) or e.get('type')}" for e in zaehler)

    if METER_INDEX is not None:
        eintrag = next((e for e in zaehler if e.get("index") == METER_INDEX), None)
        if eintrag is None:
            raise MesswertFehler(f"Zählerindex {METER_INDEX} existiert nicht: {zaehlerliste}")
        typ = typname(eintrag)
        if typ is not None and typ != WURZEL_TYP:
            raise MesswertFehler(
                f"Zählerindex {METER_INDEX} ist kein Netzzähler (Typ {typ}), sondern {zaehlerliste}. "
                "METER_INDEX entfernen oder korrigieren."
            )
        return METER_INDEX, typ

    for eintrag in zaehler:
        if typname(eintrag) == WURZEL_TYP:
            return eintrag["index"], WURZEL_TYP

    if any(typname(eintrag) is not None for eintrag in zaehler):
        raise MesswertFehler(
            f"Kein Netzzähler vom Typ {WURZEL_TYP} gefunden: {zaehlerliste}. "
            "Installation prüfen und ggf. METER_INDEX setzen."
        )

    # pye3dc ohne Typnamen: Index 0 verwenden und offen sagen, dass der Typ nicht prüfbar ist
    erster = zaehler[0]
    log(f"Warnung: Zählertyp nicht prüfbar – verwende Zählerindex {erster.get('index')} ({zaehlerliste}).")
    return erster.get("index", 0), None


def spannung(daten, phase):
    """Liefert die Spannung der Phase in Volt oder None, wenn sie fehlt oder unplausibel ist."""
    roh = None
    spannungen = daten.get("voltage")
    if isinstance(spannungen, dict):
        roh = spannungen.get(f"L{phase}")
    elif isinstance(spannungen, (list, tuple)) and len(spannungen) >= phase:
        roh = spannungen[phase - 1]
    if roh is None:
        roh = daten.get(f"voltageL{phase}")
    wert = zahl(roh)
    if wert is None:
        return None
    wert = round(wert, 2)
    if not SPANNUNG_MIN <= wert <= SPANNUNG_MAX:
        return None
    return wert


def ac_frequenz_abrufen(e3dc):
    """Fragt die Netzfrequenz am ersten PV-Wechselrichter ab.

    pye3dc ab 0.10.0 hat die Frequenz nicht im Zählerdatensatz. Der Tag
    `PVI_REQ_AC_FREQUENCY` wird am Hauskraftwerk nur innerhalb eines
    `PVI_REQ_DATA`-Containers mit Wechselrichter-Index beantwortet; die Antwort enthält
    `PVI_AC_FREQUENCY` mit `PVI_VALUE` in Hz.
    """
    if RscpTag is None or RscpType is None or rscpFindTagIndex is None:
        return None
    try:
        for wechselrichter in e3dc.get_pvis(keepAlive=True):
            antwort = e3dc.sendRequest(
                (
                    RscpTag.PVI_REQ_DATA,
                    RscpType.Container,
                    [
                        (RscpTag.PVI_INDEX, RscpType.Uint16, wechselrichter["index"]),
                        (RscpTag.PVI_REQ_AC_FREQUENCY, RscpType.NoneType, None),
                    ],
                ),
                keepAlive=True,
            )
            wert = zahl(rscpFindTagIndex(antwort, RscpTag.PVI_VALUE))
            if wert is not None:
                return wert
    except Exception:
        return None
    return None


def frequenz_lesen(daten, e3dc):
    """Liefert die plausibile Netzfrequenz in Hz oder None; Feld grid_frequency_hz ist optional."""
    wert = zahl(daten.get("frequency"))
    if wert is None:
        wert = ac_frequenz_abrufen(e3dc)
    if wert is None:
        return None
    wert = round(wert, 2)
    if not FREQUENZ_MIN <= wert <= FREQUENZ_MAX:
        log(f"Warnung: Netzfrequenz {wert} Hz ist unplausibel – grid_frequency_hz wird nicht übertragen.")
        return None
    return wert


def netzleistung_abrufen(e3dc):
    """Liefert die Wirkleistung am Hausanschluss in W (positiv = Bezug, negativ = Einspeisung).

    `EMS_REQ_POWER_GRID` dokumentiert pye3dc als "absorption from grid in W", also
    genau das Vorzeichen, das die API verlangt. Der Wert stammt vom Netzzähler-Pfad des
    Kraftwerks und ist nicht die Leistung eines Wechselrichters.
    """
    if RscpTag is None:
        return None
    try:
        wert = zahl(e3dc.sendRequestTag(RscpTag.EMS_REQ_POWER_GRID, keepAlive=True))
    except Exception:
        log("Warnung: Netzleistung nicht verfügbar – grid_power_w wird nicht übertragen.")
        return None
    if wert is None:
        log("Warnung: Netzleistung nicht verfügbar – grid_power_w wird nicht übertragen.")
        return None
    if not LEISTUNG_MIN <= wert <= LEISTUNG_MAX:
        log(f"Warnung: Netzleistung {wert} W ist unplausibel – grid_power_w wird nicht übertragen.")
        return None
    return round(wert, 1)


def soc_abrufen(e3dc):
    """Liefert den Ladezustand in Prozent (0 bis 100) oder None, wenn kein Speicher antwortet."""
    if RscpTag is None:
        return None
    try:
        wert = zahl(e3dc.sendRequestTag(RscpTag.EMS_REQ_BAT_SOC, keepAlive=True))
    except Exception:
        return None
    if wert is None:
        return None
    wert = round(wert)
    if not 0 <= wert <= 100:
        log(f"Warnung: Ladezustand {wert} % ist unplausibel – battery_soc_percent wird nicht übertragen.")
        return None
    return wert


def anlagen_groesse(e3dc):
    """Liefert plant_capacity_kwp: Konfiguration hat Vorrang, sonst die installierte Spitzenleistung.

    `installedPeakPower` nennt die installierte PV-Leistung in Watt; pye3dc liest sie
    beim Verbindungsaufbau, ohne zusätzlichen RSCP-Aufruf.
    """
    if PLANT_CAPACITY_KWP is not None:
        return PLANT_CAPACITY_KWP
    wert = zahl(getattr(e3dc, "installedPeakPower", None))
    if wert is None:
        return None
    kwp = round(wert / 1000, 1)
    if not 0 < kwp <= 1000:
        return None
    return kwp


def batteriekapazitaet_kwh(e3dc):
    """Liefert battery_capacity in kWh: Konfiguration hat Vorrang, sonst die installierte Kapazität.

    `installedBatteryCapacity` ist die installierte, nicht die nutzbare Kapazität.
    `BAT_REQ_USABLE_CAPACITY` wäre in Amperestunden und nur mit der Batteriespannung
    in kWh umrechnbar – eine Schätzung, die API.md nicht will. Deshalb ist der
    Konfigurationswert BATTERY_CAPACITY_KWH genauer und hat Vorrang.
    """
    if BATTERY_CAPACITY_KWH is not None:
        return BATTERY_CAPACITY_KWH
    wert = zahl(getattr(e3dc, "installedBatteryCapacity", None))
    if wert is None:
        return None
    kwh = round(wert / 1000, 1)
    if kwh <= 0:
        return None
    return kwh


def zaehlerbezeichnung(e3dc):
    """Liefert smartmeter_model: Konfiguration hat Vorrang, sonst Modell und Seriennummer."""
    if SMARTMETER_MODEL:
        return SMARTMETER_MODEL[:120]
    anteile = ["E3/DC"]
    modell = getattr(e3dc, "model", None)
    if isinstance(modell, str) and modell.strip():
        anteile.append(modell.strip())
    seriennummer = getattr(e3dc, "serialNumber", None)
    if isinstance(seriennummer, str) and seriennummer.strip():
        anteile.append(seriennummer.strip())
    if len(anteile) == 1:
        return AUSWICH_MODELL
    return " ".join(anteile)[:120]


def zahl_von_wert(wert):
    """Liefert eine HA-Sensorangabe als Zahl; HA meldet den Zustand als Text."""
    if isinstance(wert, str):
        return zahl_aus_text(wert)
    return zahl(wert)


def einheit_faktor(einheit):
    """Liefert den Faktor nach kWh für die Sensor-Einheit, sonst None.

    Es wird nie geraten: ein Sensor ohne `unit_of_measurement` oder mit einer
    Leistung (W) statt einer Energie (Wh) wird übersprungen.
    """
    if einheit is None:
        return None
    return EINHEITEN.get(str(einheit).strip())


def zeitpunkt_aus_iso(text):
    """Liefert den Unix-Zeitpunkt einer ISO-Zeit aus Home Assistant, sonst None.

    Python 3.8 akzeptiert das `Z` in `…T08:00:00Z` nicht, es wird durch `+00:00`
    ersetzt. Zeiten ohne Zeitzone gelten als UTC.
    """
    if not isinstance(text, str):
        return None
    text = text.strip().replace("Z", "+00:00")
    try:
        zeit = datetime.fromisoformat(text)
    except ValueError:
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return int(zeit.timestamp())


def ha_abfragen(entity):
    """Liefert die Sensorantwort von Home Assistant als dict, sonst None."""
    pfad = PV_FORECAST_HA_URL.rstrip("/") + f"/api/states/{entity}"
    anfrage = urllib.request.Request(
        pfad,
        headers={"Authorization": f"Bearer {PV_FORECAST_HA_TOKEN}",
                 "User-Agent": "E3DC-Ortsnetz-Client"},
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=HA_TIMEOUT_S) as antwort:
            daten = json.loads(antwort.read().decode("utf-8", errors="replace"))
    except Exception as fehler:
        log(f"Warnung: Home Assistant {entity} nicht abrufbar ({fehler}).")
        return None
    if not isinstance(daten, dict):
        log(f"Warnung: Home Assistant {entity} antwortet ohne Sensorobjekt.")
        return None
    return daten


def pv_forecast_ha():
    """Liefert die Summe der Prognosesensoren in kWh, sonst None.

    Jeder Sensor wird einzeln geprüft: Zahl, bekannte Energieeinheit, Alter.
    Ein Sensor, der `unavailable` meldet (nachts) oder einen veralteten Wert hält,
    wird übersprungen, die Messung selbst wird trotzdem übertragen.
    """
    entities = [e.strip() for e in PV_FORECAST_HA_ENTITY.split(",") if e.strip()]
    gesamt = None
    for entity in entities:
        daten = ha_abfragen(entity)
        if daten is None:
            continue

        wert = zahl_von_wert(daten.get("state"))
        if wert is None:
            log(f"Warnung: Sensor {entity} meldet {daten.get('state')!r} – keine Zahl, Prognose ignoriert.")
            continue

        einheit = (daten.get("attributes") or {}).get("unit_of_measurement")
        faktor = einheit_faktor(einheit)
        if faktor is None:
            log(f"Warnung: Sensor {entity} hat Einheit {einheit!r} – keine bekannte Energieeinheit "
                "(Sensor muss unit_of_measurement: kWh melden), Prognose ignoriert.")
            continue

        zeit = zeitpunkt_aus_iso(daten.get("last_reported") or daten.get("last_updated"))
        if PV_FORECAST_MAX_AGE_S > 0:
            if zeit is None:
                log(f"Warnung: Sensor {entity} nennt keine Zeit – Alter nicht prüfbar, Prognose ignoriert.")
                continue
            alter = jetzt() - zeit
            if alter > PV_FORECAST_MAX_AGE_S:
                log(f"Warnung: Sensor {entity} ist {alter} s alt (max. {PV_FORECAST_MAX_AGE_S} s) – Prognose ignoriert.")
                continue

        kwh = wert * faktor
        gesamt = kwh if gesamt is None else gesamt + kwh
    if gesamt is None:
        return None
    return round(gesamt, 1)


def pv_forecast_datei():
    """Liefert die Prognose in kWh aus PV_FORECAST_DATEI, sonst None."""
    try:
        with open(PV_FORECAST_DATEI, "r", encoding="utf-8") as objekt:
            wert = zahl_aus_text(objekt.read())
    except OSError as fehler:
        log(f"Warnung: Prognosedatei {PV_FORECAST_DATEI} ist nicht lesbar ({fehler}).")
        return None
    if wert is None:
        log(f"Warnung: Prognosedatei {PV_FORECAST_DATEI} nennt keine kWh-Zahl – pv_forecast_kwh weggelassen.")
    return wert


def pv_forecast_befehl():
    """Liefert die Prognose in kWh aus PV_FORECAST_BEFEHL, sonst None."""
    try:
        ablauf = subprocess.run(shlex.split(PV_FORECAST_BEFEHL), capture_output=True,
                                text=True, timeout=15)
    except (OSError, ValueError, subprocess.TimeoutExpired) as fehler:
        log(f"Warnung: Prognosebefehl {PV_FORECAST_BEFEHL} fehlgeschlagen ({fehler}).")
        return None
    if ablauf.returncode != 0:
        log(f"Warnung: Prognosebefehl {PV_FORECAST_BEFEHL} mit Exit {ablauf.returncode}.")
        return None
    wert = zahl_aus_text(ablauf.stdout)
    if wert is None:
        log(f"Warnung: Prognosebefehl {PV_FORECAST_BEFEHL} nennt keine kWh-Zahl – pv_forecast_kwh weggelassen.")
    return wert


def prognose_pruefen(wert, kapazitaet):
    """Prüft die Prognose gegen die API-Grenzen und liefert sie, sonst None.

    Die API verlangt eine gespeicherte oder mitgesendete Anlagengröße und verwirft bei
    mehr als 10 kWh je kWp pro Tag die gesamte Messung mit HTTP 422. Deshalb wird ein
    Wert ohne Anlagengröße oder über der Grenze gar nicht erst gesendet.
    """
    wert = round(wert, 1)
    if not 0 <= wert <= 100000:
        log(f"Warnung: PV-Prognose {wert} kWh ist außerhalb von 0 bis 100000 – weggelassen.")
        return None
    if kapazitaet is None:
        log("Warnung: PV-Prognose ohne bekannte Anlagengröße wird nicht gesendet (API: HTTP 422).")
        return None
    grenze = 10 * kapazitaet
    if wert > grenze:
        log(f"Warnung: PV-Prognose {wert} kWh überschreitet {grenze} kWh (10 kWh je kWp) – weggelassen.")
        return None
    return wert


def pv_forecast_lesen(kapazitaet):
    """Liefert pv_forecast_kwh: Home Assistant zuerst, dann Datei, dann Befehl, sonst None."""
    wert = pv_forecast_ha() if PV_FORECAST_HA_ENTITY else None
    if wert is None:
        if PV_FORECAST_DATEI:
            wert = pv_forecast_datei()
        elif PV_FORECAST_BEFEHL:
            wert = pv_forecast_befehl()
    if wert is None:
        return None
    return prognose_pruefen(wert, kapazitaet)


def messdaten_flach(daten):
    """Liefert die Messwerte; pye3dc bis 0.9.x hält sie in einem "data"-Unterordner."""
    return daten.get("data", daten)


def messwerte(daten):
    """Liefert die Spannungen L1, L2, L3 aus einem Zählerdatensatz; L1 muss plausibel sein."""
    daten = messdaten_flach(daten)

    l1 = spannung(daten, 1)
    if l1 is None:
        raise MesswertFehler(
            f"L1: keine plausible Spannung (voltage L1 = {daten.get('voltage')}, "
            f"erwartet {SPANNUNG_MIN} bis {SPANNUNG_MAX} V)."
        )
    # Der Netzzähler meldet nicht gemessene Phasen mit 0 V; die API erwartet dann -1
    return {"l1": l1, "l2": spannung(daten, 2), "l3": spannung(daten, 3)}


def messlauf_erstellen(daten, e3dc, index, typ):
    """Liefert alle Werte einer Laufzeit: Spannungen, Frequenz, Netzleistung, SOC und Standortangaben."""
    flach = messdaten_flach(daten)
    werte = messwerte(flach)
    return {
        "index": index,
        "typ": typ,
        "l1": werte["l1"],
        "l2": werte["l2"],
        "l3": werte["l3"],
        "freq": frequenz_lesen(flach, e3dc),
        "power": netzleistung_abrufen(e3dc),
        "soc": soc_abrufen(e3dc),
        "kapazitaet": anlagen_groesse(e3dc),
        "batteriekapazitaet": batteriekapazitaet_kwh(e3dc),
        "modell": zaehlerbezeichnung(e3dc),
    }


def stichprobe_erstellen(lauf, zeitpunkt):
    """Liefert die Stichprobe [Zeit, L1, L2, L3, Frequenz] für die State-Datei.

    Nur die Werte mit Min/Max-Mitteln werden über das Intervall gesammelt; Netzleistung
    und Ladezustand haben keine Kennzahlen und werden bei der Sendung aktuell gelesen.
    """
    return [zeitpunkt, lauf["l1"], lauf["l2"], lauf["l3"], lauf["freq"]]


def payload_erstellen(stichprobe, fenster, lauf, forecast):
    """Liefert den API-Payload; wirft MesswertFehler bei unplausiblen Werten."""
    zeitpunkt, l1, l2, l3, freq = stichprobe
    if l1 is None:
        raise MesswertFehler(f"L1: keine plausible Spannung (Stichprobe {stichprobe}).")

    payload = {
        "observed_at": datetime.fromtimestamp(zeitpunkt, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": l1,
        # Nicht gemessene Phasen kennzeichnet die API mit -1; ebenso ihre Kennzahlen
        "l2_v": -1 if l2 is None else l2,
        "l3_v": -1 if l3 is None else l3,
        "smartmeter_model": lauf["modell"],
        "integration_version": INTEGRATION_VERSION,
    }

    for phase, spalte in (("l1", 1), ("l2", 2), ("l3", 3)):
        ken = kennzahlen(fenster, spalte)
        payload[f"{phase}_v_min"] = ken[0] if ken else -1
        payload[f"{phase}_v_max"] = ken[1] if ken else -1
        payload[f"{phase}_v_avg"] = ken[2] if ken else -1

    if freq is not None:
        payload["grid_frequency_hz"] = freq
    ken = kennzahlen(fenster, 4)
    if ken:
        payload["grid_frequency_hz_min"] = ken[0]
        payload["grid_frequency_hz_max"] = ken[1]
        payload["grid_frequency_hz_avg"] = ken[2]

    if lauf["power"] is not None:
        payload["grid_power_w"] = lauf["power"]
    if lauf["soc"] is not None:
        payload["battery_soc_percent"] = lauf["soc"]
    if lauf["kapazitaet"] is not None:
        payload["plant_capacity_kwp"] = lauf["kapazitaet"]
    if lauf["batteriekapazitaet"] is not None:
        payload["battery_capacity"] = lauf["batteriekapazitaet"]
    if forecast is not None:
        payload["pv_forecast_kwh"] = forecast

    anzahl = f"{len(fenster)} Stichprobe" + ("n" if len(fenster) > 1 else "")
    log(f"Benutzter Zähler: Index {lauf['index']} Typ {lauf['typ'] or 'unbekannt'} | "
        f"L1={payload['l1_v']} L2={payload['l2_v']} L3={payload['l3_v']} V | "
        f"f={payload.get('grid_frequency_hz', '-')} Hz | "
        f"P={payload.get('grid_power_w', '-')} W | SOC={payload.get('battery_soc_percent', '-')} % | "
        f"{anzahl} im Intervall")
    return payload


def antwort_auswerten(antwort):
    """Loggt Ampel, Speicherladeempfehlung und Redispatch; fehlende Felder werden ignoriert."""
    if not isinstance(antwort, dict):
        return
    status = antwort.get("status")
    if isinstance(status, dict):
        phasen = " ".join(f"{phase}={status.get(phase) or '-'}" for phase in ("l1", "l2", "l3"))
        log(f"Ampel: {phasen} | gesamt={status.get('overall') or '-'}")
    empfehlung = antwort.get("storage_recommendation")
    if isinstance(empfehlung, str) and empfehlung:
        log(f"Speicherladeempfehlung: {empfehlung}.")
    redispatch = antwort.get("redispatch")
    if isinstance(redispatch, dict):
        log(f"Redispatch: active={redispatch.get('active')} "
            f"affected_units={redispatch.get('affected_units')} "
            f"active_measures={redispatch.get('active_measures')} "
            f"data_updated_at={redispatch.get('data_updated_at')}")


def senden(payload):
    anfrage = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "E3DC-Ortsnetz-Client"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=20) as antwort:
            status = antwort.status
            text = antwort.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as fehler:
        status = fehler.code
        text = fehler.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, http.client.HTTPException) as fehler:
        raise ApiFehler(f"Verbindung zur API fehlgeschlagen: {fehler}")

    if status == 202:
        try:
            antwort_json = json.loads(text)
        except ValueError:
            antwort_json = None
        if not isinstance(antwort_json, dict) or antwort_json.get("accepted") is not True:
            raise ApiFehler(f"HTTP 202 ohne Annahmebestätigung: {text}")
        log(f"Übertragen ({payload['observed_at']}): HTTP 202, Messung angenommen.")
        antwort_auswerten(antwort_json)
    elif status == 403:
        raise ApiFehler(f"HTTP 403 – der Standort ist für die Annahme gesperrt: {text}")
    elif status == 422:
        raise ApiFehler(f"HTTP 422 – Payload abgelehnt: {text}")
    else:
        raise ApiFehler(f"Unerwarteter HTTP-Status {status}: {text}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="E3/DC-Messwerte an Ortsnetz-Auslastung senden.")
    parser.add_argument("--dry-run", action="store_true", help="Stichprobe lesen und Payload nur ausgeben")
    args = parser.parse_args(argv)

    try:
        env_datei_laden()
        konfiguration_laden()
        konfiguration_pruefen()
    except KonfigurationsFehler as fehler:
        log(f"FEHLER: {fehler}")
        return EXIT_KONFIGURATION

    laufzeit_begrenzen()

    try:
        e3dc = E3DC(
            E3DC.CONNECT_LOCAL,
            username=E3DC_USERNAME,
            password=E3DC_PASSWORD,
            ipAddress=E3DC_HOST,
            key=RSCP_KEY,
        )
    except Exception as fehler:
        log(f"FEHLER: RSCP-Verbindung zu {E3DC_HOST} fehlgeschlagen: {fehler}")
        return EXIT_RSCP

    lauf = None
    try:
        index, typ = netzhaehler_finden(e3dc)
        daten = e3dc.get_powermeter_data(pmIndex=index, keepAlive=True)
        lauf = messlauf_erstellen(daten, e3dc, index, typ)
    except MesswertFehler as fehler:
        log(f"FEHLER: {fehler}")
        return EXIT_MESSUNG
    except Exception as fehler:
        log(f"FEHLER: RSCP-Abfrage fehlgeschlagen: {fehler}")
        return EXIT_RSCP
    finally:
        try:
            e3dc.disconnect()
        except Exception:
            pass

    if lauf is None:
        return EXIT_MESSUNG

    zeitpunkt = jetzt()
    pfad = state_pfad()
    staat = staat_lesen(pfad)
    proben = stichproben_pruenen(staat["samples"] + [stichprobe_erstellen(lauf, zeitpunkt)], zeitpunkt)
    fenster = stichproben_fenster(proben, zeitpunkt)
    forecast = pv_forecast_lesen(lauf["kapazitaet"])
    payload = payload_erstellen(stichprobe_erstellen(lauf, zeitpunkt), fenster, lauf, forecast)

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    try:
        # Stichprobe zuerst sichern, damit ein Sendefehler die gesammelten Werte nicht kostet
        staat_schreiben(pfad, proben, staat["last_send"])
    except OSError as fehler:
        log(f"Warnung: State-Datei {pfad} konnte nicht geschrieben werden ({fehler}).")

    if not senden_faellig(staat["last_send"], zeitpunkt):
        rest = SENDINTERVALL_S - (zeitpunkt - (staat["last_send"] or zeitpunkt))
        log(f"Stichprobe gespeichert, Senden erst in {max(rest, 0)} s.")
        return 0

    try:
        senden(payload)
    except ApiFehler as fehler:
        log(f"FEHLER: {fehler}")
        return EXIT_API

    try:
        staat_schreiben(pfad, proben, zeitpunkt)
    except OSError as fehler:
        log(f"Warnung: State-Datei {pfad} konnte nicht geschrieben werden ({fehler}).")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
