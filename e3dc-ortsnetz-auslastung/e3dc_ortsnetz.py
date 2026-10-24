#!/usr/bin/env python3
import json
import traceback
import urllib.request
from datetime import datetime
from e3dc import E3DC

# --- Konfiguration ---
E3DC_IP = "IP Addresse"  # IP-Adresse deines E3/DC Kraftwerks
E3DC_USER = "USER"  # Portal-Benutzername (E3/DC Login)
E3DC_PASS = "PASSWORT"  # Portal-Passwort
RSCP_KEY = "RSCP KEY"  # Lokales RSCP-Verschlüsselungspasswort

# Ungefährer Standort (Dezimalgrad, z. B. über OpenStreetMap ermittelt)
LATITUDE = 52.520008
LONGITUDE = 13.404954

API_URL = "https://www.ortsnetz-auslastung.de/v1/measurements"
INTEGRATION_VERSION = "e3dc-rscp-1.0"

def main():
  try:
    print("Verbinde mit E3/DC...")
    e3dc = E3DC(
        E3DC.CONNECT_LOCAL,
        username=E3DC_USER,
        password=E3DC_PASS,
        ipAddress=E3DC_IP,
        key=RSCP_KEY,
    )

    print("Rufe Zählerdaten ab...")
    powermeters = e3dc.get_powermeters_data()
    e3dc.disconnect()

    if not powermeters:
      print("Fehler: Keine Zählerdaten vom E3/DC empfangen.")
      return

    # Netzzähler (Grid Meter) ist das erste Element
    grid_meter = powermeters[0]

    l1, l2, l3 = None, None, None
    frequency = None

    # Flexible Erkennung der Phasenspannungen
    if isinstance(grid_meter, dict):
      for k in ["voltageL1", "L1_VOLTAGE", "VOLTAGE_L1", "v1"]:
        if k in grid_meter:
          l1 = float(grid_meter.get(k, 0))
          l2 = float(grid_meter.get(k.replace("1", "2"), 0))
          l3 = float(grid_meter.get(k.replace("1", "3"), 0))
          break

      if l1 is None and "voltage" in grid_meter:
        v = grid_meter["voltage"]
        if isinstance(v, (list, tuple)) and len(v) >= 3:
          l1, l2, l3 = float(v[0]), float(v[1]), float(v[2])
        elif isinstance(v, dict):
          l1 = float(v.get("L1", v.get(0, 0)))
          l2 = float(v.get("L2", v.get(1, 0)))
          l3 = float(v.get("L3", v.get(2, 0)))

      # Frequenz auslesen (verschiedene mögliche Schlüssel abfangen)
      for fk in ["frequency", "freq", "FREQUENCY", "f"]:
        if fk in grid_meter:
          frequency = float(grid_meter.get(fk))
          break

    if l1 is None or l2 is None or l3 is None:
      print(
          "Fehler: Konnte die Phasenspannungen nicht aus den Zählerdaten"
          " extrahieren."
      )
      return

    freq_str = f" | Frequenz: {frequency}Hz" if frequency is not None else ""
    print(f"Gelesene Werte: L1={l1}V, L2={l2}V, L3={l3}V{freq_str}")

    # Plausibilitätsprüfung
    if not (150 <= l1 <= 300 and 150 <= l2 <= 300 and 150 <= l3 <= 300):
      print(f"Unplausible Spannungswerte: L1={l1}V, L2={l2}V, L3={l3}V")
      return

    # API-Payload aufbauen
    payload = {
        "observed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "l1_v": round(l1, 2),
        "l2_v": round(l2, 2),
        "l3_v": round(l3, 2),
        "smartmeter_model": "E3DC Hauskraftwerk",
        "integration_version": INTEGRATION_VERSION,
    }

    # Daten per HTTP POST an das Ortsnetz-Tool senden
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "E3DC-Ortsnetz-Client",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=10) as response:
      if response.status == 202:
        print(
            f"Erfolgreich übertragen ({response.status}): L1={l1}V, L2={l2}V,"
            f" L3={l3}V{freq_str}"
        )
      else:
        print(f"Unerwarteter HTTP-Statuscode: {response.status}")

  except Exception:
    traceback.print_exc()


if __name__ == "__main__":
  main()
