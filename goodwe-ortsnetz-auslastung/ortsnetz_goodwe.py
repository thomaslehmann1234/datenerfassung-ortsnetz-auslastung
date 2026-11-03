#!/usr/bin/env python3
"""
ortsnetz_goodwe.py

Liest die Phasenspannungen, die Netzfrequenz und weitere Messwerte des GoodWe
Smart Meters am Netzanschlusspunkt über die Modbus-TCP-Schnittstelle eines
GoodWe-Hybridwechselrichters (ET-Plattform, z. B. GW10KN-ET) und sendet sie an
https://www.ortsnetz-auslastung.de

Nur Python-Standardbibliothek, ab Python 3.8. Es wird ausschließlich lesend
auf den Wechselrichter zugegriffen (Modbus-Funktion 03).
Jeder Aufruf führt genau eine Messung und Übertragung aus.

Aufruf:
	ortsnetz_goodwe.py            -> abrufen und senden
	ortsnetz_goodwe.py --dry-run  -> abrufen und Payload nur ausgeben

Crontab (alle 5 Minuten):
	*/5 * * * * /usr/bin/python3 /opt/ortsnetz-goodwe/ortsnetz_goodwe.py >> $HOME/ortsnetz-goodwe.log 2>&1

Die Konfiguration kann statt im Konfigurationsblock auch per Environment-Variablen
erfolgen, siehe README.md.
"""

import http.client
import json
import os
import socket
import struct
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ============================ Konfiguration ============================

# Alle Werte dieses Blocks außer API_URL und INTEGRATION_VERSION können auch als
# gleichnamige Environment-Variablen gesetzt werden, diese haben Vorrang vor den Werten hier

# IP-Adresse oder Hostname des GoodWe-Wechselrichters, muss gesetzt werden
GOODWE_HOST = ""
# Modbus-TCP-Port, Standard 502
GOODWE_PORT = 502
# Modbus Unit-ID, GoodWe verwendet standardmäßig 247 (0xF7)
GOODWE_UNIT_ID = 247

# Messquelle der Spannungen:
#   "meter"          -> GoodWe Smart Meter am Netzanschlusspunkt (empfohlen)
#   "wechselrichter" -> AC-Klemmen des Wechselrichters, nur wenn die Firmware keine Zählerspannungen liefert
GOODWE_QUELLE = "meter"

# Ungefährer Standort in Dezimalgrad, muss gesetzt werden
LATITUDE = None		# z. B. 52.52
LONGITUDE = None	# z. B. 13.40

# Optional: installierte PV-Leistung in kWp, größer 0 und maximal 1000 (None = wird nicht übertragen)
PLANT_CAPACITY_KWP = None	# z. B. 9.8
# Optional: nutzbare Batteriekapazität in kWh, größer 0 (None = wird nicht übertragen)
BATTERY_CAPACITY_KWH = None	# z. B. 10.2
# Optional: Hersteller und Modell des Zählers, z. B. "GoodWe GM3000" (None = automatisch)
SMARTMETER_MODEL = None

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "goodwe-0.1.0"

# =======================================================================

# Register der GoodWe ET-Plattform (ET, EH, BT, BH, GW…K-ET, GW…KN-ET)
REG_MODELL = 35011			# 5 Register ASCII, z. B. "GW10KN-ET"
REG_WR_PHASEN = 35121		# je Phase 5 Register: Spannung 0,1 V, Strom 0,1 A, Frequenz 0,01 Hz, -, Leistung
REG_BATTERIE_SPANNUNG = 35180	# 0,1 V
REG_METER = 36000			# Smart-Meter-Block 36000 bis 36057
METER_ANZAHL = 58
REG_BATTERIE_SOC = 37007	# %

# Offsets im Smart-Meter-Block
METER_KOMMUNIKATION = 4		# 36004: 1 = Kommunikation in Ordnung
METER_FREQUENZ = 14			# 36014: 0,01 Hz
METER_WIRKLEISTUNG = 25		# 36025/36026: int32 W, positiv = Einspeisung
METER_SCHEINLEISTUNG = 41	# 36041/36042: int32 VA, Vorzeichen folgt der Energierichtung
METER_SPANNUNG = 52			# 36052 bis 36054: 0,1 V
METER_STROM = 55			# 36055 bis 36057: 0,1 A

