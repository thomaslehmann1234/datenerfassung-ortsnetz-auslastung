import importlib.util
import pathlib
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).with_name("ortsnetz_evcc.py")
SPEC = importlib.util.spec_from_file_location("ortsnetz_evcc", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ShellyTests(unittest.TestCase):
    def test_three_phase_payload(self):
        response = {
            "a_voltage": 230.1,
            "b_voltage": 229.9,
            "c_voltage": 231.2,
            "a_freq": 49.98,
        }
        with patch.object(MODULE, "get_json", return_value=response):
            self.assertEqual(MODULE.read_shelly(), (230.1, 229.9, 231.2, 49.98))

    def test_single_phase_marks_missing_phases(self):
        response = {"a_voltage": 230.1, "a_freq": 50.0}
        with patch.object(MODULE, "get_json", return_value=response), patch.object(
            MODULE, "SHELLY_SINGLE_PHASE", True
        ):
            self.assertEqual(MODULE.read_shelly(), (230.1, -1, -1, 50.0))


class PayloadTests(unittest.TestCase):
    def test_optional_attributes_are_added(self):
        with patch.object(MODULE, "SOURCE", "shelly"), patch.object(
            MODULE, "read_shelly", return_value=(230.1, 229.9, 231.2, 49.98)
        ), patch.object(MODULE, "PLANT_CAPACITY_KWP", 10.0), patch.object(
            MODULE, "PV_FORECAST_KWH", 24.5
        ), patch.object(MODULE, "SMARTMETER_MODEL", "Shelly Pro 3EM"):
            data = MODULE.payload()
        self.assertEqual(data["l1_v"], 230.1)
        self.assertEqual(data["grid_frequency_hz"], 49.98)
        self.assertEqual(data["plant_capacity_kwp"], 10.0)
        self.assertEqual(data["pv_forecast_kwh"], 24.5)
        self.assertEqual(data["smartmeter_model"], "Shelly Pro 3EM")


if __name__ == "__main__":
    unittest.main()
