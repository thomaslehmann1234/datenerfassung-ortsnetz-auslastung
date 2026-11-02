import importlib.util
import pathlib
import signal
import time
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).with_name("ortsnetz_smartwb.py")
SPEC = importlib.util.spec_from_file_location("ortsnetz_smartwb", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

# Beispielantwort aus der API-Dokumentation EVSE-WiFi 2.0 / smartWB
BEISPIEL = {
    "type": "parameters",
    "list": [
        {
            "vehicleState": 3,
            "evseState": False,
            "currentP1": 9.78,
            "currentP2": 0,
            "currentP3": 0,
            "voltageP1": 228.28,
            "voltageP2": 231.85,
            "voltageP3": 232.07,
            "useMeter": True,
            "RFIDUID": "0a1b2c3d",
        }
    ],
}


def antwort(**spannungen):
    eintrag = dict(BEISPIEL["list"][0])
    eintrag.update(spannungen)
    return {"type": "parameters", "list": [eintrag]}


class PayloadTests(unittest.TestCase):
    def setUp(self):
        for name, wert in (("SMARTWB_HOST", "192.168.1.50"), ("LATITUDE", 52.52), ("LONGITUDE", 13.4)):
            patcher = patch.object(MODULE, name, wert)
            patcher.start()
            self.addCleanup(patcher.stop)

    def payload(self, antwort_json):
        with patch.object(MODULE, "json_holen", return_value=antwort_json) as holen:
            payload = MODULE.payload_erstellen()
        holen.assert_called_once_with("http://192.168.1.50/getParameters")
        return payload

    def test_dreiphasig(self):
        payload = self.payload(BEISPIEL)
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (228.28, 231.85, 232.07))
        self.assertEqual(payload["smartmeter_model"], "smartWB")
        self.assertEqual(payload["integration_version"], "smartwb-0.1.0")
        self.assertNotIn("grid_frequency_hz", payload)
        self.assertNotIn("plant_capacity_kwp", payload)
        self.assertRegex(payload["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_einphasig_setzt_minus_eins(self):
        payload = self.payload(antwort(voltageP2=0, voltageP3=0))
        self.assertEqual((payload["l1_v"], payload["l2_v"], payload["l3_v"]), (228.28, -1, -1))

    def test_nur_eine_weitere_phase_ist_fehler(self):
        with self.assertRaises(MODULE.MesswertFehler):
            self.payload(antwort(voltageP3=0))

    def test_l1_nicht_plausibel_ist_fehler(self):
        with self.assertRaises(MODULE.MesswertFehler):
            self.payload(antwort(voltageP1=0))
        with self.assertRaises(MODULE.MesswertFehler):
            self.payload(antwort(voltageP1=400))

    def test_fehlende_spannung_ist_fehler(self):
        eintrag = dict(BEISPIEL["list"][0])
        del eintrag["voltageP1"]
        with self.assertRaises(MODULE.MesswertFehler):
            self.payload({"list": [eintrag]})

    def test_unerwartetes_format_ist_fehler(self):
        for kaputt in ({}, {"list": []}, {"list": ["x"]}, []):
            with self.assertRaises(MODULE.MesswertFehler):
                self.payload(kaputt)

    def test_plant_capacity_wird_uebernommen(self):
        with patch.object(MODULE, "PLANT_CAPACITY_KWP", 9.8):
            self.assertEqual(self.payload(BEISPIEL)["plant_capacity_kwp"], 9.8)


class LaufzeitTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(signal, "SIGALRM"), "nur Unix")
    def test_laufzeitbegrenzung_bricht_ab(self):
        self.addCleanup(signal.alarm, 0)
        self.addCleanup(signal.signal, signal.SIGALRM, signal.SIG_DFL)
        with patch.object(MODULE, "MAX_LAUFZEIT_S", 1):
            MODULE.laufzeit_begrenzen()
        with self.assertRaises(SystemExit) as fehler:
            time.sleep(3)
        self.assertIn("Maximale Laufzeit", str(fehler.exception))


class EinstellungTests(unittest.TestCase):
    def test_environment_hat_vorrang(self):
        with patch.dict("os.environ", {"SMARTWB_HOST": "wb.local", "LATITUDE": "48.1", "LONGITUDE": "11.5"}):
            with patch.object(MODULE, "SMARTWB_HOST", ""), patch.object(MODULE, "LATITUDE", None), patch.object(
                MODULE, "LONGITUDE", None
            ):
                MODULE.konfiguration_laden()
                self.assertEqual((MODULE.SMARTWB_HOST, MODULE.LATITUDE, MODULE.LONGITUDE), ("wb.local", 48.1, 11.5))

    def test_ungueltige_environment_variable(self):
        with patch.dict("os.environ", {"LATITUDE": "abc"}):
            with self.assertRaises(SystemExit):
                MODULE.konfiguration_laden()

    def test_pflichtwerte(self):
        with patch.object(MODULE, "SMARTWB_HOST", ""):
            with self.assertRaises(SystemExit):
                MODULE.konfiguration_pruefen()
        with patch.object(MODULE, "SMARTWB_HOST", "x"), patch.object(MODULE, "LATITUDE", None):
            with self.assertRaises(SystemExit):
                MODULE.konfiguration_pruefen()


if __name__ == "__main__":
    unittest.main()