UNGUELTIG = 0xFFFF


class MesswertFehler(Exception):
	pass


def log(text):
	zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	print(f"{zeit} {text}", flush=True)


def zahl(wert):
	"""Liefert wert als float oder None, wenn es keine Zahl ist."""
	if isinstance(wert, bool) or not isinstance(wert, (int, float)):
		return None
	return float(wert)


def int16(wert):
	return wert - 0x10000 if wert & 0x8000 else wert


def int32(hoch, tief):
	wert = (hoch << 16) | tief
	return wert - 0x100000000 if wert & 0x80000000 else wert


class ModbusVerbindung:
	"""Minimaler Modbus-TCP-Client, der nur Holding Register liest (Funktion 03)."""

	def __init__(self, host, port, unit_id, timeout=5):
		self.unit_id = unit_id
		self.transaktion = 0
		try:
			self.sock = socket.create_connection((host, port), timeout=timeout)
		except OSError as fehler:
			raise MesswertFehler(f"Verbindung zu {host}:{port} fehlgeschlagen: {fehler}")
		self.sock.settimeout(timeout)

	def __enter__(self):
		return self

	def __exit__(self, *_):
		self.sock.close()

	def _empfangen(self, anzahl):
		daten = b""
		while len(daten) < anzahl:
			teil = self.sock.recv(anzahl - len(daten))
			if not teil:
				raise MesswertFehler("Der Wechselrichter hat die Modbus-Verbindung geschlossen.")
			daten += teil
		return daten

	def lesen(self, start, anzahl):
		"""Liefert anzahl Register ab start als Liste vorzeichenloser 16-Bit-Werte."""
		self.transaktion = (self.transaktion + 1) & 0xFFFF
		anfrage = struct.pack(">HHHBBHH", self.transaktion, 0, 6, self.unit_id, 3, start, anzahl)
		try:
			self.sock.sendall(anfrage)
			transaktion, protokoll, laenge, _, funktion = struct.unpack(">HHHBB", self._empfangen(8))
			rest = self._empfangen(laenge - 2)
		except (OSError, struct.error) as fehler:
			raise MesswertFehler(f"Lesen der Register ab {start} fehlgeschlagen: {fehler}")

		if transaktion != self.transaktion or protokoll != 0:
			raise MesswertFehler(f"Unerwartete Modbus-Antwort beim Lesen der Register ab {start}.")
		if funktion != 3:
			code = rest[0] if rest else None
			raise MesswertFehler(f"Modbus-Fehler {code} beim Lesen der Register ab {start}.")
		if not rest or rest[0] != 2 * anzahl or len(rest) != 1 + 2 * anzahl:
			raise MesswertFehler(f"Unvollständige Modbus-Antwort beim Lesen der Register ab {start}.")
		return list(struct.unpack(f">{anzahl}H", rest[1:]))


def verbinden():
	"""Baut die Modbus-Verbindung auf, bei einem Fehler wird einmal nach zwei Sekunden wiederholt."""
	try:
		return ModbusVerbindung(GOODWE_HOST, GOODWE_PORT, GOODWE_UNIT_ID)
	except MesswertFehler:
		time.sleep(2)
		return ModbusVerbindung(GOODWE_HOST, GOODWE_PORT, GOODWE_UNIT_ID)


def spannung(roh):
	"""Liefert eine Registerspannung (0,1 V) in Volt oder None, wenn sie außerhalb von ]0, 500] liegt."""
	if roh == UNGUELTIG:
		return None
	wert = round(roh / 10, 1)
	if not 0 < wert <= 500:
		return None
	return wert


