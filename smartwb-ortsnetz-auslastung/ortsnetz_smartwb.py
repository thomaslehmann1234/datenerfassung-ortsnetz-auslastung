#!/usr/bin/env python3
"""
ortsnetz_smartwb.py

Liest die Phasenspannungen einer smartWB / EVSE-WiFi 2.0 Wallbox über deren lokale
HTTP-API (GET /getParameters) und sendet sie an https://www.ortsnetz-auslastung.de

Nur Python-Standardbibliothek, ab Python 3.8.
Jeder Aufruf führt genau eine Messung und Übertragung aus.

Aufruf:
	ortsnetz_smartwb.py            -> abrufen und senden
	ortsnetz_smartwb.py --dry-run  -> abrufen und Payload nur ausgeben

Crontab (alle 5 Minuten):
	*/5 * * * * SMARTWB_HOST=192.168.1.50 LATITUDE=52.52 LONGITUDE=13.40 /usr/bin/python3 /opt/ortsnetz-smartwb/ortsnetz_smartwb.py >> $HOME/ortsnetz-smartwb.log 2>&1

Alternativ als systemd-Timer, siehe README.md und Ordner systemd/.

Die Konfiguration kann statt im Konfigurationsblock auch per Environment-Variablen
erfolgen, siehe README.md.
"""

import http.client
import json
import os
import signal
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ============================ Konfiguration ============================

# SMARTWB_HOST, LATITUDE, LONGITUDE und PLANT_CAPACITY_KWP können auch als gleichnamige
# Environment-Variablen gesetzt werden, diese haben Vorrang vor den Werten hier

# IP-Adresse oder Hostname der Wallbox im Heimnetz (optional mit Port, z. B. "192.168.1.50:8080"),
# muss gesetzt werden. 192.168.4.1 ist nur die Adresse im Access-Point-Modus der Wallbox.
SMARTWB_HOST = ""

# Ungefährer Standort in Dezimalgrad, muss gesetzt werden
LATITUDE = None		# z. B. 52.52
LONGITUDE = None	# z. B. 13.40

# Optional: installierte PV-Leistung in kWp, größer 0 und maximal 1000 (None = wird nicht übertragen)
PLANT_CAPACITY_KWP = None	# z. B. 9.8

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "smartwb-0.1.0"
SMARTMETER_MODEL = "smartWB"

# Maximale Gesamtlaufzeit eines Aufrufs in Sekunden. Die HTTP-Timeouts begrenzen nur einzelne
# Netzwerkoperationen, langsam weiter eintreffende Daten würden den Prozess sonst beliebig lange offenhalten.
MAX_LAUFZEIT_S = 60

# =======================================================================

# Spannungen außerhalb dieses Bereichs gelten als nicht plausibel
SPANNUNG_MIN = 150
SPANNUNG_MAX = 300


class MesswertFehler(Exception):
	pass


def laufzeit_begrenzen():
	"""Beendet den Prozess mit Fehler, wenn er länger als MAX_LAUFZEIT_S läuft (nur Linux/Unix)."""
	if not hasattr(signal, "SIGALRM"):
		return

	def abbruch(signalnummer, frame):
		raise SystemExit(f"FEHLER: Maximale Laufzeit von {MAX_LAUFZEIT_S} s überschritten.")

	signal.signal(signal.SIGALRM, abbruch)
	signal.alarm(MAX_LAUFZEIT_S)


def log(text):
	zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	print(f"{zeit} {text}", flush=True)


def json_holen(url):
	try:
		with urllib.request.urlopen(url, timeout=10) as antwort:
			return json.load(antwort)
	except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as fehler:
		raise MesswertFehler(f"Abruf von {url} fehlgeschlagen: {fehler}")


def zahl(wert):
	"""Liefert wert als float oder None, wenn es keine Zahl ist."""
	if isinstance(wert, bool) or not isinstance(wert, (int, float)):
		return None
	return float(wert)


def parameter_holen():
	"""Liefert das Parameter-Dict aus der Antwort von /getParameters."""
	antwort = json_holen(f"http://{SMARTWB_HOST}/getParameters")
	try:
		daten = antwort["list"][0]
	except (KeyError, IndexError, TypeError):
		raise MesswertFehler("Antwort der Wallbox hat ein unerwartetes Format.")
	if not isinstance(daten, dict):
		raise MesswertFehler("Antwort der Wallbox hat ein unerwartetes Format.")
	return daten


def spannung(daten, phase):
	"""Liefert die Spannung der Phase in Volt oder None, wenn sie fehlt oder nicht plausibel ist."""
	wert = zahl(daten.get(f"voltageP{phase}"))
	if wert is None:
		return None
	wert = round(wert, 2)
	if not SPANNUNG_MIN <= wert <= SPANNUNG_MAX:
		return None
	return wert


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
	global SMARTWB_HOST, LATITUDE, LONGITUDE, PLANT_CAPACITY_KWP
	SMARTWB_HOST = einstellung("SMARTWB_HOST", SMARTWB_HOST)
	LATITUDE = einstellung("LATITUDE", LATITUDE, float)
	LONGITUDE = einstellung("LONGITUDE", LONGITUDE, float)
	PLANT_CAPACITY_KWP = einstellung("PLANT_CAPACITY_KWP", PLANT_CAPACITY_KWP, float)


def konfiguration_pruefen():
	if not SMARTWB_HOST:
		raise SystemExit("FEHLER: SMARTWB_HOST ist nicht gesetzt.")
	if zahl(LATITUDE) is None or zahl(LONGITUDE) is None:
		raise SystemExit("FEHLER: LATITUDE und LONGITUDE müssen als Zahl gesetzt sein.")
	if not -90 <= LATITUDE <= 90 or not -180 <= LONGITUDE <= 180:
		raise SystemExit("FEHLER: LATITUDE muss zwischen -90 und 90, LONGITUDE zwischen -180 und 180 liegen.")
	if PLANT_CAPACITY_KWP is not None and (zahl(PLANT_CAPACITY_KWP) is None or not 0 < PLANT_CAPACITY_KWP <= 1000):
		raise SystemExit("FEHLER: PLANT_CAPACITY_KWP muss größer 0 und maximal 1000 sein.")


def payload_erstellen():
	daten = parameter_holen()

	l1 = spannung(daten, 1)
	if l1 is None:
		raise MesswertFehler(
			f"L1: keine plausible Spannung (voltageP1 = {daten.get('voltageP1')}, erwartet {SPANNUNG_MIN} bis {SPANNUNG_MAX} V)."
		)

	# Einphasige Wallboxen liefern L2/L3 nicht oder mit 0 V, die API erwartet dann -1
	l2 = spannung(daten, 2)
	l3 = spannung(daten, 3)
	if l2 is None and l3 is None:
		l2 = l3 = -1
	elif l2 is None or l3 is None:
		raise MesswertFehler(
			f"L2/L3: nur eine Phase liefert eine plausible Spannung (voltageP2 = {daten.get('voltageP2')}, "
			f"voltageP3 = {daten.get('voltageP3')})."
		)

	# Die Wallbox liefert keinen Zeitstempel, daher die Systemzeit
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

	if PLANT_CAPACITY_KWP is not None:
		payload["plant_capacity_kwp"] = PLANT_CAPACITY_KWP

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

	laufzeit_begrenzen()
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
