# Ortsnetz-Auslastung für Siemens PAC Messgeräte

Ein eigenständiges Node.js-Script ohne zusätzliche Abhängigkeiten. Es liest die L1-, L2- und L3-Spannung sowie die Netzfrequenz über die lokale REST API eines SIEMENS SENTRON PAC Messgeräts, prüft die Werte und überträgt sie alle fünf Minuten per HTTPS an die Ortsnetz-Auslastung-API.

Unterstützt werden z.B. PAC2200, PAC2200-CLP, PAC3200T, PAC3220, PAC4200, PAC4220

## Voraussetzungen

- Node.js ab Version 18 oder Docker.
- Erreichbares PAC Gerät im lokalen Netz.
- Internetzugang des ausführenden Hosts für den Upload.

## Installation

1. Repository klonen.
2. Umgebungsvariablen setzen: `ORTSNETZ_DEVICE_IP`, `ORTSNETZ_LATITUDE`, `ORTSNETZ_LONGITUDE` (siehe [.env.example](.env.example)).
3. `npm start` ausführen. Nach dem ersten Upload werden alle fünf Minuten Messwerte übertragen.

Beispiel Umgebungsvariablen:

```bash
ORTSNETZ_DEVICE_IP=192.168.10.30 \
ORTSNETZ_LATITUDE=54.551807 \
ORTSNETZ_LONGITUDE=5.622114 \
node ortsnetz-siemens-pac.js
```

Beispiel .env Datei:

```bash
echo 'ORTSNETZ_DEVICE_IP=192.168.10.30' >> .env
echo 'ORTSNETZ_LATITUDE=54.551807' >> .env
echo 'ORTSNETZ_LONGITUDE=5.622114' >> .env
node --env-file .env ortsnetz-siemens-pac.js
```

Das API-Format (`data.json` oder `/api-webserver`) wird automatisch erkannt; es muss nur die IP-Adresse gesetzt werden.

Koordinaten lassen sich mit [OpenStreetMap](https://www.openstreetmap.org/) bestimmen: Standort suchen, Rechtsklick auf die Karte und **„Abfrage starten“** wählen.

## Konfiguration

| Variable | Pflicht | Beschreibung |
| --- | --- | --- |
| `ORTSNETZ_DEVICE_IP` | Ja | IP-Adresse des Messgeräts, z. B. `192.168.10.30` |
| `ORTSNETZ_LATITUDE` | Ja | Breitengrad des Messorts |
| `ORTSNETZ_LONGITUDE` | Ja | Längengrad des Messorts |
| `ORTSNETZ_PLANT_CAPACITY_KWP` | Nein | Installierte PV-Leistung in kWp |
| `ORTSNETZ_INTERVAL_S` | Nein | Upload interval in seconds, default 300; allowed range 300–2147483.647. Invalid values stop startup before any network requests. |
| `ORTSNETZ_DRY_RUN` | Nein | Wert mit `=1` setzen, um das zu sendende Payload nur auszugeben, ohne an die API zu übertragen; der Prozess beendet sich danach |

## Docker

```bash
docker run --rm \
  -e ORTSNETZ_DEVICE_IP=192.168.10.30 \
  -e ORTSNETZ_LATITUDE=52.520008 \
  -e ORTSNETZ_LONGITUDE=13.404954 \
  siemens-pac-ortsnetz-auslastung
```

Oder mit [compose.yaml](compose.yaml): `.env` mit den `ORTSNETZ_*`-Werten befüllen und `docker compose up -d`.

## Verhalten

- Das API-Format wird automatisch erkannt.
- Der Model-Name wird automatisch erkannt, z.B. `SIEMENS SENTRON PAC4220`.
- Phasen ohne gültigen Messwert werden als `-1` gesendet; einphasige Messungen werden auch unterstützt.
- Missing or invalid phase voltages (outside 150–300 V) are sent as `-1`. If no phase is valid, the upload is skipped.
- Die Frequenz wird nur gesendet, wenn sie zwischen 45 und 55 Hz liegt.
- Bei `202 Accepted` wird der Ampelstatus geloggt; bei `yellow` zusätzlich eine Warnung.
- Alle Zeitüberschreitungen betragen 10 Sekunden; Fehler führen nicht zum Abbruch, der nächste Upload-Lauf wird normal erneut versucht.

## Copyright

- Programmiert von mojoaxel mit QWen3.8-27B
- Lizenz: MIT