def frequenz(roh):
	"""Liefert eine Registerfrequenz (0,01 Hz) in Hertz oder None, wenn sie außerhalb von [45, 55] liegt."""
	wert = round(roh / 100, 2)
	if not 45 <= wert <= 55:
		if roh not in (0, UNGUELTIG):
			log(f"Frequenz {wert} Hz liegt außerhalb des gültigen Bereichs und wird nicht übertragen.")
		return None
	return wert


def modell_lesen(verbindung):
	"""Liefert die Modellbezeichnung des Wechselrichters, z. B. "GW10KN-ET", oder None."""
	try:
		register = verbindung.lesen(REG_MODELL, 5)
	except MesswertFehler as fehler:
		log(f"Modellbezeichnung nicht lesbar: {fehler}")
		return None
	text = b"".join(struct.pack(">H", wert) for wert in register).decode("ascii", errors="ignore")
	text = text.replace("\x00", "").strip()
	return text if text.isprintable() and text else None


def phasen_pruefen(l1, l2, l3, register_text):
	if l1 is None:
		raise MesswertFehler(f"L1: keine gültige Spannung ({register_text}).")
	# Einphasige Zähler liefern L2/L3 nicht oder mit 0 V, die API erwartet dann -1
	if l2 is None and l3 is None:
		return l1, -1, -1
	if l2 is None or l3 is None:
		raise MesswertFehler(f"L2/L3: nur eine Phase liefert eine gültige Spannung ({register_text}).")
	return l1, l2, l3


def meter_werte(verbindung):
	"""Liefert die Messwerte des Smart Meters am Netzanschlusspunkt als dict mit API-Feldnamen."""
	meter = verbindung.lesen(REG_METER, METER_ANZAHL)

	if meter[METER_KOMMUNIKATION] != 1:
		raise MesswertFehler(
			f"Der Smart Meter kommuniziert nicht mit dem Wechselrichter (Register 36004 = {meter[METER_KOMMUNIKATION]})."
		)

	roh = meter[METER_SPANNUNG:METER_SPANNUNG + 3]
	if all(wert in (0, UNGUELTIG) for wert in roh):
		raise MesswertFehler(
			"Der Wechselrichter liefert keine Zählerspannungen (Register 36052 bis 36054). "
			"Firmware aktualisieren oder GOODWE_QUELLE=wechselrichter setzen."
		)
	l1, l2, l3 = phasen_pruefen(*(spannung(wert) for wert in roh), f"Register 36052 bis 36054 = {roh}")
	werte = {"l1_v": l1, "l2_v": l2, "l3_v": l3}

	netzfrequenz = frequenz(meter[METER_FREQUENZ])
	if netzfrequenz is not None:
		werte["grid_frequency_hz"] = netzfrequenz

	# GoodWe zählt Einspeisung positiv, die API erwartet Bezug positiv
	wirkleistung = -int32(meter[METER_WIRKLEISTUNG], meter[METER_WIRKLEISTUNG + 1])
	werte["grid_power_w"] = float(wirkleistung)

	scheinleistung = abs(int32(meter[METER_SCHEINLEISTUNG], meter[METER_SCHEINLEISTUNG + 1]))
	if scheinleistung > 0:
		werte["apparent_power_va"] = float(scheinleistung)
		werte["power_factor"] = min(round(abs(wirkleistung) / scheinleistung, 3), 1.0)

	for phase, (feld, roh_strom) in enumerate(zip(("l1_a", "l2_a", "l3_a"), meter[METER_STROM:METER_STROM + 3])):
		if werte[f"l{phase + 1}_v"] == -1 or roh_strom == UNGUELTIG:
			werte[feld] = -1
		else:
			werte[feld] = round(abs(int16(roh_strom)) / 10, 1)

	return werte


def wechselrichter_werte(verbindung):
	"""Liefert die Spannungen und die Frequenz an den AC-Klemmen des Wechselrichters."""
	register = verbindung.lesen(REG_WR_PHASEN, 15)
	roh = register[0::5]
	l1, l2, l3 = phasen_pruefen(*(spannung(wert) for wert in roh), f"Register 35121, 35126, 35131 = {roh}")
	werte = {"l1_v": l1, "l2_v": l2, "l3_v": l3}

	netzfrequenz = frequenz(register[2])
	if netzfrequenz is not None:
		werte["grid_frequency_hz"] = netzfrequenz
	return werte


