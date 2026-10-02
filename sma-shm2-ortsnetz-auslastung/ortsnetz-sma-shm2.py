#!/usr/bin/env python3
"""
Ortsnetz-Auslastung – SMA Sunny Home Manager 2.0 und SMA Energy Meter.

Empfängt die Speedwire-Multicast-Telegramme (SMA-EMETER-Protokoll) direkt aus
dem lokalen Netzwerk, dekodiert Phasenspannungen und Netzfrequenz und sendet
die Messung sofort nach dem Start und danach alle fünf Minuten an
https://www.ortsnetz-auslastung.de/v1/measurements

Nur Python-Standardbibliothek, ab Python 3.8. Läuft auf jedem Linux-Rechner
(z. B. Raspberry Pi, NAS, Home-Server) im selben Layer-2-Netz wie der Zähler.

Aufruf:
    ortsnetz-sma-shm2.py            -> Dauerbetrieb, sendet alle 5 Minuten
    ortsnetz-sma-shm2.py --once     -> eine Messung senden und beenden
    ortsnetz-sma-shm2.py --dry-run  -> eine Messung dekodieren und Payload nur ausgeben
"""

import argparse
import json
import os
import socket
import struct
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
# Jeder Wert lässt sich alternativ per Umgebungsvariable setzen,
# z. B. ORTSNETZ_LATITUDE=52.520008 (praktisch für den Docker-Betrieb).
LATITUDE = konfig("LATITUDE", None)             # z. B. 52.520008
LONGITUDE = konfig("LONGITUDE", None)           # z. B. 13.404954

# IP-Adresse des lokalen Interfaces, über das der Multicast empfangen wird.
# "0.0.0.0" = Standard-Interface. Bei mehreren Interfaces oder VLANs die
# IP-Adresse des Interfaces im Zähler-Netz eintragen, z. B. "192.168.80.2" –
# sonst geht der Multicast-Beitritt über die Default-Route ins Leere.
INTERFACE_IP = konfig("INTERFACE_IP", "0.0.0.0", str)

# Seriennummer des Zählers (None = erstes gültiges Gerät je Messung). Nötig, wenn
# mehrere EMETER-Geräte im Netz senden; steht auf dem Typenschild und im Log.
METER_SERIAL = konfig("METER_SERIAL", None, int)    # z. B. 3011478221

INTERVAL_S = konfig("INTERVAL_S", 300, int)     # alle 5 Minuten
# -----------------------------------------------

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
VERSION = "sma-shm2-0.1.0"

MCAST_GRP = "239.12.255.254"
MCAST_PORT = 9522
EMETER_PROTOCOL_ID = 0x6069
TELEGRAM_TIMEOUT_S = 15     # maximale Wartezeit auf ein gültiges Telegramm

# OBIS-Messwert-Indizes im EMETER-Telegramm (Momentanwerte, Typ 4)
OBIS_FREQUENZ = 14          # in 0,001 Hz, nur Sunny Home Manager 2.0
OBIS_SPANNUNG = {1: 32, 2: 52, 3: 72}  # Phase -> Index, in 0,001 V


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def konfiguration_pruefen():
    for name, wert, grenze in (("LATITUDE", LATITUDE, 90), ("LONGITUDE", LONGITUDE, 180)):
        if wert is None or not -grenze <= wert <= grenze:
            raise ValueError(f"{name} muss zwischen {-grenze} und {grenze} gesetzt sein.")
    if INTERVAL_S <= 0:
        raise ValueError("INTERVAL_S muss größer als 0 sein.")
    if METER_SERIAL is not None and not 0 <= METER_SERIAL <= 0xFFFFFFFF:
        raise ValueError("METER_SERIAL muss eine vorzeichenlose 32-Bit-Zahl sein.")
    try:
        socket.inet_pton(socket.AF_INET, INTERFACE_IP)
    except OSError:
        raise ValueError("INTERFACE_IP muss eine lokale IPv4-Adresse sein.") from None


def telegramm_dekodieren(daten):
    """Dekodiert ein EMETER-Telegramm; liefert (seriennummer, {index: rohwert}) oder None."""
    # SMA Tag0, anschließend SMA Net 2; Länge schließt die Protokoll-ID ein.
    if len(daten) < 32 or daten[:8] != b"SMA\x00\x00\x04\x02\xa0":
        return None
    ende = 16 + int.from_bytes(daten[12:14], "big")
    if (ende < 28 or ende + 4 != len(daten) or daten[ende:] != b"\x00" * 4
            or daten[14:16] != b"\x00\x10"
            or int.from_bytes(daten[16:18], "big") != EMETER_PROTOCOL_ID):
        return None

    seriennummer = int.from_bytes(daten[20:24], "big")
    werte = {}
    pos = 28
    while pos < ende:
        if pos + 4 > ende:
            return None
        kanal, index, typ, tarif = daten[pos:pos + 4]
        if daten[pos:pos + 4] == b"\x90\x00\x00\x00":  # 144:0.0.0, Software-Version
            laenge = 8
        elif typ in (4, 8):  # Momentanwert bzw. Energiezähler
            laenge = 4 + typ
        else:
            return None
        if pos + laenge > ende:
            return None
        if kanal == 0 and tarif == 0 and typ == 4 and index in (14, 32, 52, 72):
            werte[index] = int.from_bytes(daten[pos + 4:pos + 8], "big")
        pos += laenge
    return seriennummer, werte


