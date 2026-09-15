# Datenerfassung für Ortsnetz-Auslastung

Diese Sammlung beschreibt die verfügbaren Wege, Spannungen im lokalen Stromnetz an die Ortsnetz-Auslastung-API zu übertragen. Alle Varianten senden mindestens die Spannungen von L1, L2 und L3, einen UTC-Zeitstempel und den ungefähren Standort. 

## Integrationen im Überblick

| Integration | Messquelle | Laufzeit | Upload | Geeignet für |
| --- | --- | --- | --- | --- |
| [Shelly Pro 3EM] | Direkte 3-Phasen-Messung | Shelly Script | HTTPS | Installation auf dem Shelly |
| [Tasmota] | Optischer IR-Lesekopf am Stromzähler | ESP32/Tasmota-Script | HTTPS/Webquery | Installation auf dem Lesekopf |
| [ioBroker] | Vorhandene Spannungs-Datenpunkte | ioBroker JavaScript | HTTPS | Bestehende ioBroker-Installation |

## Shelly Pro 3EM

Ein JavaScript für Shelly Plus/Pro liest die drei Spannungen direkt über `em:0` und sendet sie im Fünf-Minuten-Takt. Das Script prüft dabei Werte außerhalb von 150–300 V.

- Ordner: `shelly-ortsnetz-auslastung`
- Messquelle: Shelly Pro 3EM
- Voraussetzung: Shelly-Scripting, WLAN und Internetzugang

Siehe die Installations- und Konfigurationshinweise im jeweiligen Repository.

## Tasmota SML-Lesekopf

Ein ESP32 mit optischem Lesekopf liest SML-Telegramme des Stromzählers und überträgt die OBIS-Werte für L1, L2, L3 und optional die Frequenz direkt per `WebQuery`.

- Ordner: lokal `tasmota-ortsnetz-auslastung`
- Messquelle: digitaler Stromzähler mit optischer Schnittstelle
- Voraussetzung: ESP32 (HTTPS), selbst kompilierte Tasmota-Firmware mit `USE_SCRIPT` und `USE_SML_M`, freigeschaltete Info-Schnittstelle des Zählers

Die Pinbelegung, Baudrate und OBIS-Werte können je Zählermodell abweichen. Das enthaltene Beispiel zielt auf binäres SML deutscher Basiszähler.

## ioBroker

Ein Script für den ioBroker-JavaScript-Adapter liest drei vorhandene Datenpunkte für die Phasenspannungen. Die Messwerte können beispielsweise von einem Shelly-, Smart-Meter- oder Modbus-Adapter stammen.

- Repository: lokal `iobroker-ortsnetz-auslastung`
- Messquelle: beliebige ioBroker-Datenpunkte für L1/L2/L3
- Voraussetzung: `ioBroker.javascript` ab 7.9.0

Es gibt keine zusätzlichen npm-Abhängigkeiten: Das Script nutzt `httpPost` aus dem JavaScript-Adapter.

## Gemeinsame Eigenschaften

- Intervall: fünf Minuten
- Pflichtwerte: Zeit, Standort und drei Phasenspannungen
- Plausibilitätsprüfung: Spannungen nur im Bereich 150–300 V
- Optional: Netzfrequenz (45–55 Hz), Anlagenleistung und PV-Prognose
- Datenschutz: Keine Zählernummer, Seriennummer, IP-Adresse, Leistung oder Energieverbrauch erforderlich

## API

Details und Beispiele stehen in [API.md](API.md).

Kurzfassung:

```text
POST https://www.ortsnetz-auslastung.de/v1/measurements
Content-Type: application/json
```

Eine erfolgreich angenommene Messung liefert `202 Accepted` zurück.

## Standortkoordinaten

Latitude und Longitude können direkt über [OpenStreetMap](https://www.openstreetmap.org/) ermittelt werden: Standort suchen, Rechtsklick auf die Karte und **„Abfrage starten“** wählen.
