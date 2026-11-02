import importlib.util
import pathlib
import socket
import struct
import threading
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).with_name("ortsnetz_goodwe.py")
SPEC = importlib.util.spec_from_file_location("ortsnetz_goodwe", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def u16(wert):
	return wert & 0xFFFF


def u32(wert):
	wert &= 0xFFFFFFFF
	return [wert >> 16, wert & 0xFFFF]


def beispiel_register():
	"""Registerabbild eines GW10KN-ET mit dreiphasigem Smart Meter, aufgenommen an einer realen Anlage."""
	register = {}
	for i, wert in enumerate([18263, 12592, 19278, 11589, 21536]):	# "GW10KN-ET "
		register[35011 + i] = wert
	for i, wert in enumerate([2304, 41, 4989, 0, 934, 2297, 41, 4990, 0, 916, 2316, 41, 4996, 0, 925]):
		register[35121 + i] = wert
	register[35180] = 3170
	register[37007] = 83
	meter = [0] * 58
	meter[4] = 1
	meter[14] = 4994
	meter[25:27] = u32(-6)
	meter[41:43] = u32(-3115)
	meter[52:55] = [2305, 2292, 2316]
	meter[55:58] = [29, 67, 39]
	for i, wert in enumerate(meter):
		register[36000 + i] = wert
	return register


class FalscheVerbindung:
	def __init__(self, register):
		self.register = register

	def __enter__(self):
		return self

	def __exit__(self, *_):
		pass

	def lesen(self, start, anzahl):
		if any(start + i not in self.register for i in range(anzahl)):
			raise MODULE.MesswertFehler(f"Modbus-Fehler 2 beim Lesen der Register ab {start}.")
		return [self.register[start + i] for i in range(anzahl)]


class PayloadTests(unittest.TestCase):
	def setUp(self):
		for name, wert in (("GOODWE_HOST", "192.168.1.50"), ("LATITUDE", 52.52), ("LONGITUDE", 13.4)):
			patcher = patch.object(MODULE, name, wert)
			patcher.start()
			self.addCleanup(patcher.stop)

	def payload(self, register, **einstellungen):
		with patch.multiple(MODULE, verbinden=lambda: FalscheVerbindung(register), **einstellungen):
			return MODULE.payload_erstellen()

	def test_meter_dreiphasig(self):
		payload = self.payload(beispiel_register())
		self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (230.5, 229.2, 231.6))
		self.assertEqual(payload["grid_frequency_hz"], 49.94)
		self.assertEqual(payload["grid_power_w"], 6.0)
		self.assertEqual(payload["apparent_power_va"], 3115.0)
		self.assertEqual(payload["power_factor"], 0.002)
		self.assertEqual((payload["l1_a"], payload["l2_a"], payload["l3_a"]), (2.9, 6.7, 3.9))
		self.assertEqual(payload["battery_soc_percent"], 83.0)
		self.assertEqual(payload["smartmeter_model"], "GoodWe Smart Meter")
		self.assertEqual(payload["integration_version"], "goodwe-0.1.0")
		self.assertNotIn("plant_capacity_kwp", payload)
		self.assertNotIn("battery_capacity", payload)
		self.assertRegex(payload["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

	def test_einspeisung_wird_negativ(self):
		register = beispiel_register()
		register[36025], register[36026] = u32(3515)
		self.assertEqual(self.payload(register)["grid_power_w"], -3515.0)

	def test_bezug_wird_positiv(self):
		register = beispiel_register()
		register[36025], register[36026] = u32(-1200)
		self.assertEqual(self.payload(register)["grid_power_w"], 1200.0)

	def test_ohne_scheinleistung_kein_leistungsfaktor(self):
		register = beispiel_register()
		register[36041], register[36042] = 0, 0
		payload = self.payload(register)
		self.assertNotIn("apparent_power_va", payload)
		self.assertNotIn("power_factor", payload)

	def test_einphasig(self):
		register = beispiel_register()
		register[36053], register[36054] = 0, 0
		payload = self.payload(register)
		self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (230.5, -1, -1))
		self.assertEqual((payload["l2_a"], payload["l3_a"]), (-1, -1))

	def test_eine_phase_fehlt(self):
		register = beispiel_register()
		register[36053] = 0
		with self.assertRaisesRegex(MODULE.MesswertFehler, "L2/L3"):
			self.payload(register)

	def test_meter_ohne_kommunikation(self):
		register = beispiel_register()
		register[36004] = 0
		with self.assertRaisesRegex(MODULE.MesswertFehler, "kommuniziert nicht"):
			self.payload(register)

	def test_firmware_ohne_zaehlerspannungen(self):
		register = beispiel_register()
		register[36052] = register[36053] = register[36054] = 0
		with self.assertRaisesRegex(MODULE.MesswertFehler, "GOODWE_QUELLE=wechselrichter"):
			self.payload(register)

	def test_frequenz_ausserhalb_wird_weggelassen(self):
		register = beispiel_register()
		register[36014] = 6000
		with patch.object(MODULE, "log"):
			self.assertNotIn("grid_frequency_hz", self.payload(register))

	def test_quelle_wechselrichter(self):
		payload = self.payload(beispiel_register(), GOODWE_QUELLE="wechselrichter")
		self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (230.4, 229.7, 231.6))
		self.assertEqual(payload["grid_frequency_hz"], 49.89)
		self.assertEqual(payload["smartmeter_model"], "GoodWe GW10KN-ET")
		for feld in ("grid_power_w", "apparent_power_va", "power_factor", "l1_a"):
			self.assertNotIn(feld, payload)

	def test_ohne_batterie(self):
		register = beispiel_register()
		register[35180] = 0
		register[37007] = 0
		self.assertNotIn("battery_soc_percent", self.payload(register))

	def test_batterieregister_nicht_lesbar(self):
		register = beispiel_register()
		del register[37007]
		with patch.object(MODULE, "log"):
			self.assertNotIn("battery_soc_percent", self.payload(register))

	def test_statische_angaben(self):
		payload = self.payload(
			beispiel_register(), PLANT_CAPACITY_KWP=9.8, BATTERY_CAPACITY_KWH=10.2, SMARTMETER_MODEL="GoodWe GM3000"
		)
		self.assertEqual(payload["plant_capacity_kwp"], 9.8)
		self.assertEqual(payload["battery_capacity"], 10.2)
		self.assertEqual(payload["smartmeter_model"], "GoodWe GM3000")

	def test_keine_seriennummer(self):
		register = beispiel_register()
		for i, wert in enumerate(b"SERIAL12345678XY"[::2]):
			register[35003 + i] = wert
		self.assertNotIn("SERIAL", str(self.payload(register)))