def multicast_socket():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", MCAST_PORT))
    mitgliedschaft = struct.pack(
        "4s4s", socket.inet_aton(MCAST_GRP), socket.inet_aton(INTERFACE_IP)
    )
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mitgliedschaft)
    return sock


def spannung(werte, phase):
    """Spannung einer Phase in Volt; -1, wenn nicht vorhanden oder unplausibel."""
    roh = werte.get(OBIS_SPANNUNG[phase])
    if roh is None:
        return -1
    volt = round(roh / 1000.0, 1)
    return volt if 0 < roh <= 500000 and volt > 0 else -1


def messung_empfangen(sock):
    """Wartet auf ein Telegramm mit gültiger L1-Spannung; liefert (seriennummer, werte) oder None."""
    ende = time.monotonic() + TELEGRAM_TIMEOUT_S
    while True:
        rest = ende - time.monotonic()
        if rest <= 0:
            return None
        sock.settimeout(rest)
        try:
            daten, _ = sock.recvfrom(65535)
        except socket.timeout:
            return None
        ergebnis = telegramm_dekodieren(daten)
        if ergebnis is None:
            continue
        seriennummer, werte = ergebnis
        if METER_SERIAL is not None and seriennummer != METER_SERIAL:
            continue
        if spannung(werte, 1) != -1:
            return seriennummer, werte


def payload_erstellen(werte):
    payload = {
        "observed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": spannung(werte, 1),
        "l2_v": spannung(werte, 2),
        "l3_v": spannung(werte, 3),
        "integration_version": VERSION,
    }

    roh_frequenz = werte.get(OBIS_FREQUENZ)
    if roh_frequenz is not None:
        frequenz = roh_frequenz / 1000.0
        if 45 <= frequenz <= 55:
            payload["grid_frequency_hz"] = round(frequenz, 2)

    return payload


def senden(payload):
    anfrage = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=15) as antwort:
            daten = json.load(antwort)
            if antwort.status != 202 or not isinstance(daten, dict) or daten.get("accepted") is not True:
                raise ValueError("API hat die Annahme der Messung nicht bestätigt.")
            log(f"OK: L1={payload['l1_v']} L2={payload['l2_v']} L3={payload['l3_v']} V, "
                f"f={payload.get('grid_frequency_hz', '-')} Hz")
            return True
    except urllib.error.HTTPError as fehler:
        log(f"HTTP {fehler.code}: {fehler.read().decode(errors='replace')}")
    except (OSError, ValueError) as fehler:
        log(f"Übertragung fehlgeschlagen: {fehler}")
    return False


def einmal(sock, dry_run=False):
    ergebnis = messung_empfangen(sock)
    if ergebnis is None:
        log(f"Kein gültiges EMETER-Telegramm innerhalb von {TELEGRAM_TIMEOUT_S} s empfangen – "
            f"Interface {INTERFACE_IP}, Multicast {MCAST_GRP}:{MCAST_PORT} prüfen.")
        return False
    seriennummer, werte = ergebnis
    payload = payload_erstellen(werte)
    if dry_run:
        log(f"Zähler-Seriennummer: {seriennummer}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return True
    return senden(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SMA-Messwerte an Ortsnetz-Auslastung senden.")
    modus = parser.add_mutually_exclusive_group()
    modus.add_argument("--once", action="store_true", help="Eine Messung senden und beenden")
    modus.add_argument("--dry-run", action="store_true", help="Eine Messung nur anzeigen")
    args = parser.parse_args(argv)
    try:
        konfiguration_pruefen()
    except ValueError as fehler:
        parser.error(str(fehler))

    try:
        with multicast_socket() as sock:
            if args.dry_run or args.once:
                return 0 if einmal(sock, dry_run=args.dry_run) else 1
            while True:
                start = time.monotonic()
                einmal(sock)
                # Laufend leeren: keine alten Telegramme beim nächsten Upload.
                while True:
                    rest = INTERVAL_S - (time.monotonic() - start)
                    if rest <= 0:
                        break
                    sock.settimeout(rest)
                    try:
                        sock.recvfrom(65535)
                    except socket.timeout:
                        pass
    except OSError as fehler:
        log(f"Netzwerkfehler: {fehler}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
