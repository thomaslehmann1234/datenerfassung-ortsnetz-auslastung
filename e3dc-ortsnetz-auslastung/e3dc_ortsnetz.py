#!/usr/bin/env python3
"""
e3dc_ortsnetz.py

Liest die Phasenspannungen und die Netzfrequenz des Netzzählers (PM_TYPE_ROOT) eines
E3/DC-Hauskraftwerks über das lokale RSCP-Protokoll und sendet die Messung an
https://www.ortsnetz-auslastung.de/v1/measurements

Benötigt Python 3.8 oder höher und das pye3dc-Modul:  pip install pye3dc

Aufruf:
    e3dc_ortsnetz.py            -> eine Messung senden und beenden
    e3dc_ortsnetz.py --dry-run  -> eine Messung lesen und Payload nur ausgeben

Die Konfiguration steht in Environment-Variablen oder in einer .env-Datei neben dem
Script (siehe .env.example), nicht im Script selbst. Gesetzte Environment-Variablen
haben Vorrang vor der .env-Datei.

Exit-Codes:
    0  Erfolg
    1  Konfiguration fehlt oder ist ungültig
    2  RSCP-Verbindung zum Hauskraftwerk gestört
    3  Keine plausible Messung (Zähler fehlt, Typ passt nicht, Spannungen unplausibel)
    4  API-Antwort unbrauchbar (HTTP-Fehler, Verbindungsabbruch)
    130 Process abgebrochen
"""

import argparse
import http.client
import json
import os
import signal
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

# Optional: installierte PV-Leistung in kWp, größer 0 und maximal 1000 (None = nicht übertragen)
PLANT_CAPACITY_KWP = None

# Alternative .env-Datei (Environment-Variable ENV_DATEI), Standard ist .env neben dem Script
ENV_DATEI = None

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "e3dc-rscp-1.1"
SMARTMETER_MODEL = "E3DC Hauskraftwerk"

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
    return float(wert)


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

    E3DC_HOST = einstellung("E3DC_HOST", E3DC_HOST)
    E3DC_USERNAME = einstellung("E3DC_USERNAME", E3DC_USERNAME)
    E3DC_PASSWORD = einstellung("E3DC_PASSWORD", E3DC_PASSWORD)
    RSCP_KEY = einstellung("RSCP_KEY", RSCP_KEY)
    LATITUDE = einstellung("LATITUDE", LATITUDE, float)
    LONGITUDE = einstellung("LONGITUDE", LONGITUDE, float)
    METER_INDEX = einstellung("METER_INDEX", METER_INDEX, int)
    PLANT_CAPACITY_KWP = einstellung("PLANT_CAPACITY_KWP", PLANT_CAPACITY_KWP, float)


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
        log("Warnung: Netzfrequenz nicht verfügbar – grid_frequency_hz wird nicht übertragen.")
        return None
    wert = round(wert, 2)
    if not FREQUENZ_MIN <= wert <= FREQUENZ_MAX:
        log(f"Warnung: Netzfrequenz {wert} Hz ist unplausibel – grid_frequency_hz wird nicht übertragen.")
        return None
    return wert


def payload_erstellen(daten, e3dc, index, typ):
    """Liefert den API-Payload aus einem Zählerdatensatz; wirft MesswertFehler bei unplausiblen Werten."""
    # pye3dc bis 0.9.x liefert die Messwerte innerhalb eines "data"-Containers
    daten = daten.get("data", daten)

    l1 = spannung(daten, 1)
    if l1 is None:
        raise MesswertFehler(
            f"L1: keine plausible Spannung (voltage L1 = {daten.get('voltage')}, "
            f"erwartet {SPANNUNG_MIN} bis {SPANNUNG_MAX} V)."
        )

    # Der Netzzähler meldet nicht gemessene Phasen mit 0 V; die API erwartet dann -1
    l2 = spannung(daten, 2)
    l3 = spannung(daten, 3)
    l2 = -1 if l2 is None else l2
    l3 = -1 if l3 is None else l3

    payload = {
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": l1,
        "l2_v": l2,
        "l3_v": l3,
        "smartmeter_model": SMARTMETER_MODEL,
        "integration_version": INTEGRATION_VERSION,
    }

    f = frequenz_lesen(daten, e3dc)
    if f is not None:
        payload["grid_frequency_hz"] = f

    if PLANT_CAPACITY_KWP is not None:
        payload["plant_capacity_kwp"] = PLANT_CAPACITY_KWP

    log(f"Benutzter Zähler: Index {index} Typ {typ or 'unbekannt'} | "
        f"L1={payload['l1_v']} L2={payload['l2_v']} L3={payload['l3_v']} V | "
        f"f={payload.get('grid_frequency_hz', '-')} Hz")
    return payload


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
    elif status == 403:
        raise ApiFehler(f"HTTP 403 – der Standort ist für die Annahme gesperrt: {text}")
    elif status == 422:
        raise ApiFehler(f"HTTP 422 – Payload abgelehnt: {text}")
    else:
        raise ApiFehler(f"Unerwarteter HTTP-Status {status}: {text}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="E3/DC-Messwerte an Ortsnetz-Auslastung senden.")
    parser.add_argument("--dry-run", action="store_true", help="Messung lesen und Payload nur ausgeben")
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

    payload = None
    try:
        index, typ = netzhaehler_finden(e3dc)
        daten = e3dc.get_powermeter_data(pmIndex=index, keepAlive=True)
        payload = payload_erstellen(daten, e3dc, index, typ)
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

    if payload is None:
        return EXIT_MESSUNG

    if args.dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    try:
        senden(payload)
    except ApiFehler as fehler:
        log(f"FEHLER: {fehler}")
        return EXIT_API

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