class ModbusTests(unittest.TestCase):
	"""Prüft den Modbus-TCP-Client gegen einen minimalen lokalen Server."""

	def server(self, antwort_bauen):
		server = socket.socket()
		server.bind(("127.0.0.1", 0))
		server.listen(1)
		self.addCleanup(server.close)

		def bedienen():
			verbindung, _ = server.accept()
			with verbindung:
				anfrage = verbindung.recv(12)
				transaktion, _, _, unit, funktion, start, anzahl = struct.unpack(">HHHBBHH", anfrage)
				self.anfrage = (unit, funktion, start, anzahl)
				verbindung.sendall(antwort_bauen(transaktion, unit, anzahl))

		threading.Thread(target=bedienen, daemon=True).start()
		return server.getsockname()[1]

	def test_register_lesen(self):
		def antwort(transaktion, unit, anzahl):
			daten = struct.pack(f">{anzahl}H", *range(1, anzahl + 1))
			return struct.pack(">HHHBBB", transaktion, 0, 3 + len(daten), unit, 3, len(daten)) + daten

		port = self.server(antwort)
		with MODULE.ModbusVerbindung("127.0.0.1", port, 247) as verbindung:
			self.assertEqual(verbindung.lesen(36052, 3), [1, 2, 3])
		self.assertEqual(self.anfrage, (247, 3, 36052, 3))

	def test_exception_antwort(self):
		def antwort(transaktion, unit, anzahl):
			return struct.pack(">HHHBBB", transaktion, 0, 3, unit, 0x83, 2)

		port = self.server(antwort)
		with MODULE.ModbusVerbindung("127.0.0.1", port, 247) as verbindung:
			with self.assertRaisesRegex(MODULE.MesswertFehler, "Modbus-Fehler 2"):
				verbindung.lesen(40000, 1)


if __name__ == "__main__":
	unittest.main()
