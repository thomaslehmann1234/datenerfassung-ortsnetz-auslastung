# Ortsnetz-Auslastung für den EcoFlow Smart Meter (ioBroker)

Ein Script für den ioBroker-JavaScript-Adapter. Es liest die Phasenspannungen L1–L3 des EcoFlow Smart Meters aus dem Adapter [ioBroker.ecoflow-mqtt](https://github.com/foxthefox/ioBroker.ecoflow-mqtt) und überträgt sie alle fünf Minuten per HTTPS an die Ortsnetz-Auslastung-API.

Zusätzlich zum aktuellen Wert werden Minimum, Maximum und Mittelwert jeder Phase über das 5-Minuten-Intervall gesendet. Außerdem wird die Netzleistung am Hausanschluss übertragen (abschaltbar).

## Voraussetzungen

- EcoFlow Smart Meter, in der EcoFlow-App eingerichtet
- ioBroker mit Adapter **ecoflow-mqtt**, Smart Meter dort konfiguriert (Gerätetyp „EF smartmeter“, Seriennummer aus der App)
- ioBroker mit Adapter **JavaScript** ab Version 7.9.0
- Internetzugang des ioBroker-Hosts

Die Daten des Smart Meters laufen über die EcoFlow-Cloud. Eine lokale Schnittstelle wird nicht benötigt.

## Verwendete Datenpunkte

| Datenpunkt | Inhalt |
|---|---|
| `ecoflow-mqtt.0.<Seriennummer>.DisplayPropertyUpload.voltageL1` | Spannung L1 in V |
| `ecoflow-mqtt.0.<Seriennummer>.DisplayPropertyUpload.voltageL2` | Spannung L2 in V |
| `ecoflow-mqtt.0.<Seriennummer>.DisplayPropertyUpload.voltageL3` | Spannung L3 in V |
| `ecoflow-mqtt.0.<Seriennummer>.DisplayPropertyUpload.totalPower` | Netzleistung in W (optional) |

Getestet mit ecoflow-mqtt 1.4.9.

## Installation

1. Im ioBroker-Admin unter **Objekte** prüfen, ob die Datenpunkte oben vorhanden sind und Werte liefern.
2. Unter **Skripte** ein neues JavaScript-Script erstellen und den Inhalt von [ortsnetz-auslastung-ecoflow.js](ortsnetz-auslastung-ecoflow.js) einfügen.
3. Im `CONFIG`-Block anpassen:
   - `latitude` und `longitude`, auf 2–3 Nachkommastellen gerundet
   - `SERIENNUMMER` in `meterBase` durch die Seriennummer des Smart Meters ersetzen
   - optional `plantCapacityKwp`
4. Für den ersten Lauf `debug: true` setzen und das Script starten. Im Log muss eine Zeile mit `"accepted":true` erscheinen. Danach `debug: false` setzen.

Das Script sendet sofort nach dem Start und danach alle fünf Minuten.

Koordinaten lassen sich mit [OpenStreetMap](https://www.openstreetmap.org/) bestimmen: Standort suchen, Rechtsklick auf die Karte und **„Abfrage starten“** wählen.

## Netzleistung

Die API erwartet `grid_power_w` positiv bei Bezug und negativ bei Einspeisung. `totalPower` des EcoFlow Smart Meters folgt bereits dieser Konvention (geprüft durch Einschalten eines Wasserkochers: Wert steigt um ca. +2000 W). Die Netzleistung wird daher standardmäßig mitgesendet (`sendGridPower: true`).

- Nicht senden: `sendGridPower: false`
- Falls das Vorzeichen bei einer anderen Firmware umgekehrt sein sollte: `invertGridPower: true`

## Status-Datenpunkte

Die API-Antwort wird unter `0_userdata.0.ortsnetz` abgelegt (abschaltbar mit `statusPrefix: ''`). Jeder Upload-Versuch schreibt alle Datenpunkte neu. Nach einem Fehler oder übersprungenen Upload bleibt also kein alter Erfolgsstatus und keine alte Empfehlung stehen.

| Datenpunkt | Erfolg | Fehler oder übersprungener Upload |
|---|---|---|
| `http_status` | `202` | HTTP-Status der API (z. B. `422`), `null` bei Timeout, Verbindungsfehler oder übersprungenem Upload |
| `last_error` | leer | Grund des Fehlers |
| `overall`, `l1`, `l2`, `l3` | `green` / `yellow` / `red` | `null` |
| `storage_recommendation` | `none` / `charge` / `discharge` | `null` |
| `last_upload` | Zeitpunkt dieses Uploads | unverändert: Zeitpunkt des letzten erfolgreichen Uploads |

## Verhalten und Fehleranalyse

- Spannungswerte außerhalb von 150–300 V werden nicht übertragen.
- Sind die Werte älter als 10 Minuten (`maxAgeSeconds`), wird nicht gesendet. So werden bei einem Ausfall der EcoFlow-Cloud keine eingefrorenen Werte gemeldet.
- `smartmeter_model` und `plant_capacity_kwp` werden einmal pro Script-Start mitgesendet.
- Warnungen stehen im ioBroker-Log unter `Ortsnetz-Auslastung`.

| Log-Meldung | Maßnahme |
|---|---|
| `Seriennummer in meterBase nicht eingetragen` | `SERIENNUMMER` ersetzen |
| `Datenpunkt nicht lesbar` | Datenpunkt-IDs unter **Objekte** prüfen |
| `… veraltet` | Verbindung des ecoflow-mqtt-Adapters zur EcoFlow-Cloud prüfen |
| `HTTP-Status 422` | Payload mit `debug: true` prüfen, siehe [API.md](../API.md) |

Geräte-ID und Seriennummer werden nicht übertragen.