def batterie_soc(verbindung):
	"""Liefert den Ladezustand der Batterie in Prozent oder None, wenn keine Batterie erkannt wird."""
	try:
		batteriespannung = verbindung.lesen(REG_BATTERIE_SPANNUNG, 1)[0]
		soc = verbindung.lesen(REG_BATTERIE_SOC, 1)[0]
	except MesswertFehler as fehler:
		log(f"Batteriedaten nicht lesbar: {fehler}")
		return None
	if batteriespannung in (0, UNGUELTIG) or not 0 <= soc <= 100:
		return None
	return float(soc)


def einstellung(name, standard, umwandeln=str):
	"""Liefert die Environment-Variable name umgewandelt oder standard, wenn sie fehlt oder leer ist."""
	wert = os.environ.get(name, "").strip()
	if not wert:
		return standard
	try:
		return umwandeln(wert)
	except ValueError:
		raise SystemExit(f"FEHLER: Environment-Variable {name}={wert!r} ist ungültig.")


def konfiguration_laden():
	global GOODWE_HOST, GOODWE_PORT, GOODWE_UNIT_ID, GOODWE_QUELLE, LATITUDE, LONGITUDE
	global PLANT_CAPACITY_KWP, BATTERY_CAPACITY_KWH, SMARTMETER_MODEL
	GOODWE_HOST = einstellung("GOODWE_HOST", GOODWE_HOST)
	GOODWE_PORT = einstellung("GOODWE_PORT", GOODWE_PORT, int)
	GOODWE_UNIT_ID = einstellung("GOODWE_UNIT_ID", GOODWE_UNIT_ID, int)
	GOODWE_QUELLE = einstellung("GOODWE_QUELLE", GOODWE_QUELLE).lower()
	LATITUDE = einstellung("LATITUDE", LATITUDE, float)
	LONGITUDE = einstellung("LONGITUDE", LONGITUDE, float)
	PLANT_CAPACITY_KWP = einstellung("PLANT_CAPACITY_KWP", PLANT_CAPACITY_KWP, float)
	BATTERY_CAPACITY_KWH = einstellung("BATTERY_CAPACITY_KWH", BATTERY_CAPACITY_KWH, float)
	SMARTMETER_MODEL = einstellung("SMARTMETER_MODEL", SMARTMETER_MODEL)


def konfiguration_pruefen():
	if not GOODWE_HOST:
		raise SystemExit("FEHLER: GOODWE_HOST ist nicht gesetzt.")
	if not isinstance(GOODWE_PORT, int) or not 0 < GOODWE_PORT <= 65535:
		raise SystemExit("FEHLER: GOODWE_PORT muss eine Portnummer zwischen 1 und 65535 sein.")
	if not isinstance(GOODWE_UNIT_ID, int) or not 0 <= GOODWE_UNIT_ID <= 255:
		raise SystemExit("FEHLER: GOODWE_UNIT_ID muss zwischen 0 und 255 liegen.")
	if GOODWE_QUELLE not in ("meter", "wechselrichter"):
		raise SystemExit("FEHLER: GOODWE_QUELLE muss \"meter\" oder \"wechselrichter\" sein.")
	if zahl(LATITUDE) is None or zahl(LONGITUDE) is None:
		raise SystemExit("FEHLER: LATITUDE und LONGITUDE müssen als Zahl gesetzt sein.")
	if not -90 <= LATITUDE <= 90 or not -180 <= LONGITUDE <= 180:
		raise SystemExit("FEHLER: LATITUDE muss zwischen -90 und 90, LONGITUDE zwischen -180 und 180 liegen.")
	if PLANT_CAPACITY_KWP is not None and (zahl(PLANT_CAPACITY_KWP) is None or not 0 < PLANT_CAPACITY_KWP <= 1000):
		raise SystemExit("FEHLER: PLANT_CAPACITY_KWP muss größer 0 und maximal 1000 sein.")
	if BATTERY_CAPACITY_KWH is not None and (zahl(BATTERY_CAPACITY_KWH) is None or not BATTERY_CAPACITY_KWH > 0):
		raise SystemExit("FEHLER: BATTERY_CAPACITY_KWH muss größer 0 sein.")


