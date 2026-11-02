#!/usr/bin/env python3
"""
ortsnetz_loxone.py

Liest Netzspannungen (und optional Frequenz, Ströme, Leistungsfaktor, Netzleistung,
Speicher-SOC und die heutige PV-Prognose) aus einem Loxone Miniserver über dessen Webservice
(GET /jdev/sps/io/<Name>) und sendet sie an https://www.ortsnetz-auslastung.de

Welche Bausteine gelesen werden, steht in der Konfiguration (Bezeichnung des Bausteins in
Loxone Config, z. B. "L1 voltage" eines Virtuellen Eingangs). Der Loxone-Benutzer braucht
Leserechte auf genau diese Bausteine, sonst antwortet der Miniserver mit 403.

Nur Python-Standardbibliothek, ab Python 3.8.

Aufruf:
	ortsnetz_loxone.py            -> Dauerbetrieb: alle ABTAST_S Sekunden lesen, alle INTERVALL_S
	                                 Sekunden eine Messung mit Minimum, Maximum und Mittelwert senden
	ortsnetz_loxone.py --once     -> einmal lesen und senden (z. B. per cron alle 5 Minuten)
	ortsnetz_loxone.py --dry-run  -> einmal lesen und die Payload nur ausgeben

Dauerbetrieb als systemd-Dienst, siehe README.md und Ordner systemd/.
Die Konfiguration erfolgt im Konfigurationsblock oder per Environment-Variablen, siehe README.md.
"""

import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# ============================ Konfiguration ============================

# Alle Werte können auch als gleichnamige Environment-Variablen gesetzt werden,
# diese haben Vorrang vor den Werten hier

# Adresse des Miniservers im Heimnetz (optional mit Port, z. B. "192.168.1.77:8080"), muss gesetzt werden
LOXONE_HOST = ""
LOXONE_USER = ""
LOXONE_PASSWORD = ""

# Ungefährer Standort in Dezimalgrad, muss gesetzt werden
LATITUDE = None		# z. B. 52.52
LONGITUDE = None	# z. B. 13.40

# Optional: installierte PV-Leistung in kWp, größer 0 und maximal 1000 (None = wird nicht übertragen);
# muss gesetzt sein, wenn NAME_PV_PROGNOSE gesetzt ist
PLANT_CAPACITY_KWP = None
# Optional: nutzbare Kapazität des Batteriespeichers in kWh, größer 0 (None = wird nicht übertragen)
BATTERY_CAPACITY_KWH = None

# Bezeichnungen der Bausteine in Loxone Config. L1 muss gesetzt werden; L2 und L3 leer = einphasig (-1)
NAME_L1 = ""		# Spannung L1 in V, z. B. "L1 voltage"
NAME_L2 = ""
NAME_L3 = ""
# Optional, leer = wird nicht übertragen
NAME_FREQUENZ = ""		# Netzfrequenz in Hz
NAME_STROM_L1 = ""		# Strom L1 in A
NAME_STROM_L2 = ""
NAME_STROM_L3 = ""
NAME_LEISTUNGSFAKTOR = ""	# Leistungsfaktor (Betrag wird übertragen)
NAME_NETZLEISTUNG = ""		# Netzleistung am Hausanschluss (alle Phasen)
NAME_SOC = ""			# Ladezustand des Speichers in %
NAME_PV_PROGNOSE = ""		# heutige PV-Gesamtprognose in kWh (braucht PLANT_CAPACITY_KWP)

# Umrechnung der Netzleistung auf W mit Bezug positiv / Einspeisung negativ:
# 1 = Wert ist bereits W mit Bezug positiv, 1000 = kW mit Bezug positiv,
# -1000 = kW mit Einspeisung positiv
NETZLEISTUNG_FAKTOR = 1.0

# Abtastung im Dauerbetrieb und Sendeintervall in Sekunden (die API erwartet 300)
ABTAST_S = 10.0
INTERVALL_S = 300

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "loxone-0.1.0"
SMARTMETER_MODEL = "Loxone Miniserver"

# =======================================================================

# Spannungen außerhalb dieses Bereichs gelten als nicht plausibel
SPANNUNG_MIN = 150
SPANNUNG_MAX = 300

ZAHL = re.compile(r"^\s*([-+]?\d+(?:[.,]\d+)?)")


class MesswertFehler(Exception):
	pass


class SendeFehler(Exception):
	pass


