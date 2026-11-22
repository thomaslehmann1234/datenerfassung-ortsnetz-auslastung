"""Regressionstests ohne Netzwerkzugriffe."""

import contextlib
import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

PFAD = Path(__file__).with_name("ortsnetz-shelly.py")
SPEC = importlib.util.spec_from_file_location("shelly", PFAD)
shelly = importlib.util.module_from_spec(SPEC)
with patch.dict("os.environ", {}, clear=True):
    SPEC.loader.exec_module(shelly)

STATUS = {
    "a_voltage": 230.123, "b_voltage": 229.9, "c_voltage": 231.2,
    "a_current": 1.5, "b_current": 2.0, "c_current": 0.5,
    "a_freq": 50.01, "b_freq": 50.0, "c_freq": 50.02,
    "total_act_power": -350.5, "total_aprt_power": 900.0,
}


class Basis(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.multiple(
            shelly, LATITUDE=52.5, LONGITUDE=13.4, SHELLY_IP="192.0.2.10",
            SHELLY_MODEL="Shelly Pro 3EM", STROMWANDLER_A=120, CAPACITY_KWP=None,
            BATTERY_KWH=None, INTERVAL_S=300, SAMPLE_INTERVAL_S=15))
        self.ausgabe = io.StringIO()
        stack.enter_context(contextlib.redirect_stdout(self.ausgabe))
        self.http = stack.enter_context(patch.object(
            shelly.urllib.request, "urlopen", side_effect=AssertionError("Unerwarteter HTTP-Aufruf")))

    def antwort(self, daten, status=202):
        antwort = MagicMock()
        antwort.status = status
        antwort.read.return_value = json.dumps(daten).encode()
        kontext = MagicMock()
        kontext.__enter__.return_value = antwort
        return kontext


class PayloadTest(Basis):
    def test_pflichtfelder_und_optionale_felder(self):
        p = shelly.payload_erstellen(STATUS)
        self.assertEqual([p["l1_v"], p["l2_v"], p["l3_v"]], [230.12, 229.9, 231.2])
        self.assertEqual([p["l1_a"], p["l2_a"], p["l3_a"]], [1.5, 2.0, 0.5])
        self.assertEqual(p["grid_frequency_hz"], 50.01)
        self.assertEqual(p["grid_power_w"], -350.5)
        self.assertEqual(p["apparent_power_va"], 900.0)
        self.assertTrue(p["observed_at"].endswith("Z"))
        self.assertEqual(p["integration_version"], shelly.VERSION)
        self.assertNotIn("l1_v_min", p)

    def test_ungueltige_phase_wird_minus_eins(self):
        p = shelly.payload_erstellen(dict(STATUS, b_voltage=None, c_voltage=0))
        self.assertEqual((p["l2_v"], p["l3_v"]), (-1, -1))
        self.assertNotIn("l2_a", p)
        self.assertNotIn("l3_a", p)

    def test_keine_gueltige_spannung(self):
        self.assertIsNone(shelly.payload_erstellen({"a_voltage": 10, "b_voltage": 400}))
        self.assertIsNone(shelly.payload_erstellen({}))

    def test_unplausible_frequenz_und_strom_werden_weggelassen(self):
        p = shelly.payload_erstellen(dict(STATUS, a_freq=60, b_freq=None, c_freq=float("nan"), a_current=999))
        self.assertNotIn("grid_frequency_hz", p)
        self.assertNotIn("l1_a", p)

    def test_statische_standortangaben(self):
        with patch.multiple(shelly, CAPACITY_KWP=9.8, BATTERY_KWH=10.2):
            p = shelly.payload_erstellen(STATUS)
        self.assertEqual((p["plant_capacity_kwp"], p["battery_capacity"]), (9.8, 10.2))

    def test_statistik_min_avg_max(self):
        statistik = shelly.neue_statistik()
        for u in (228.0, 232.0, 230.0):
            shelly.statistik_erfassen(statistik, {"a_voltage": u})
        p = shelly.payload_erstellen(dict(STATUS, a_voltage=230.0), statistik)
        self.assertEqual((p["l1_v_min"], p["l1_v_avg"], p["l1_v_max"]), (228.0, 230.0, 232.0))
        self.assertNotIn("l2_v_min", p)


class SendenTest(Basis):
    def test_annahme(self):
        self.http.side_effect = None
        self.http.return_value = self.antwort({"accepted": True, "status": {"overall": "green"}})
        self.assertTrue(shelly.senden({"x": 1}))

    def test_logzeile_enthaelt_gesendete_werte(self):
        self.http.side_effect = None
        self.http.return_value = self.antwort({"accepted": True, "status": {"overall": "green"}})
        shelly.senden(shelly.payload_erstellen(dict(STATUS, c_voltage=None)))
        zeile = self.ausgabe.getvalue()
        self.assertIn("L1 230.12 V, L2 229.9 V, L3 -, ", zeile)
        self.assertIn("50.01 Hz, -350.5 W", zeile)

    def test_http_fehler_wird_verworfen(self):
        self.http.side_effect = urllib.error.HTTPError("u", 422, "x", {}, None)
        self.assertFalse(shelly.senden({"x": 1}))

    def test_netzwerkfehler_wird_verworfen(self):
        self.http.side_effect = OSError("nicht erreichbar")
        self.assertFalse(shelly.senden({"x": 1}))

    def test_nicht_bestaetigte_annahme(self):
        self.http.side_effect = None
        self.http.return_value = self.antwort({"accepted": False})
        self.assertFalse(shelly.senden({"x": 1}))


class MainTest(Basis):
    def test_dry_run_gibt_payload_aus_ohne_senden(self):
        with patch.object(shelly, "shelly_lesen", return_value=STATUS):
            self.assertEqual(shelly.main(["--dry-run"]), 0)
        self.assertEqual(json.loads(self.ausgabe.getvalue())["l1_v"], 230.12)
        self.http.assert_not_called()

    def test_once_shelly_nicht_erreichbar(self):
        with patch.object(shelly, "shelly_lesen", side_effect=OSError("timeout")):
            self.assertEqual(shelly.main(["--once"]), 1)

    def test_once_sendet(self):
        self.http.side_effect = None
        self.http.return_value = self.antwort({"accepted": True})
        with patch.object(shelly, "shelly_lesen", return_value=STATUS):
            self.assertEqual(shelly.main(["--once"]), 0)

    def test_ungueltige_konfiguration_exitcode_2(self):
        with patch.object(shelly, "LATITUDE", None), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(shelly.main(["--once"]), 2)
        with patch.object(shelly, "INTERVAL_S", 60), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(shelly.main(["--once"]), 2)


if __name__ == "__main__":
    unittest.main()
