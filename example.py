#!/usr/bin/env python3
"""Minimal example client for the Ortsnetz-Auslastung measurement API."""

from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
LATITUDE = 52.520008  # Replace with your measurement location.
LONGITUDE = 13.404954  # Replace with your measurement location.


def send_measurement(
    l1_v: float,
    l2_v: float,
    l3_v: float,
    frequency_hz: float | None = None,
    *,
    pv_forecast_kwh: float | None = None,
) -> dict:
    """Send measured values and optionally today's total PV forecast in kWh."""
    payload = {
        "observed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": l1_v,
        "l2_v": l2_v,
        "l3_v": l3_v,
        "smartmeter_model": "Example smart meter",
        "integration_version": "python-example-0.1.1",
    }
    if frequency_hz is not None:
        payload["grid_frequency_hz"] = frequency_hz
    if pv_forecast_kwh is not None:
        payload["pv_forecast_kwh"] = pv_forecast_kwh

    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)


if __name__ == "__main__":
    try:
        # Replace with today's total PV forecast (0–100000 kWh), or omit it.
        result = send_measurement(229.8, 230.1, 230.0, 50.01, pv_forecast_kwh=24.5)
        print(json.dumps(result, indent=2))
    except HTTPError as error:
        print(f"API responded with HTTP {error.code}: {error.read().decode('utf-8')}")
    except URLError as error:
        print(f"Could not reach API: {error.reason}")
