<!-- Version: 0.1.0 | Erstellt: 2026-10-08 | Geändert: 2026-10-08 - V0.1.0: Erstversion -->

# Ortsnetz-Auslastung für SAX Power Smartmeter

Ein eigenständiges Python-Script. Es liest die Phasenspannungen L1, L2, L3 und die Netzfrequenz des SAX-Smartmeters (ADL 400, SunSpec Model 203) per Modbus TCP vom SAX-Master und sendet sie sofort nach dem Start und danach alle fünf Minuten per HTTPS an die Ortsnetz-Auslastung-API.

## Voraussetzungen

- SAX Power Home oder Home Plus mit Smartmeter, Modbus TCP aktiviert (Unit-ID 100, SunSpec-Modus)
- Dauerhaft laufender Rechner mit Internetzugang im selben Netz wie der SAX-Master, z. B. Raspberry Pi
- Python ab Version 3.8 und das Paket `pyModbusTCP`
- Koordinaten des Messorts, bestimmbar über [OpenStreetMap](https://www.openstreetmap.org/): Ort suchen, Rechtsklick auf die Karte, **„Abfrage starten“**

## Installation

1. Ordner nach `/opt/ortsnetz-auslastung/sax/` kopieren.
2. Abhängigkeit installieren:

   ```sh
   pip3 install -r /opt/ortsnetz-auslastung/sax/requirements.txt
   ```

3. Im `CONFIG`-Block von [sax_ortsnetz_auslastung.py](sax_ortsnetz_auslastung.py) mindestens `latitude`, `longitude` und `modbus_host` anpassen.

## Konfiguration

| Feld | Beschreibung |
| --- | --- |
| `latitude`, `longitude` | Standort der Messung (Pflicht) |
| `modbus_host`, `modbus_port` | Adresse des SAX-Masters, Port standardmäßig 502 |
| `modbus_unit_id` | Unit-ID, standardmäßig 100 (SunSpec-Modus) |
| `modbus_timeout_s` | Timeout je Modbus-Zugriff in Sekunden |
| `register_voltage_l1`, `_l2`, `_l3` | Spannungsregister, standardmäßig 40062 bis 40064 |
| `register_voltage_sf` | Skalierungsfaktor der Spannung, standardmäßig 40069 |
| `register_frequency`, `register_frequency_sf` | Frequenz (40070) und Skalierungsfaktor (40071); `register_frequency: None` sendet keine Frequenz |
| `interval_s` | Abstand zwischen zwei Uploads, standardmäßig 300 |
| `smartmeter_model` | Freie Bezeichnung des Messgeräts |

Die Registeradressen gelten direkt, ohne 40001-Offset. Gelesen wird mit Function Code 3 (Holding Register) in einem Block von 40062 bis 40071. Die Skalierungsfaktoren werden bei jedem Lesen aus dem Gerät gelesen.

Bei mehreren Speichern nur den **Master** abfragen; die Werte der Slaves sind dort bereits zusammengeführt.

## Erster Test

1. Ohne Zähler prüfen, ob das Script läuft (Testwerte, kein Netzwerkzugriff):

   ```sh
   python3 sax_ortsnetz_auslastung.py --dry-run --simulate
   ```

2. Mit echtem Zähler lesen, ohne zu senden. Die Spannungen mit einer vorhandenen Anzeige vergleichen:

   ```sh
   python3 sax_ortsnetz_auslastung.py --dry-run
   ```

3. Echter Upload: Script ohne Option starten. Die Log-Zeile `Gesendet (HTTP 202)` bestätigt die Annahme.

   ```sh
   python3 sax_ortsnetz_auslastung.py
   ```

`--dry-run` liefert Exitcode 0 bei Erfolg, 1 bei Lesefehlern und 2 bei ungültiger Konfiguration.

## Dauerbetrieb mit systemd

Datei `/etc/systemd/system/ortsnetz-sax.service`:

```ini
[Unit]
Description=Ortsnetz-Auslastung SAX Smartmeter
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /opt/ortsnetz-auslastung/sax/sax_ortsnetz_auslastung.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ortsnetz-sax.service
journalctl -u ortsnetz-sax.service -f
```

## Docker

Ein eigenes Image ist nicht Teil dieser Integration. Mit dem offiziellen Python-Image lässt sich das Script so starten:

```sh
docker run -d --restart unless-stopped --name ortsnetz-sax \
  -v "$PWD":/app -w /app python:3.12-slim \
  sh -c "pip install --no-cache-dir -r requirements.txt && python sax_ortsnetz_auslastung.py"
```

## Verhalten und Fehleranalyse

- Jeder Modbus-Zugriff verbindet neu und schließt die Verbindung wieder. Bei einem Fehler folgen bis zu drei Versuche im Abstand von 0,5 Sekunden. Der SAX-Master verträgt höchstens einen Zugriff alle 500 ms; fragt ein zweites System denselben Master ab, kann das zu Timeouts führen.
- Schlägt Lesen oder Senden fehl, wird der Fehler geloggt und im nächsten Intervall erneut versucht. Das Script beendet sich nicht.
- Spannungen außerhalb von 150 bis 300 V gelten als nicht plausibel. Ist L1 nicht plausibel, wird nicht gesendet. Nicht plausible Werte für L2 und L3, etwa 0 bei einphasiger Messung, werden als `-1` übertragen.
- Die Frequenz wird nur gesendet, wenn sie zwischen 45 und 55 Hz liegt.
- Übertragungen erhalten eine Zeitüberschreitung von 10 Sekunden. Als Erfolg gilt HTTP `202`; andere Antworten werden mit Statuscode und Antworttext geloggt. Meldet die API den Ampelstatus `yellow`, erscheint eine Warnung.
- Es werden keine Zählernummern, Gerätekennungen, IP-Adressen oder Energiezähler gelesen oder gesendet.
- Bei `Verbindung fehlgeschlagen` Host, Port und Modbus-Freigabe des Masters prüfen. Bei `L1 nicht plausibel` Unit-ID 100 und das Modell des Zählers prüfen.

Tests ohne Zähler: `python3 test_sax.py`

## API

```text
POST https://www.ortsnetz-auslastung.de/v1/measurements
Content-Type: application/json
```

Beispiel-Payload:

```json
{
  "observed_at": "2026-09-15T08:00:00Z",
  "latitude": 52.520008,
  "longitude": 13.404954,
  "l1_v": 230.1,
  "l2_v": 229.9,
  "l3_v": 230.4,
  "grid_frequency_hz": 50.01,
  "smartmeter_model": "SAX Power Smartmeter",
  "integration_version": "sax-0.1.0"
}
```

Die API bestätigt angenommene Messungen mit HTTP `202`. Details siehe [API.md](../API.md).