def log(text):
	zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	print(f"{zeit} {text}", flush=True)


def zahl(wert):
	"""Liefert wert als float oder None, wenn es keine Zahl ist."""
	if isinstance(wert, bool) or not isinstance(wert, (int, float)):
		return None
	return float(wert)


def wert_aus_text(text):
	"""Die Zahl am Anfang eines Loxone-Werts ('237.68 V', '55.1 %', '0.647') oder None."""
	treffer = ZAHL.match(str(text or ""))
	if not treffer:
		return None
	return float(treffer.group(1).replace(",", "."))


def loxone_lesen(name):
	"""Liest den Wert des Bausteins name vom Miniserver, als Zahl."""
	url = f"http://{LOXONE_HOST}/jdev/sps/io/{urllib.parse.quote(name, safe='')}"
	anfrage = urllib.request.Request(url)
	if LOXONE_USER:
		zugang = base64.b64encode(f"{LOXONE_USER}:{LOXONE_PASSWORD}".encode("utf-8")).decode("ascii")
		anfrage.add_header("Authorization", f"Basic {zugang}")
	try:
		with urllib.request.urlopen(anfrage, timeout=10) as antwort:
			daten = json.load(antwort)
	except urllib.error.HTTPError as fehler:
		fehler.close()
		raise MesswertFehler(f"'{name}': HTTP {fehler.code} vom Miniserver.")
	except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as fehler:
		raise MesswertFehler(f"'{name}': Abruf fehlgeschlagen: {fehler}")
	try:
		code = str(daten["LL"]["Code"])
		text = daten["LL"].get("value")
	except (KeyError, TypeError, AttributeError):
		raise MesswertFehler(f"'{name}': Antwort des Miniservers hat ein unerwartetes Format.")
	if code == "403":
		raise MesswertFehler(f"'{name}': 403 - der Loxone-Benutzer hat keine Rechte auf diesen Baustein.")
	if code == "404":
		raise MesswertFehler(f"'{name}': 404 - kein Baustein mit dieser Bezeichnung.")
	if code != "200":
		raise MesswertFehler(f"'{name}': Code {code} vom Miniserver.")
	wert = wert_aus_text(text)
	if wert is None:
		raise MesswertFehler(f"'{name}': kein Zahlenwert ({text!r}).")
	return wert


def spannung_lesen(name):
	wert = round(loxone_lesen(name), 2)
	if not SPANNUNG_MIN <= wert <= SPANNUNG_MAX:
		raise MesswertFehler(f"'{name}': {wert} V liegt nicht zwischen {SPANNUNG_MIN} und {SPANNUNG_MAX} V.")
	return wert


def optionale_werte():
	"""(Payload-Feld, Bausteinname, Umrechnung, Prüfung) der gesetzten optionalen Werte."""
	alle = (
		("grid_frequency_hz", NAME_FREQUENZ, lambda w: round(w, 3), lambda w: 45 <= w <= 55),
		("l1_a", NAME_STROM_L1, lambda w: round(abs(w), 2), lambda w: True),
		("l2_a", NAME_STROM_L2, lambda w: round(abs(w), 2), lambda w: True),
		("l3_a", NAME_STROM_L3, lambda w: round(abs(w), 2), lambda w: True),
		("power_factor", NAME_LEISTUNGSFAKTOR, lambda w: round(abs(w), 3), lambda w: 0 <= w <= 1),
		("grid_power_w", NAME_NETZLEISTUNG, lambda w: round(w * NETZLEISTUNG_FAKTOR), lambda w: True),
		("battery_soc_percent", NAME_SOC, lambda w: round(w, 1), lambda w: 0 <= w <= 100),
		# mehr als 10 kWh je kWp und Tag lehnt die API mit 422 für die ganze Messung ab
		("pv_forecast_kwh", NAME_PV_PROGNOSE, lambda w: round(w, 1),
			lambda w: 0 <= w <= min(100000, 10 * (PLANT_CAPACITY_KWP or 0))),
	)
	return [eintrag for eintrag in alle if eintrag[1]]


