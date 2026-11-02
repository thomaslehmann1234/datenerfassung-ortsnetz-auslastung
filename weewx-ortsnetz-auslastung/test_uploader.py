"""Regression tests using the installed WeeWX RESTThread; no network calls.

Run: python -m unittest discover -s weewx-ortsnetz-auslastung -p 'test_*.py'
"""

import importlib.util
import queue
import unittest
from pathlib import Path
from unittest.mock import patch

import weewx.restx

spec = importlib.util.spec_from_file_location(
    "ortsnetz_uploader",
    Path(__file__).parent / "bin/user/ortsnetzauslastunguploader.py",
)
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


def make_thread(**overrides):
    options = dict(
        longitude=13.404954, latitude=52.520008,
        l1_v="supplyVoltage", l2_v="none", l3_v="none",
        grid_frequency_hz=None, plant_capacity_kwp=None,
        pv_forecast_kwh=None, smartmeter_model="Test meter",
        integration_version="weewx-test",
    )
    options.update(overrides)
    return uploader.RESTThread(queue.Queue(), **options)


class UploaderTest(unittest.TestCase):
    def setUp(self):
        # The payload is built by the real uploader using WeeWX unit conversion.
        self.record = {"dateTime": 1791540000, "usUnits": weewx.METRIC, "supplyVoltage": 230.1}

    def test_dry_run_never_reaches_upload(self):
        for value in (True, "true", "1"):
            with self.subTest(skip_upload=value):
                thread = make_thread(skip_upload=value)
                with patch.object(thread, "post_with_retries") as post:
                    with self.assertRaises(weewx.restx.AbortedPost):
                        thread.process_record(self.record, None)
                    post.assert_not_called()

    def test_false_dry_run_allows_upload(self):
        for value in (False, "false", "0"):
            with self.subTest(skip_upload=value):
                thread = make_thread(skip_upload=value)
                with patch.object(thread, "post_with_retries") as post:
                    thread.process_record(self.record, None)
                    post.assert_called_once()

    def test_archive_records_within_five_minutes_are_skipped(self):
        thread = make_thread()
        start = self.record["dateTime"]
        self.assertFalse(thread.skip_this_post(start))
        for delta in (1, 60, 120, 299):
            self.assertTrue(thread.skip_this_post(start + delta))
        self.assertFalse(thread.skip_this_post(start + 300))

    def test_short_or_disabled_intervals_cannot_increase_upload_rate(self):
        for interval in (None, 0, -1, 1, 60, "60", "300"):
            with self.subTest(interval=interval):
                thread = make_thread(post_interval=interval)
                self.assertFalse(thread.skip_this_post(1000))
                self.assertTrue(thread.skip_this_post(1299))
                self.assertFalse(thread.skip_this_post(1300))

    def test_longer_interval_is_preserved(self):
        thread = make_thread(post_interval="600")
        self.assertFalse(thread.skip_this_post(1000))
        self.assertTrue(thread.skip_this_post(1599))
        self.assertFalse(thread.skip_this_post(1600))


if __name__ == "__main__":
    unittest.main()
