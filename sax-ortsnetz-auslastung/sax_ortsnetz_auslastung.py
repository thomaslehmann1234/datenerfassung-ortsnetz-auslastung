#!/usr/bin/env python3
"""Sendet Netzspannungen eines SAX Power Smartmeters (Modbus TCP) an Ortsnetz-Auslastung.

Liest L1, L2, L3 und die Netzfrequenz (SunSpec Model 203) vom SAX-Master per Modbus TCP
und sendet sofort nach dem Start und danach alle 300 Sekunden an die API.

Aufruf:
  python3 sax_ortsnetz_auslastung.py             Dauerbetrieb
  python3 sax_ortsnetz_auslastung.py --dry-run   Messung lesen und Payload anzeigen, nichts senden
  python3 sax_ortsnetz_auslastung.py --simulate  Testwerte statt Modbus (ohne Zähler testbar)

Version: 0.1.0
Erstellt: 2026-10-08
Geändert: 2026-10-08 - V0.1.0: Erstversion
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from pyModbusTCP.client import ModbusClient
from pyModbusTCP.constants import MB_EXCEPT_ERR

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
CONFIG = {
    "latitude": None,                # z. B. 52.520008 (Pflicht, siehe README "Koordinaten")
    "longitude": None,               # z. B. 13.404954 (Pflicht)
    "modbus_host": "192.168.1.100",  # IP des SAX-Masters
    "modbus_port": 502,
    "modbus_unit_id": 100,           # SunSpec-Modus
    "modbus_timeout_s": 5,
    # Registeradressen direkt (ohne 40001-Offset), Function Code 3
    "register_voltage_l1": 40062,
    "register_voltage_l2": 40063,
    "register_voltage_l3": 40064,
    "register_voltage_sf": 40069,    # Skalierungsfaktor Spannung, int16 (typisch -1)
    "register_frequency": 40070,     # None = Frequenz nicht senden
    "register_frequency_sf": 40071,  # Skalierungsfaktor Frequenz, int16 (typisch -2)
    "interval_s": 300,
    "smartmeter_model": "SAX Power Smartmeter",
}

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
VERSION = "0.1.0"
INTEGRATION_VERSION = f"sax-{VERSION}"

HTTP_TIMEOUT_S = 10
READ_ATTEMPTS = 3
READ_PAUSE_S = 0.5               # SAX: höchstens ein Zugriff je 500 ms
VOLTAGE_RANGE = (150.0, 300.0)
FREQUENCY_RANGE = (45.0, 55.0)


class MeasurementError(RuntimeError):
    pass


def to_int16(raw):
    return raw - 65536 if raw > 32767 else raw


def in_range(value, limits):
    return limits[0] <= value <= limits[1]


def read_registers(address, count):
    """Liest Holding-Register mit Wiederholung; verbindet je Zugriff neu."""
    reasons = []
    for attempt in range(1, READ_ATTEMPTS + 1):
        client = ModbusClient(host=CONFIG["modbus_host"], port=CONFIG["modbus_port"],
                              unit_id=CONFIG["modbus_unit_id"], timeout=CONFIG["modbus_timeout_s"])
        if client.open():
            try:
                values = client.read_holding_registers(address, count)
            finally:
                client.close()
            if values:
                return values
            reason = "leere Antwort"
        else:
            reason = "Verbindung fehlgeschlagen"
        if client.last_error == MB_EXCEPT_ERR:
            reason += f": {client.last_error_as_txt} ({client.last_except_as_txt})"
        else:
            reason += f": {client.last_error_as_txt}"
        reasons.append(reason)
        if attempt < READ_ATTEMPTS:
            time.sleep(READ_PAUSE_S)
    raise MeasurementError(f"Modbus-Lesen ab Register {address} nach {READ_ATTEMPTS} Versuchen "
                           f"fehlgeschlagen ({' | '.join(reasons)})")


def decode(registers, start):
    """Wandelt die Rohregister (ab `start`) in Spannungen und Frequenz um.

    Returns:
        (l1, l2, l3, frequenz) mit -1 für nicht plausible L2/L3-Werte, Frequenz None wenn
        nicht vorhanden oder nicht plausibel.
    Raises:
        MeasurementError: L1 nicht plausibel.
    """
    def raw(address):
        return registers[address - start]

    factor_v = 10 ** to_int16(raw(CONFIG["register_voltage_sf"]))
    phases = [round(raw(CONFIG[key]) * factor_v, 1)
              for key in ("register_voltage_l1", "register_voltage_l2", "register_voltage_l3")]
    if not in_range(phases[0], VOLTAGE_RANGE):
        raise MeasurementError(f"L1 nicht plausibel: {phases[0]} V")
    l1, l2, l3 = (v if in_range(v, VOLTAGE_RANGE) else -1 for v in phases)

    frequency = None
    if CONFIG["register_frequency"] is not None:
        value = round(raw(CONFIG["register_frequency"])
                      * 10 ** to_int16(raw(CONFIG["register_frequency_sf"])), 2)
        if in_range(value, FREQUENCY_RANGE):
            frequency = value
    return l1, l2, l3, frequency


def read_modbus():
    addresses = [CONFIG[key] for key in ("register_voltage_l1", "register_voltage_l2",
                                         "register_voltage_l3", "register_voltage_sf")]
    if CONFIG["register_frequency"] is not None:
        addresses += [CONFIG["register_frequency"], CONFIG["register_frequency_sf"]]
    start = min(addresses)
    return decode(read_registers(start, max(addresses) - start + 1), start)


def read_simulated():
    def noisy(base, spread):
        return round(base + random.uniform(-spread, spread), 1)
    frequency = round(50.0 + random.uniform(-0.05, 0.05), 2) \
        if CONFIG["register_frequency"] is not None else None
    return noisy(230.0, 2.0), noisy(230.0, 2.0), noisy(230.0, 2.0), frequency


def build_payload(l1, l2, l3, frequency):
    payload = {
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": CONFIG["latitude"],
        "longitude": CONFIG["longitude"],
        "l1_v": l1,
        "l2_v": l2,
        "l3_v": l3,
        "smartmeter_model": CONFIG["smartmeter_model"][:120],
        "integration_version": INTEGRATION_VERSION[:32],
    }
    if frequency is not None:
        payload["grid_frequency_hz"] = frequency
    return payload


def send(payload):
    request = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            status, body = response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status, body = error.code, error.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as error:
        raise MeasurementError(f"API nicht erreichbar: {error}") from error
    if status != 202:
        raise MeasurementError(f"API antwortete mit HTTP {status}: {body[:300]}")
    try:
        overall = (json.loads(body).get("status") or {}).get("overall")
    except ValueError:
        overall = None
    return overall


def log(level, message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{level}] {message}", flush=True)


def run_cycle(args):
    """Ein Zyklus. Returns True bei Erfolg."""
    try:
        values = read_simulated() if args.simulate else read_modbus()
        payload = build_payload(*values)
        if args.dry_run:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return True
        overall = send(payload)
    except MeasurementError as error:
        log("ERROR", error)
        return False
    except Exception as error:  # nie abstürzen, im nächsten Intervall erneut versuchen
        log("ERROR", f"Unerwarteter Fehler: {error!r}")
        return False
    log("INFO", f"Gesendet (HTTP 202): L1 {payload['l1_v']} V, L2 {payload['l2_v']} V, "
                f"L3 {payload['l3_v']} V, Ampel {overall}")
    if overall == "yellow":
        log("WARNING", "Ortsnetz-Bewertung: yellow")
    return True


def main():
    parser = argparse.ArgumentParser(description="SAX-Smartmeter-Messwerte an Ortsnetz-Auslastung senden.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Eine Messung lesen und den Payload anzeigen, nichts senden")
    parser.add_argument("--simulate", action="store_true",
                        help="Testwerte statt Modbus-Zugriff verwenden")
    args = parser.parse_args()

    for key in ("latitude", "longitude"):
        if not isinstance(CONFIG[key], (int, float)):
            print(f"CONFIG['{key}'] ist nicht gesetzt.", file=sys.stderr)
            sys.exit(2)
    if not (-90 <= CONFIG["latitude"] <= 90 and -180 <= CONFIG["longitude"] <= 180):
        print("Koordinaten außerhalb des gültigen Bereichs.", file=sys.stderr)
        sys.exit(2)

    if args.dry_run:
        sys.exit(0 if run_cycle(args) else 1)

    log("INFO", f"Start {INTEGRATION_VERSION}, Intervall {CONFIG['interval_s']} s"
                f"{' (Simulation)' if args.simulate else ''}")
    while True:
        started = time.monotonic()
        run_cycle(args)
        time.sleep(max(1.0, CONFIG["interval_s"] - (time.monotonic() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