def probe_nehmen():
	"""Liest alle gesetzten Bausteine einmal. Die Spannungen müssen gelesen werden können,
	ein fehlender optionaler Wert fehlt nur in dieser Probe."""
	probe = {"zeit": datetime.now(timezone.utc)}
	for feld, name in (("l1_v", NAME_L1), ("l2_v", NAME_L2), ("l3_v", NAME_L3)):
		probe[feld] = spannung_lesen(name) if name else -1
	for feld, name, umrechnen, pruefen in optionale_werte():
		try:
			wert = umrechnen(loxone_lesen(name))
		except MesswertFehler as fehler:
			log(f"WARNUNG: {fehler}")
			continue
		if pruefen(wert):
			probe[feld] = wert
		else:
			log(f"WARNUNG: '{name}': {wert} ist nicht plausibel und wird nicht übertragen.")
	return probe


def payload_erstellen(proben, kennzahlen=False):
	"""Payload aus den Proben eines Intervalls: die letzte Probe als Messung, mit kennzahlen
	zusätzlich Minimum, Maximum und Mittelwert der Spannungen und der Frequenz."""
	if not proben:
		raise MesswertFehler("keine gültige Probe im Intervall.")
	letzte = proben[-1]
	payload = {
		"observed_at": letzte["zeit"].strftime("%Y-%m-%dT%H:%M:%SZ"),
		"latitude": LATITUDE,
		"longitude": LONGITUDE,
		"l1_v": letzte["l1_v"],
		"l2_v": letzte["l2_v"],
		"l3_v": letzte["l3_v"],
	}
	for feld, _name, _umrechnen, _pruefen in optionale_werte():
		if feld in letzte:
			payload[feld] = letzte[feld]
	if kennzahlen:
		for feld in ("l1_v", "l2_v", "l3_v", "grid_frequency_hz"):
			werte = [probe[feld] for probe in proben if feld in probe and probe[feld] != -1]
			if not werte:
				continue
			payload[f"{feld}_min"] = min(werte)
			payload[f"{feld}_max"] = max(werte)
			payload[f"{feld}_avg"] = round(sum(werte) / len(werte), 3)
	if PLANT_CAPACITY_KWP is not None:
		payload["plant_capacity_kwp"] = PLANT_CAPACITY_KWP
	if BATTERY_CAPACITY_KWH is not None:
		payload["battery_capacity"] = BATTERY_CAPACITY_KWH
	payload["smartmeter_model"] = SMARTMETER_MODEL
	payload["integration_version"] = INTEGRATION_VERSION
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
		fehler.close()
	except (urllib.error.URLError, OSError, http.client.HTTPException) as fehler:
		raise SendeFehler(f"Verbindung zur API fehlgeschlagen: {fehler}")

	if status_code == 202:
		werte = f"L1={payload['l1_v']} L2={payload['l2_v']} L3={payload['l3_v']}"
		log(f"Übertragen ({payload['observed_at']}): {werte} | HTTP 202: {text}")
	elif status_code == 403:
		raise SendeFehler(f"403 - der Standort ist für die Annahme gesperrt: {text}")
	elif status_code == 422:
		raise SendeFehler(f"422 - Payload abgelehnt: {text}")
	else:
		raise SendeFehler(f"HTTP {status_code}: {text}")