def payload_erstellen():
	# Zeitstempel vor dem Abruf nehmen, der Wechselrichter liefert keine UTC-Zeit
	observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

	with verbinden() as verbindung:
		modell = modell_lesen(verbindung)
		if GOODWE_QUELLE == "meter":
			werte = meter_werte(verbindung)
		else:
			werte = wechselrichter_werte(verbindung)
		soc = batterie_soc(verbindung)

	payload = {
		"observed_at": observed_at,
		"latitude": LATITUDE,
		"longitude": LONGITUDE,
		"l1_v": werte.pop("l1_v"),
		"l2_v": werte.pop("l2_v"),
		"l3_v": werte.pop("l3_v"),
		"integration_version": INTEGRATION_VERSION,
	}
	payload.update(werte)

	if soc is not None:
		payload["battery_soc_percent"] = soc
	if PLANT_CAPACITY_KWP is not None:
		payload["plant_capacity_kwp"] = PLANT_CAPACITY_KWP
	if BATTERY_CAPACITY_KWH is not None:
		payload["battery_capacity"] = BATTERY_CAPACITY_KWH

	# Nur Modellbezeichnungen übertragen, niemals die Seriennummer aus den Registern 35003 bis 35010
	if SMARTMETER_MODEL:
		payload["smartmeter_model"] = SMARTMETER_MODEL.strip()[:120]
	elif GOODWE_QUELLE == "meter":
		payload["smartmeter_model"] = "GoodWe Smart Meter"
	elif modell:
		payload["smartmeter_model"] = f"GoodWe {modell}"[:120]

	return payload


def senden(payload):
	anfrage = urllib.request.Request(
		API_URL,
		data=json.dumps(payload).encode("utf-8"),
		headers={"Content-Type": "application/json"},
		method="POST",
	)
	try:
		with urllib.request.urlopen(anfrage, timeout=20) as antwort:
			status_code = antwort.status
			text = antwort.read().decode("utf-8", errors="replace")
	except urllib.error.HTTPError as fehler:
		status_code = fehler.code
		text = fehler.read().decode("utf-8", errors="replace")
	except (urllib.error.URLError, OSError, http.client.HTTPException) as fehler:
		raise SystemExit(f"FEHLER: Verbindung zur API fehlgeschlagen: {fehler}")

	if status_code == 202:
		werte = f"L1={payload['l1_v']} L2={payload['l2_v']} L3={payload['l3_v']}"
		if "grid_frequency_hz" in payload:
			werte += f" f={payload['grid_frequency_hz']}"
		if "grid_power_w" in payload:
			werte += f" P={payload['grid_power_w']}"
		log(f"Übertragen ({payload['observed_at']}): {werte} | HTTP 202: {text}")
	elif status_code == 403:
		raise SystemExit(f"FEHLER: 403 – der Standort ist für die Annahme gesperrt: {text}")
	elif status_code == 422:
		raise SystemExit(f"FEHLER: 422 – Payload abgelehnt: {text}")
	else:
		raise SystemExit(f"FEHLER: HTTP {status_code}: {text}")


def main():
	argumente = sys.argv[1:]
	if any(argument != "--dry-run" for argument in argumente):
		raise SystemExit(f"Aufruf: {sys.argv[0]} [--dry-run]")

	konfiguration_laden()
	konfiguration_pruefen()
	try:
		payload = payload_erstellen()
	except MesswertFehler as fehler:
		raise SystemExit(f"FEHLER: {fehler}")

	if "--dry-run" in argumente:
		print(json.dumps(payload, indent="\t", ensure_ascii=False))
		return

	senden(payload)


if __name__ == "__main__":
	main()
