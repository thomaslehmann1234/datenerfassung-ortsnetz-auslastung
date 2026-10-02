#!/usr/bin/env python3
"""Sendet Netzspannungen aus einer evcc-nahen Shelly- oder Modbus-Quelle."""

import json
import math
import socket
import struct
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# Quelle: "shelly" (Shelly Gen2/3 EM) oder "modbus" (Modbus TCP)
SOURCE = "shelly"

LATITUDE = 52.520008
LONGITUDE = 13.404954
PLANT_CAPACITY_KWP = 10.0       # None = nicht senden
PV_FORECAST_KWH = None          # None = nicht senden
SMARTMETER_MODEL = ""           # optional

# Shelly Gen2/3: z. B. Shelly Pro 3EM. EM.GetStatus liefert a/b/c_voltage.
SHELLY_HOST = "192.168.1.50"
SHELLY_EM_ID = 0
SHELLY_SINGLE_PHASE = False     # Pro EM50: True, L2/L3 werden -1

# Modbus TCP. Registeradressen sind nullbasiert (also z. B. 0 für 30001).
MODBUS_HOST = "192.168.1.51"
MODBUS_PORT = 502
MODBUS_UNIT_ID = 1
MODBUS_FUNCTION = 4             # 3 = Holding, 4 = Input Register
MODBUS_VALUE_TYPE = "float32"  # float32 oder uint16
MODBUS_WORD_SWAP = False
MODBUS_L1_REGISTER = None
MODBUS_L2_REGISTER = None
MODBUS_L3_REGISTER = None
MODBUS_FREQUENCY_REGISTER = None

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "evcc-source-py-1.0"


class MeasurementError(RuntimeError):
    pass


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise MeasurementError(f"Abruf fehlgeschlagen: {error}") from error


def valid(value, minimum, maximum, name):
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise MeasurementError(f"{name} ist keine Zahl.") from error
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise MeasurementError(f"{name} liegt außerhalb von {minimum} bis {maximum}.")
    return round(value, 2)


def read_shelly():
    status = get_json(f"http://{SHELLY_HOST}/rpc/EM.GetStatus?id={SHELLY_EM_ID}")
    l1 = valid(status.get("a_voltage"), 100, 300, "Shelly L1")
    if SHELLY_SINGLE_PHASE:
        l2 = l3 = -1
    else:
        l2 = valid(status.get("b_voltage"), 100, 300, "Shelly L2")
        l3 = valid(status.get("c_voltage"), 100, 300, "Shelly L3")
    frequency = status.get("a_freq")
    return l1, l2, l3, frequency


def modbus_value(register):
    if register is None:
        return None
    count = 2 if MODBUS_VALUE_TYPE == "float32" else 1
    transaction_id = 1
    request = struct.pack(">HHHBBHH", transaction_id, 0, 6, MODBUS_UNIT_ID, MODBUS_FUNCTION, register, count)
    try:
        with socket.create_connection((MODBUS_HOST, MODBUS_PORT), timeout=5) as connection:
            connection.sendall(request)
            header = receive_exact(connection, 7)
            response_transaction, protocol, length, unit_id = struct.unpack(">HHHB", header)
            if response_transaction != transaction_id or protocol != 0 or unit_id != MODBUS_UNIT_ID:
                raise MeasurementError("Ungültige Modbus-Antwort.")
            pdu = receive_exact(connection, length - 1)
    except OSError as error:
        raise MeasurementError(f"Modbus-Verbindung fehlgeschlagen: {error}") from error

    function, byte_count = pdu[0], pdu[1]
    if function & 0x80:
        raise MeasurementError(f"Modbus-Fehlercode {pdu[1]}.")
    if function != MODBUS_FUNCTION or byte_count != count * 2:
        raise MeasurementError("Unerwartete Modbus-Nutzdaten.")
    registers = list(struct.unpack(">" + "H" * count, pdu[2:]))
    if MODBUS_VALUE_TYPE == "uint16":
        return registers[0]
    if MODBUS_VALUE_TYPE == "float32":
        if MODBUS_WORD_SWAP:
            registers.reverse()
        return struct.unpack(">f", struct.pack(">HH", *registers))[0]
    raise MeasurementError("MODBUS_VALUE_TYPE muss float32 oder uint16 sein.")


def receive_exact(connection, size):
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise MeasurementError("Modbus-Verbindung wurde vorzeitig geschlossen.")
        data += chunk
    return data


def read_modbus():
    l1 = valid(modbus_value(MODBUS_L1_REGISTER), 100, 300, "Modbus L1")
    l2 = valid(modbus_value(MODBUS_L2_REGISTER), 100, 300, "Modbus L2")
    l3 = valid(modbus_value(MODBUS_L3_REGISTER), 100, 300, "Modbus L3")
    return l1, l2, l3, modbus_value(MODBUS_FREQUENCY_REGISTER)


def payload():
    if SOURCE == "shelly":
        l1, l2, l3, frequency = read_shelly()
    elif SOURCE == "modbus":
        l1, l2, l3, frequency = read_modbus()
    else:
        raise MeasurementError("SOURCE muss shelly oder modbus sein.")

    result = {
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": l1,
        "l2_v": l2,
        "l3_v": l3,
        "integration_version": INTEGRATION_VERSION,
    }
    if frequency is not None:
        result["grid_frequency_hz"] = valid(frequency, 45, 55, "Netzfrequenz")
    if PLANT_CAPACITY_KWP is not None:
        result["plant_capacity_kwp"] = valid(PLANT_CAPACITY_KWP, 0.01, 1000, "PV-Leistung")
    if PV_FORECAST_KWH is not None:
        result["pv_forecast_kwh"] = valid(PV_FORECAST_KWH, 0, 100000, "PV-Prognose")
    if SMARTMETER_MODEL.strip():
        result["smartmeter_model"] = SMARTMETER_MODEL.strip()[:120]
    return result


def send(data):
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 202:
                raise MeasurementError(f"API antwortet mit HTTP {response.status}.")
    except urllib.error.HTTPError as error:
        raise MeasurementError(f"API antwortet mit HTTP {error.code}: {error.read().decode(errors='replace')}") from error
    except urllib.error.URLError as error:
        raise MeasurementError(f"API-Verbindung fehlgeschlagen: {error}") from error


def main():
    try:
        data = payload()
        if "--dry-run" in sys.argv:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            send(data)
            print("Messung übertragen.")
    except MeasurementError as error:
        raise SystemExit(f"FEHLER: {error}")


if __name__ == "__main__":
    main()
