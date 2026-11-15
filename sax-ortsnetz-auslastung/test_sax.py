#!/usr/bin/env python3
"""Tests für die Dekodierung in sax_ortsnetz_auslastung.py (ohne Zähler).

Aufruf: python3 test_sax.py

Version: 0.1.0
Erstellt: 2026-10-08
Geändert: 2026-10-08 - V0.1.0: Erstversion
"""

import unittest

import sax_ortsnetz_auslastung as sax

START = 40062


def registers(l1, l2, l3, voltage_sf=-1, frequency=5001, frequency_sf=-2):
    """Rohregister 40062..40071 (nicht genutzte Register 0)."""
    regs = [0] * 10
    regs[0], regs[1], regs[2] = l1, l2, l3
    regs[7] = voltage_sf & 0xFFFF
    regs[8] = frequency
    regs[9] = frequency_sf & 0xFFFF
    return regs


class DecodeTest(unittest.TestCase):
    def test_three_phases(self):
        self.assertEqual(sax.decode(registers(2301, 2299, 2304), START), (230.1, 229.9, 230.4, 50.01))

    def test_single_phase_marks_missing_phases(self):
        self.assertEqual(sax.decode(registers(2301, 0, 0), START), (230.1, -1, -1, 50.01))

    def test_not_implemented_marker(self):
        self.assertEqual(sax.decode(registers(2301, 0xFFFF, 0xFFFF), START)[1:3], (-1, -1))

    def test_l1_implausible_raises(self):
        with self.assertRaises(sax.MeasurementError):
            sax.decode(registers(0, 2300, 2300), START)

    def test_implausible_frequency_is_omitted(self):
        self.assertIsNone(sax.decode(registers(2301, 2300, 2300, frequency=0), START)[3])

    def test_frequency_disabled(self):
        saved = sax.CONFIG["register_frequency"]
        sax.CONFIG["register_frequency"] = None
        try:
            self.assertIsNone(sax.decode(registers(2301, 2300, 2300), START)[3])
        finally:
            sax.CONFIG["register_frequency"] = saved

    def test_payload_without_frequency_and_with_minus_one(self):
        payload = sax.build_payload(230.1, -1, -1, None)
        self.assertNotIn("grid_frequency_hz", payload)
        self.assertEqual((payload["l2_v"], payload["l3_v"]), (-1, -1))
        self.assertLessEqual(len(payload["integration_version"]), 32)


if __name__ == "__main__":
    unittest.main()
