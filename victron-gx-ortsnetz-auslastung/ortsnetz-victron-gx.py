#!/usr/bin/env python3
"""
Ortsnetz-Auslastung – läuft direkt auf dem Victron GX (Cerbo, Venus OS).
Kein Modbus, kein mbpoll: Liest die Werte lokal über D-Bus und sendet sie an
https://www.ortsnetz-auslastung.de/v1/measurements

Quelle KI Claude (automatisch gesucht, in dieser Reihenfolge):
  1. Netzzähler (grid)        /Ac/L{1,2,3}/Voltage     und  /Ac/Frequency
  2. VE.Bus (Multi/Quattro)   /Ac/ActiveIn/L{1,2,3}/V  und  /Ac/ActiveIn/L1/F

Installation (per SSH als root auf dem GX):
  mkdir -p /data/ortsnetz
  -> diese Datei nach /data/ortsnetz/ortsnetz-victron-gx.py kopieren, CONFIG anpassen
  python3 /data/ortsnetz/ortsnetz-victron-gx.py --once        # Test
  Autostart: siehe Kommentar am Ende der Datei
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

import dbus

# ---------------- Konfiguration ----------------
LATITUDE = 52.520008
LONGITUDE = 13.404954
# Optional: Nur die tatsächliche installierte PV-Leistung in kWp eintragen.
# Bei unbekannter Anlagengröße oder ohne PV-Anlage None lassen; der Wert wird dann nicht übertragen.
PLANT_KWP = None
PV_FORECAST_KWH = None      # optional, z. B. 24.5
SMARTMETER_MODEL = "Victron GX"
INTERVAL_S = 300            # alle 5 Minuten
# -----------------------------------------------

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
VERSION = "venus-dbus-0.1.2"

bus = dbus.SystemBus()


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def get(service, path):
    """D-Bus GetValue; liefert float oder None (ungültig = leeres Array)."""
    try:
        v = bus.get_object(service, path).GetValue(
            dbus_interface="com.victronenergy.BusItem",
            timeout=3,
        )
        if isinstance(v, dbus.Array) or v is None:
            return None
        return float(v)
    except Exception:
        return None


def find_service(prefix):
    for name in bus.list_names():
        if str(name).startswith(prefix):
            return str(name)
    return None


def valid_v(v):
    return round(v, 1) if v is not None and 150 <= v <= 300 else -1


def valid_forecast(v):
    return round(v, 2) if isinstance(v, (int, float)) and 0 <= v <= 100000 else None


def read_values():
    svc = find_service("com.victronenergy.grid.")
    if svc:
        volts = [get(svc, f"/Ac/L{i}/Voltage") for i in (1, 2, 3)]
        freq = get(svc, "/Ac/Frequency")
        if valid_v(volts[0]) != -1:
            return svc, volts, freq

    svc = find_service("com.victronenergy.vebus.")
    if svc:
        volts = [get(svc, f"/Ac/ActiveIn/L{i}/V") for i in (1, 2, 3)]
        freq = get(svc, "/Ac/ActiveIn/L1/F")
        if valid_v(volts[0]) != -1:
            return svc, volts, freq

    return None, [None, None, None], None


def send_once():
    svc, volts, freq = read_values()
    l1, l2, l3 = (valid_v(v) for v in volts)
    if l1 == -1:
        log(f"Keine gültige L1-Spannung (Quelle: {svc or 'keine gefunden'}) – übersprungen")
        return

    payload = {
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": l1,
        "l2_v": l2,
        "l3_v": l3,
        "smartmeter_model": SMARTMETER_MODEL,
        "integration_version": VERSION,
    }
    if freq is not None and 45 <= freq <= 55:
        payload["grid_frequency_hz"] = round(freq, 2)
    if PLANT_KWP:
        payload["plant_capacity_kwp"] = PLANT_KWP
    forecast = valid_forecast(PV_FORECAST_KWH)
    if forecast is not None:
        payload["pv_forecast_kwh"] = forecast

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode() or "{}")
            overall = body.get("status", {}).get("overall", "?")
            log(f"OK ({svc}): L1={l1} L2={l2} L3={l3} V, "
                f"f={payload.get('grid_frequency_hz', '-')} Hz -> {overall}")
    except urllib.error.HTTPError as e:
        log(f"HTTP {e.code}: {e.read().decode(errors='replace')}")
    except Exception as e:
        log(f"Übertragung fehlgeschlagen: {e}")


if __name__ == "__main__":
    if "--once" in sys.argv:
        send_once()
        sys.exit(0)
    while True:
        send_once()
        time.sleep(INTERVAL_S)

# ---------------------------------------------------------------------------
# Autostart (überlebt Firmware-Updates, weil alles unter /data liegt):
#
#   Datei /data/rc.local anlegen bzw. ergänzen:
#       #!/bin/sh
#       nohup python3 /data/ortsnetz/ortsnetz-victron-gx.py >> /data/ortsnetz/ortsnetz-victron-gx.log 2>&1 &
#
#   chmod +x /data/rc.local
#   Danach GX neu starten oder die nohup-Zeile einmal von Hand ausführen.
# 
#
# Variante ohne Log, um Diskspace und Schreibvorgänge auf der SD-Karte zu sparen
# nohup python3 /data/scripts/ortsnetz-victron-gx.py > /dev/null 2>&1 &
# ---------------------------------------------------------------------------
