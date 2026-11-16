#!/usr/bin/env python3
"""
Ortsnetz-Auslastung – Shelly Pro 3EM / Pro 3EM-400 als Docker-Container.

Fragt den Shelly lokal über die RPC-Schnittstelle (EM.GetStatus) ab, sammelt
Minimum, Maximum und Mittelwert der Phasenspannungen und sendet die Messung
sofort nach dem Start und danach alle fünf Minuten an
https://www.ortsnetz-auslastung.de/v1/measurements

Es gibt keine lokale Datenhaltung und keine Wiederholungslogik: Ist der Shelly
oder die API einmal nicht erreichbar, wird die Messung verworfen und der
nächste Versuch erfolgt regulär zum nächsten Intervall.

Nur Python-Standardbibliothek, ab Python 3.8.

Aufruf:
    ortsnetz-shelly.py            -> Dauerbetrieb, sendet alle 5 Minuten
    ortsnetz-shelly.py --once     -> eine Messung senden und beenden
    ortsnetz-shelly.py --dry-run  -> eine Messung lesen und Payload nur ausgeben
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def konfig(name, standard, typ=float):
    """Liest ORTSNETZ_<name> aus der Umgebung (für Docker); sonst Standardwert."""
    wert = os.environ.get("ORTSNETZ_" + name)
    if wert is None or wert == "":
        return standard
    try:
        return typ(wert)
    except ValueError:
        raise SystemExit(f"FEHLER: ORTSNETZ_{name} hat ein ungültiges Format.") from None


# ---------------- Konfiguration ----------------
LATITUDE = konfig("LATITUDE", None)             # z. B. 52.520008
LONGITUDE = konfig("LONGITUDE", None)           # z. B. 13.404954
SHELLY_IP = konfig("SHELLY_IP", None, str)      # IP oder Hostname des Shelly
SHELLY_MODEL = konfig("SHELLY_MODEL", "Shelly Pro 3EM", str)
STROMWANDLER_A = konfig("CURRENT_TRANSFORMER_A", 120, int)  # 120 oder 400 (Pro 3EM-400)
CAPACITY_KWP = konfig("CAPACITY_KWP", None)     # optional: installierte PV-Leistung
BATTERY_KWH = konfig("BATTERY_KWH", None)       # optional: nutzbare Batteriekapazität
INTERVAL_S = konfig("INTERVAL_S", 300, int)     # Sendeintervall, mindestens 300
SAMPLE_INTERVAL_S = konfig("SAMPLE_INTERVAL_S", 15, int)  # Abfrage für min/max/avg
# -----------------------------------------------

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
VERSION = "shelly-docker-0.1.0"
SHELLY_TIMEOUT_S = 5
API_TIMEOUT_S = 15
PHASEN = ("a", "b", "c")


def endlich(wert):
    return isinstance(wert, (int, float)) and not isinstance(wert, bool) \
        and -float("inf") < wert < float("inf")


def spannung_gueltig(wert):
    return endlich(wert) and 150 <= wert <= 300


def strom_gueltig(wert):
    return endlich(wert) and 0 <= wert <= STROMWANDLER_A


def frequenz_gueltig(wert):
    return endlich(wert) and 45 <= wert <= 55


def runden(wert):
    return round(wert, 2)


def konfiguration_pruefen():
    """Gibt eine Fehlermeldung zurück oder None, wenn alles in Ordnung ist."""
    if not endlich(LATITUDE) or not -90 <= LATITUDE <= 90:
        return "ORTSNETZ_LATITUDE fehlt oder liegt nicht zwischen -90 und 90."
    if not endlich(LONGITUDE) or not -180 <= LONGITUDE <= 180:
        return "ORTSNETZ_LONGITUDE fehlt oder liegt nicht zwischen -180 und 180."
    if not SHELLY_IP:
        return "ORTSNETZ_SHELLY_IP fehlt."
    if INTERVAL_S < 300:
        return "ORTSNETZ_INTERVAL_S muss mindestens 300 Sekunden betragen."
    if not 0 < SAMPLE_INTERVAL_S <= INTERVAL_S:
        return "ORTSNETZ_SAMPLE_INTERVAL_S muss größer 0 und höchstens so groß wie das Sendeintervall sein."
    if CAPACITY_KWP is not None and not 0 < CAPACITY_KWP <= 1000:
        return "ORTSNETZ_CAPACITY_KWP muss größer 0 und höchstens 1000 sein."
    if BATTERY_KWH is not None and not 0 <= BATTERY_KWH <= 150:
        return "ORTSNETZ_BATTERY_KWH muss zwischen 0 und 150 liegen."
    return None


def shelly_lesen():
    """Liest den Status der Energiemessung (em:0) per RPC; wirft bei Fehlern OSError/ValueError."""
    url = f"http://{SHELLY_IP}/rpc/EM.GetStatus?id=0"
    with urllib.request.urlopen(url, timeout=SHELLY_TIMEOUT_S) as antwort:
        status = json.loads(antwort.read(65536))
    if not isinstance(status, dict):
        raise ValueError("unerwartete Antwort des Shelly")
    return status


def neue_statistik():
    return [{"min": None, "max": None, "summe": 0.0, "anzahl": 0} for _ in PHASEN]


def statistik_erfassen(statistik, status):
    for index, phase in enumerate(PHASEN):
        wert = status.get(f"{phase}_voltage")
        if not spannung_gueltig(wert):
            continue
        wert = runden(wert)
        eintrag = statistik[index]
        eintrag["min"] = wert if eintrag["anzahl"] == 0 else min(eintrag["min"], wert)
        eintrag["max"] = wert if eintrag["anzahl"] == 0 else max(eintrag["max"], wert)
        eintrag["summe"] += wert
        eintrag["anzahl"] += 1


def payload_erstellen(status, statistik=None):
    """Baut den Request-Body; None, wenn keine Phase eine gültige Spannung hat."""
    spannungen = [status.get(f"{p}_voltage") for p in PHASEN]
    if not any(spannung_gueltig(u) for u in spannungen):
        return None
    payload = {
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "smartmeter_model": SHELLY_MODEL[:120],
        "integration_version": VERSION,
    }
    for index, phase in enumerate(PHASEN):
        name = f"l{index + 1}"
        gueltig = spannung_gueltig(spannungen[index])
        payload[f"{name}_v"] = runden(spannungen[index]) if gueltig else -1
        if statistik and statistik[index]["anzahl"] > 0:
            eintrag = statistik[index]
            mittel = runden(eintrag["summe"] / eintrag["anzahl"])
            payload[f"{name}_v_min"] = eintrag["min"]
            payload[f"{name}_v_max"] = eintrag["max"]
            # min <= avg <= max trotz Rundung sicherstellen
            payload[f"{name}_v_avg"] = max(eintrag["min"], min(eintrag["max"], mittel))
        strom = status.get(f"{phase}_current")
        if gueltig and strom_gueltig(strom):
            payload[f"{name}_a"] = strom
        frequenz = status.get(f"{phase}_freq")
        if gueltig and "grid_frequency_hz" not in payload and frequenz_gueltig(frequenz):
            payload["grid_frequency_hz"] = frequenz
    if endlich(status.get("total_act_power")):
        payload["grid_power_w"] = status["total_act_power"]
    scheinleistung = status.get("total_aprt_power")
    if endlich(scheinleistung) and scheinleistung >= 0:
        payload["apparent_power_va"] = scheinleistung
    if CAPACITY_KWP is not None:
        payload["plant_capacity_kwp"] = CAPACITY_KWP
    if BATTERY_KWH is not None:
        payload["battery_capacity"] = BATTERY_KWH
    return payload


def werte_text(payload):
    """Übertragene Werte als kurze Logzeile, z. B. 'L1 230.8 V, L2 229.0 V, L3 231.0 V, 50.00 Hz, -350.5 W'."""
    teile = []
    for phase in ("l1", "l2", "l3"):
        wert = payload.get(f"{phase}_v", -1)
        teile.append(f"{phase.upper()} {wert} V" if wert != -1 else f"{phase.upper()} -")
    if "grid_frequency_hz" in payload:
        teile.append(f"{payload['grid_frequency_hz']:.2f} Hz")
    if "grid_power_w" in payload:
        teile.append(f"{payload['grid_power_w']} W")
    return ", ".join(teile)


def senden(payload):
    """Sendet die Messung; True nur bei bestätigter Annahme (HTTP 202, accepted)."""
    anfrage = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=API_TIMEOUT_S) as antwort:
            status = antwort.status
            antwort_daten = json.loads(antwort.read(65536))
    except urllib.error.HTTPError as fehler:
        log(f"API lehnt Messung ab: HTTP {fehler.code}")
        return False
    except (OSError, ValueError) as fehler:
        log(f"Senden fehlgeschlagen: {fehler}")
        return False
    if status != 202 or not isinstance(antwort_daten, dict) or antwort_daten.get("accepted") is not True:
        log(f"API hat die Annahme nicht bestätigt (HTTP {status})")
        return False
    log(f"Messung angenommen (HTTP 202), Ampel: {antwort_daten.get('status', {}).get('overall', '?')}"
        f" | gesendet: {werte_text(payload)}")
    return True


def log(text):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {text}", flush=True)


def einmal(dry_run=False, statistik=None):
    """Liest den Shelly und sendet (oder gibt aus). Rückgabe: Exitcode 0/1."""
    try:
        status = shelly_lesen()
    except (OSError, ValueError) as fehler:
        log(f"Shelly nicht lesbar: {fehler}")
        return 1
    payload = payload_erstellen(status, statistik)
    if payload is None:
        log("Keine gültige Phasenspannung; Messung verworfen")
        return 1
    if dry_run:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    return 0 if senden(payload) else 1


def dauerbetrieb():
    """Sendet sofort nach dem Start, danach alle INTERVAL_S Sekunden mit min/max/avg."""
    statistik = neue_statistik()
    naechster_versand = time.monotonic()  # erste Messung sofort
    erster = True
    while True:
        try:
            status = shelly_lesen()
        except (OSError, ValueError) as fehler:
            log(f"Shelly nicht lesbar: {fehler}")
            status = None
        if status is not None:
            statistik_erfassen(statistik, status)
        if time.monotonic() >= naechster_versand:
            naechster_versand += INTERVAL_S
            if status is not None:
                payload = payload_erstellen(status, None if erster else statistik)
                if payload is None:
                    log("Keine gültige Phasenspannung; Intervall übersprungen")
                else:
                    senden(payload)
            else:
                log("Intervall übersprungen (kein Shelly-Messwert)")
            erster = False
            statistik = neue_statistik()
        time.sleep(SAMPLE_INTERVAL_S)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Shelly Pro 3EM -> Ortsnetz-Auslastung")
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument("--once", action="store_true", help="eine Messung senden und beenden")
    gruppe.add_argument("--dry-run", action="store_true", help="Messung lesen, Payload nur ausgeben")
    args = parser.parse_args(argv)
    fehler = konfiguration_pruefen()
    if fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        return 2
    if args.once or args.dry_run:
        return einmal(dry_run=args.dry_run)
    log(f"Start: Shelly {SHELLY_IP}, Intervall {INTERVAL_S} s, Abfrage alle {SAMPLE_INTERVAL_S} s")
    try:
        dauerbetrieb()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
