# Ortsnetz-Auslastung für SMA Sunny Home Manager 2.0 und SMA Energy Meter

Der Sunny Home Manager 2.0 und das SMA Energy Meter senden ihre Messwerte als Speedwire-Multicast (SMA-EMETER-Protokoll) in das lokale Netzwerk. Dieses Python-Script empfängt die Telegramme lokal ohne Sunny-Portal-Zugang, dekodiert die Phasenspannungen L1, L2, L3 sowie eine vorhandene Netzfrequenz und sendet die erste gültige Messung nach dem Start und danach alle fünf Minuten an die Ortsnetz-Auslastung-API.

## Voraussetzungen

- SMA Sunny Home Manager 2.0 oder SMA Energy Meter (EMETER-20)
- Dauerhaft laufender Linux-Rechner mit Internetzugang im **selben Layer-2-Netz** wie der Zähler, z. B. Raspberry Pi, NAS oder Home-Server
- Python ab Version 3.8, nur Standardbibliothek
- Koordinaten des Messorts, bestimmbar über [OpenStreetMap](https://www.openstreetmap.org/): Ort suchen, Rechtsklick, **„Abfrage starten“**

Die Netzfrequenz liefert der Sunny Home Manager 2.0; fehlt sie im Telegramm, etwa beim SMA Energy Meter, wird sie weggelassen.

## Empfang

- Die Telegramme gehen an die Multicast-Gruppe `239.12.255.254`, UDP-Port `9522`, und überqueren ohne eigens eingerichtete Weiterleitung keine VLAN- oder Subnetz-Grenzen. Access Points filtern Multicast häufig — kabelgebundene Anbindung ist zuverlässiger.
- Bei mehreren Interfaces oder VLANs `INTERFACE_IP` auf die **lokale** IP im Zähler-Netz setzen (nicht die des SMA-Geräts). Bei `0.0.0.0` wählt das Betriebssystem das Interface; diese Wahl kann am Zähler-Netz vorbeigehen.
- Sind im Sunny Portal direkte Empfänger eingetragen, entfällt der Multicast-Versand ([Betriebsanleitung, Kapitel 11.3.12](https://www.sunnyportal.com/Documents/HM-20-BE-de-19.pdf)). Das Script verarbeitet auch direkt an den Rechner gesendete Telegramme auf Port 9522; bestehende Empfänger der Anlagensteuerung dabei beibehalten.
- Verarbeitet werden nur unverschlüsselte EMETER-Telegramme. Ob sie in der eigenen Anlagenkonfiguration verfügbar sind, zeigt `--dry-run`.

## Installation

1. Script nach `/opt/ortsnetz-auslastung/ortsnetz-sma-shm2.py` kopieren.
2. Im Konfigurationsblock mindestens `LATITUDE` und `LONGITUDE` anpassen; bei mehreren Interfaces zusätzlich `INTERFACE_IP`.
3. Empfang testen, ohne zu senden — die Ausgabe zeigt Seriennummer und Payload; Spannungen mit einer vorhandenen Anzeige vergleichen:

   ```sh
   python3 /opt/ortsnetz-auslastung/ortsnetz-sma-shm2.py --dry-run
   ```

4. Einmalig senden: gleicher Aufruf mit `--once`. Beide Modi liefern Exitcode 0 bei Erfolg, 1 bei Empfangs- oder Übertragungsfehlern, 2 bei ungültiger Konfiguration; `--help` zeigt die Optionen.
5. Dauerbetrieb als systemd-Dienst, Datei `/etc/systemd/system/ortsnetz-sma.service`:

   ```ini
   [Unit]
   Description=Ortsnetz-Auslastung SMA Speedwire
   After=network-online.target
   Wants=network-online.target

   [Service]
   ExecStart=/usr/bin/python3 /opt/ortsnetz-auslastung/ortsnetz-sma-shm2.py
   Restart=always
   RestartSec=30

   [Install]
   WantedBy=multi-user.target
   ```

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now ortsnetz-sma.service
   journalctl -u ortsnetz-sma.service -f
   ```

## Konfiguration

```python
LATITUDE = None             # z. B. 52.520008
LONGITUDE = None            # z. B. 13.404954
INTERFACE_IP = "0.0.0.0"    # bei mehreren Interfaces: lokale IP im Zähler-Netz
METER_SERIAL = None         # nur bei mehreren EMETER-Geräten nötig
INTERVAL_S = 300
```

Die Standardwerte der `konfig(...)`-Aufrufe im Script anpassen oder per Umgebungsvariable mit Präfix `ORTSNETZ_` überschreiben, z. B. `ORTSNETZ_LATITUDE=52.520008`; nichtleere Umgebungsvariablen haben Vorrang, die `.env`-Datei lädt nur Docker Compose. Alle Werte werden beim Start validiert.

## Docker

[`Dockerfile`](Dockerfile) und [`compose.yaml`](compose.yaml) liegen bei; die Konfiguration kommt aus einer `.env`-Datei (von Git ausgeschlossen, ohne Koordinaten verweigert Compose den Start):

```sh
cp .env.example .env    # Koordinaten, ggf. Interface-IP und Seriennummer eintragen
docker compose build
docker compose run --rm ortsnetz-sma-shm2 python3 ortsnetz-sma-shm2.py --dry-run
docker compose up -d
docker logs -f ortsnetz-sma-shm2
```

Zugang zum Zähler-Netz für den Multicast-Empfang:

- `network_mode: host` (Voreinstellung): Container nutzt den Netz-Stack des Hosts; bei mehreren Interfaces `ORTSNETZ_INTERFACE_IP` auf die Host-IP im Zähler-Netz setzen.
- macvlan-Netz: eigene Container-IP im Zähler-Netz, wenn der Host dort kein Interface hat; `ORTSNETZ_INTERFACE_IP` kann auf `0.0.0.0` bleiben.
- Dual-homed: Darf das Zähler-VLAN nicht ins Internet, zusätzlich zum macvlan-Netz ein Bridge-Netz für den Upload anbinden; `ORTSNETZ_INTERFACE_IP` dann auf die macvlan-IP des Containers setzen.

## Dekodierte Messwerte

| Messwert | OBIS-Index im Telegramm | Einheit im Telegramm |
| --- | --- | --- |
| Spannung L1 | 32.4.0 | 0,001 V |
| Spannung L2 | 52.4.0 | 0,001 V |
| Spannung L3 | 72.4.0 | 0,001 V |
| Netzfrequenz | 14.4.0 | 0,001 Hz |

Es werden nur interne Messwerte (OBIS-Kanal 0, Tarif 0) verwendet; unvollständige Telegramme und unbekannte Datensatztypen werden verworfen. Nicht vorhandene oder unplausible L2/L3-Spannungen werden mit `-1` übertragen, ohne gültige L1-Spannung erfolgt kein Upload. Protokollgrundlage: [SMA Energy Meter Protocol](https://developer.sma.de/fileadmin/content/www.developer.sma.de/docs/EMETER-Protokoll-TI-en-10.pdf); die SHM2-Frequenzzuordnung ist auch im [openWB-Decoder](https://github.com/openWB/core/blob/master/packages/modules/devices/sma/sma_shm/speedwiredecoder.py) implementiert.

## Fehleranalyse

- `Kein gültiges EMETER-Telegramm ... empfangen`: `INTERFACE_IP`, `METER_SERIAL`, VLANs und direkte Zähler-Kommunikation prüfen; Switches/APs müssen die Multicast-Gruppe weiterleiten (bei IGMP-Snooping den Querier prüfen).
- Falscher Zähler: `METER_SERIAL` auf die Seriennummer aus der `--dry-run`-Ausgabe setzen.
- `HTTP ...`: Die API hat den Request abgelehnt; Antwort im Log prüfen.
- `Übertragung fehlgeschlagen`: Internetzugang, DNS und Systemzeit prüfen. Kommen Telegramme an, scheitert aber der Upload mit Timeout, blockiert möglicherweise eine ausgehende Firewall-Regel (z. B. ein Geo-Filter) den API-Server.

## Tests

Vom Repository-Hauptverzeichnis, ohne Netzwerk oder zusätzliche Pakete; die Tests nutzen synthetische Telegramme und ersetzen den Empfangstest mit echter Hardware nicht:

```sh
python3 -B -m unittest discover -s sma-shm2-ortsnetz-auslastung -v
```