def naechste_grenze(jetzt):
	"""Das nächste Vielfache von INTERVALL_S nach jetzt (Unix-Zeit), z. B. :00, :05, :10."""
	return (int(jetzt) // INTERVALL_S + 1) * INTERVALL_S


def dauerbetrieb(uhr=time.time, schlafen=time.sleep, runden=None):
	"""Liest alle ABTAST_S Sekunden und sendet an jeder Intervallgrenze die Messung des
	abgelaufenen Intervalls. runden begrenzt die Zahl der Intervalle (für Tests)."""
	log(f"Dauerbetrieb: alle {ABTAST_S:g} s lesen, alle {INTERVALL_S} s senden ({LOXONE_HOST}).")
	proben = []
	grenze = naechste_grenze(uhr())
	gesendet = 0
	while runden is None or gesendet < runden:
		beginn = uhr()
		try:
			proben.append(probe_nehmen())
		except MesswertFehler as fehler:
			log(f"WARNUNG: Probe verworfen: {fehler}")
		if uhr() >= grenze:
			try:
				senden(payload_erstellen(proben, kennzahlen=True))
			except (MesswertFehler, SendeFehler) as fehler:
				log(f"FEHLER: {fehler}")
			proben = []
			grenze = naechste_grenze(uhr())
			gesendet += 1
		schlafen(max(0.5, ABTAST_S - (uhr() - beginn)))


def einstellung(name, standard, umwandeln=str):
	"""Liefert die Environment-Variable name umgewandelt oder standard, wenn sie fehlt oder leer ist."""
	wert = os.environ.get(name, "").strip()
	if not wert:
		return standard
	try:
		return umwandeln(wert)
	except ValueError:
		raise SystemExit(f"FEHLER: Environment-Variable {name}={wert!r} ist ungültig.")


TEXTE = ("LOXONE_HOST", "LOXONE_USER", "NAME_L1", "NAME_L2", "NAME_L3", "NAME_FREQUENZ",
	"NAME_STROM_L1", "NAME_STROM_L2", "NAME_STROM_L3", "NAME_LEISTUNGSFAKTOR", "NAME_NETZLEISTUNG",
	"NAME_SOC", "NAME_PV_PROGNOSE", "SMARTMETER_MODEL")
ZAHLEN = ("LATITUDE", "LONGITUDE", "PLANT_CAPACITY_KWP", "BATTERY_CAPACITY_KWH", "NETZLEISTUNG_FAKTOR", "ABTAST_S")


def konfiguration_laden():
	modul = globals()
	for name in TEXTE:
		modul[name] = einstellung(name, modul[name])
	for name in ZAHLEN:
		modul[name] = einstellung(name, modul[name], float)
	modul["INTERVALL_S"] = einstellung("INTERVALL_S", INTERVALL_S, int)
	# das Passwort wird nie ausgegeben; ein leeres LOXONE_PASSWORD lässt den Wert hier stehen
	modul["LOXONE_PASSWORD"] = os.environ.get("LOXONE_PASSWORD", LOXONE_PASSWORD)


def konfiguration_pruefen():
	if not LOXONE_HOST:
		raise SystemExit("FEHLER: LOXONE_HOST ist nicht gesetzt.")
	if not NAME_L1:
		raise SystemExit("FEHLER: NAME_L1 (Baustein der Spannung L1) ist nicht gesetzt.")
	if bool(NAME_L2) != bool(NAME_L3):
		raise SystemExit("FEHLER: NAME_L2 und NAME_L3 nur zusammen setzen (oder beide leer für einphasig).")
	if zahl(LATITUDE) is None or zahl(LONGITUDE) is None:
		raise SystemExit("FEHLER: LATITUDE und LONGITUDE müssen als Zahl gesetzt sein.")
	if not -90 <= LATITUDE <= 90 or not -180 <= LONGITUDE <= 180:
		raise SystemExit("FEHLER: LATITUDE muss zwischen -90 und 90, LONGITUDE zwischen -180 und 180 liegen.")
	if PLANT_CAPACITY_KWP is not None and (zahl(PLANT_CAPACITY_KWP) is None or not 0 < PLANT_CAPACITY_KWP <= 1000):
		raise SystemExit("FEHLER: PLANT_CAPACITY_KWP muss größer 0 und maximal 1000 sein.")
	if NAME_PV_PROGNOSE and PLANT_CAPACITY_KWP is None:
		raise SystemExit("FEHLER: NAME_PV_PROGNOSE braucht PLANT_CAPACITY_KWP (sonst lehnt die API die Messung mit 422 ab).")
	if BATTERY_CAPACITY_KWH is not None and (zahl(BATTERY_CAPACITY_KWH) is None or not BATTERY_CAPACITY_KWH > 0):
		raise SystemExit("FEHLER: BATTERY_CAPACITY_KWH muss größer 0 sein.")
	if not 1 <= ABTAST_S <= INTERVALL_S:
		raise SystemExit("FEHLER: ABTAST_S muss zwischen 1 und INTERVALL_S liegen.")


def main():
	argumente = sys.argv[1:]
	if len(argumente) > 1 or any(argument not in ("--once", "--dry-run") for argument in argumente):
		raise SystemExit(f"Aufruf: {sys.argv[0]} [--once | --dry-run]")

	konfiguration_laden()
	konfiguration_pruefen()
	if not argumente:
		dauerbetrieb()
		return
	try:
		payload = payload_erstellen([probe_nehmen()])
	except MesswertFehler as fehler:
		raise SystemExit(f"FEHLER: {fehler}")
	if "--dry-run" in argumente:
		print(json.dumps(payload, indent="\t", ensure_ascii=False))
		return
	try:
		senden(payload)
	except SendeFehler as fehler:
		raise SystemExit(f"FEHLER: {fehler}")


if __name__ == "__main__":
	main()
