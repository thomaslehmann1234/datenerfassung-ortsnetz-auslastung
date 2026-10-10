# Datenerfassung für Ortsnetz-Auslastung

Dieses Repository bündelt Integrationen, die lokale Netzspannungsmessungen an die API von [ortsnetz-auslastung.de](https://www.ortsnetz-auslastung.de/) senden. Sie übertragen Spannungswerte, einen Zeitstempel und einen ungefähren Standort. Es ist kein API-Schlüssel erforderlich.

## Schnellnavigation

- [Shelly Pro 3EM und Pro EM50](#shelly-pro-3em-und-pro-em50)
- [SMA Sunny Home Manager 2.0 und Energy Meter](#sma-sunny-home-manager-20-und-energy-meter)
- [Tasmota SML-Lesekopf](#tasmota-sml-lesekopf)
- [Home Assistant](#home-assistant)
- [ioBroker](#iobroker)
- [MQTT](#mqtt)
- [evcc](#evcc)
- [Victron GX](#victron-gx)
- [Volkszähler](#volkszähler)
- [KOSTAL KSEM](#kostal-ksem)
- [openHAB](#openhab)
- [Fronius](#fronius)
- [Siemens PAC Energiemessgeräte](#siemens-pac-energiemessgerate)
- [SAX Power Smartmeter](#sax-power-smartmeter)
- [USV mit NUT](#usv-mit-nut)
- [WeeWX](#weewx)
- [Gemeinsame Eigenschaften](#gemeinsame-eigenschaften)
- [API](#api)
- [Koordinaten](#koordinaten)

## Integrationen

| Integration | Datenquelle | Laufzeit | Übertragung | Geeignet für |
| --- | --- | --- | --- | --- |
| [Shelly Pro 3EM und Pro EM50](#shelly-pro-3em-und-pro-em50) | Direkte Spannungsmessung | Shelly Script | HTTPS | Shelly-Installationen |
| [SMA Sunny Home Manager 2.0 und Energy Meter](#sma-sunny-home-manager-20-und-energy-meter) | Speedwire-Multicast (EMETER-Protokoll) | Python / systemd / Docker | HTTPS | SMA-Anlagen mit Sunny Home Manager 2.0 oder Energy Meter |
| [Tasmota SML-Lesekopf](#tasmota-sml-lesekopf) | Optische Smart-Meter-Schnittstelle | ESP32 / Tasmota Script | HTTPS / WebQuery | SML-fähige Stromzähler |
| [Home Assistant](#home-assistant) | Vorhandene Spannungssensoren | Home Assistant / HACS | HTTPS | Home-Assistant-Installationen |
| [ioBroker](#iobroker) | Vorhandene Spannungsdatenpunkte | ioBroker JavaScript | HTTPS | ioBroker-Installationen |
| [MQTT](#mqtt) | MQTT-Topics | Node.js / Docker | HTTPS | Smart-Meter-Gateways mit MQTT und EVCC |
| [evcc](#evcc) | Shelly Gen2/3 oder Modbus TCP | Python / cron | HTTPS | evcc-Installationen mit direktem Zählerzugriff |
| [Victron GX](#victron-gx) | VE.Bus oder Netzzähler über D-Bus | Python / Venus OS | HTTPS | Victron GX-Geräte |
| [Volkszähler](#volkszähler) | Volkszähler-Middleware | Python / cron | HTTPS | Smart Meter mit Volkszähler |
| [KOSTAL KSEM](#kostal-ksem) | KOSTAL Smart Energy Meter | Node-RED / Modbus | HTTPS | KSEM mit Node-RED |
| [openHAB](#openhab) | Vorhandene Smart-Meter-Items | openHAB 4+ / JavaScript | HTTPS | openHAB-Installationen |
| [Fronius](#fronius) | Fronius Smart Meter über die Solar API | Python / cron | HTTPS | Fronius-Wechselrichter mit Smart Meter |
| [Siemens PAC Energiemessgeräte](#siemens-pac-energiemessgerate) | REST-API des Messgeräts | Node.js / Docker | HTTPS | Siemens PAC 4200/4220 und ähnliche Energiemessgeräte |
| [SAX Power Smartmeter](#sax-power-smartmeter) | SAX Smartmeter über Modbus TCP | Python / systemd | HTTPS | SAX Power Home und Home Plus mit Smartmeter |
| [USV mit NUT](#usv-mit-nut) | USV-Eingangsspannung über NUT | Shell / cron | HTTPS | NUT-kompatible einphasige USVs |
| [WeeWX](#weewx) | Vorhandene Sensoren | Python / systemd | HTTPS | WeeWX mit Zusatzmodul

## Shelly Pro 3EM und Pro EM50

Skripte für Shelly Pro 3EM, Pro 3EM-400 und Pro EM50. Sie senden sofort nach dem Start und danach alle fünf Minuten. Der einphasige Pro EM50 kennzeichnet nicht vorhandene L2/L3-Phasen mit `-1`; die API akzeptiert diese Werte.

- Ordner: [`shelly-ortsnetz-auslastung`](shelly-ortsnetz-auslastung)
- Voraussetzungen: unterstütztes Shelly-Gerät, Shelly Scripting, NTP und Internetzugang
- Skripte: [`pro-3EM-ortsnetz-auslastung.js`](shelly-ortsnetz-auslastung/pro-3EM-ortsnetz-auslastung.js) und [`pro-EM50-ortsnetz-auslastung.js`](shelly-ortsnetz-auslastung/pro-EM50-ortsnetz-auslastung.js)
- Anleitung: [Shelly-README](shelly-ortsnetz-auslastung/README.md)

Vor dem Aktivieren Breitengrad und Längengrad konfigurieren.

## SMA Sunny Home Manager 2.0 und Energy Meter

Das Python-Script empfängt die Speedwire-Multicast-Telegramme des Sunny Home Manager 2.0 oder SMA Energy Meter direkt aus dem lokalen Netz und dekodiert L1, L2, L3 sowie die Netzfrequenz, sofern vorhanden. Es läuft auf einem dauerhaft eingeschalteten Rechner und benötigt keinen Sunny-Portal-Zugang zum Auslesen.

- Ordner: [`sma-shm2-ortsnetz-auslastung`](sma-shm2-ortsnetz-auslastung)
- Script: [`ortsnetz-sma-shm2.py`](sma-shm2-ortsnetz-auslastung/ortsnetz-sma-shm2.py)
- Voraussetzungen: Linux-Rechner mit Python ab 3.8 im selben Layer-2-Netz wie der Zähler und Internetzugang

Ohne eigens eingerichtete Weiterleitung bleibt Multicast im lokalen Netz; bei mehreren Interfaces die Interface-IP im Zähler-Netz konfigurieren. Empfang zuerst mit `--dry-run` prüfen. Details stehen in der [SMA-README](sma-shm2-ortsnetz-auslastung/README.md).

## Tasmota SML-Lesekopf

Ein ESP32 mit optischem Lesekopf dekodiert SML-Telegramme des Stromzählers und sendet L1, L2, L3 sowie optional die Frequenz per WebQuery.

- Ordner: [`tasmota-ortsnetz-auslastung`](tasmota-ortsnetz-auslastung)
- Voraussetzungen: ESP32 für HTTPS, Tasmota mit `USE_SCRIPT` und `USE_SML_M` sowie eine freigeschaltete Info-Schnittstelle des Zählers
- Anleitung: [Tasmota-README](tasmota-ortsnetz-auslastung/README.md)

GPIO, Baudrate und OBIS-Codes hängen vom Zählermodell ab.

## Home Assistant

Die HACS-Integration überträgt drei ausgewählte Spannungssensoren sowie optional Frequenz- und PV-Daten.

- Repository: [ha_ortsnetz_auslastung](https://github.com/thomaslehmann1234/ha_ortsnetz_auslastung)
- Voraussetzungen: Home Assistant und HACS

## ioBroker

Das Script für den JavaScript-Adapter liest drei konfigurierte Spannungsdatenpunkte und optional die Frequenz.

- Ordner: [`iobroker-ortsnetz-auslastung`](iobroker-ortsnetz-auslastung)
- Voraussetzung: `ioBroker.javascript` ab Version 7.9
- Anleitung: [ioBroker-README](iobroker-ortsnetz-auslastung/README.md)

Das Script verwendet den eingebauten Helfer `httpPost` und benötigt keine zusätzliche npm-Abhängigkeit.

## MQTT

Ein eigenständiges Node.js-Script abonniert drei Spannungs-Topics und optional ein Frequenz-Topic auf einem MQTT-Broker. Es unterstützt außerdem eine PV-Tagesprognose, zum Beispiel von evcc, und überträgt die Messwerte nach einem ersten Upload alle fünf Minuten per HTTPS.

- Ordner: [`mqtt-ortsnetz-auslastung`](mqtt-ortsnetz-auslastung)
- Messquelle: Smart-Meter-Gateways oder andere Systeme mit MQTT-Topics für L1/L2/L3
- Voraussetzung: Node.js ab Version 24 oder Docker, erreichbarer MQTT-Broker und Internetzugang

Die Konfiguration erfolgt im `CONFIG`-Block des Scripts. Unterstützt werden numerische Payloads sowie JSON-Payloads mit konfigurierbarem Schlüssel. Details stehen in der [MQTT-README](mqtt-ortsnetz-auslastung/README.md).

## evcc

Die evcc-Integration nutzt die gleiche direkte Messquelle wie evcc: Shelly Gen2/3 EM per RPC oder einen Modbus-TCP-Zähler. Das Python-Script wird von evcc alle fünf Minuten gestartet und überträgt L1 bis L3 sowie optional Frequenz, PV-Daten und Zähler-Modell.

- Ordner: [`evcc-ortsnetz-auslastung`](evcc-ortsnetz-auslastung)
- Script: [`ortsnetz_evcc.py`](evcc-ortsnetz-auslastung/ortsnetz_evcc.py)
- Voraussetzungen: Python ab 3.8, cron sowie Zugriff auf Shelly oder Modbus TCP

Konfiguration und Start stehen in der [evcc-README](evcc-ortsnetz-auslastung/README.md).

## Victron GX

Das Python-Script läuft direkt auf Venus OS und liest Netzspannungen über den lokalen D-Bus. Es bevorzugt den Victron-Netzzähler und verwendet andernfalls VE.Bus.

- Ordner: [`victron-gx-ortsnetz-auslastung`](victron-gx-ortsnetz-auslastung)
- Script: [`ortsnetz-victron-gx.py`](victron-gx-ortsnetz-auslastung/ortsnetz-victron-gx.py)
- Voraussetzungen: Victron GX mit Venus OS, VE.Bus-Gerät oder Netzzähler, SSH-Zugang und Internetzugang

Installation, Konfiguration und Autostart stehen in der [Victron-GX-README](victron-gx-ortsnetz-auslastung/README.md).

## Volkszähler

Das Python-Script liest die Phasenspannungen aus der lokalen Volkszähler-Middleware und wird alle fünf Minuten per cron ausgeführt. Optional werden Netzfrequenz, installierte PV-Leistung, PV-Tagesprognose und das Zählermodell übertragen.

- Ordner: [`volkszaehler-ortsnetz-auslastung`](volkszaehler-ortsnetz-auslastung)
- Script: [`ortsnetz_auslastung.py`](volkszaehler-ortsnetz-auslastung/ortsnetz_auslastung.py)
- Voraussetzungen: Linux mit Python ab 3.8, cron, lokale Volkszähler-Middleware und ein Smart Meter mit Spannungswerten

Installation und die Zuordnung der Volkszähler-Kanäle stehen in der [Volkszähler-README](volkszaehler-ortsnetz-auslastung/readme.md).

## KOSTAL KSEM

Die KSEM-Integration ist ein importierbarer Node-RED-Flow. Sie liest L1, L2, L3 und Frequenz über Modbus, baut den API-Payload und wertet die API-Antwort aus.

- Ordner: [`kesm-ortsnetz-auslastung`](kesm-ortsnetz-auslastung)
- Flow: [`kesm.js`](kesm-ortsnetz-auslastung/kesm.js)
- Voraussetzungen: Node-RED mit Modbus- und buffer-parser-Nodes sowie Modbus-Zugriff auf den KSEM

Vor der Bereitstellung Modbus-Server und Beispielkoordinaten in der Payload-Funktion anpassen. Der mitgelieferte Flow liest und sendet alle fünf Minuten.

## openHAB

Die openHAB-Datenerfassung wird in einem separaten Repository gepflegt. Sie liest konfigurierte Smart-Meter-Items und überträgt die Spannungswerte alle fünf Minuten.

- Repository: [Caddy-SRX/Openhab-datenerfassung-ortsnetz-auslastung](https://github.com/Caddy-SRX/Openhab-datenerfassung-ortsnetz-auslastung)
- Voraussetzungen: openHAB ab Version 4, JavaScript Scripting (GraalVM) und JSONPath

Installation und Konfiguration stehen in der [openHAB-README](https://github.com/Caddy-SRX/Openhab-datenerfassung-ortsnetz-auslastung#readme).

## Fronius

Das Python-Script liest die Phasenspannungen und die Netzfrequenz des Fronius Smart Meters am Netzeinspeisepunkt über die lokale Solar API des Wechselrichters und wird alle fünf Minuten per cron ausgeführt. Das Zählermodell wird aus der Solar API übernommen, optional wird die installierte PV-Leistung übertragen.

- Ordner: [`fronius-ortsnetz-auslastung`](fronius-ortsnetz-auslastung)
- Script: [`ortsnetz_fronius.py`](fronius-ortsnetz-auslastung/ortsnetz_fronius.py)
- Voraussetzungen: Fronius-Wechselrichter mit Fronius Smart Meter am Netzeinspeisepunkt, aktivierte Solar API, Linux mit Python ab 3.8, cron und Internetzugang

Aktivierung der Solar API, Konfiguration und cron-Eintrag stehen in der [Fronius-README](fronius-ortsnetz-auslastung/README.md).

## Siemens PAC Energiemessgeräte

Das Node.js-Script liest die Phasenspannungen und die Netzfrequenz über die lokale REST API des Messgeräts und wird alle fünf Minuten ausgeführt. Es erkennt automatisch das API-Format (`data.json` mit `type=INST_VALUES` oder `/api-webserver/values/base`) sowie den Zählernamen. Konfiguration erfolgt über Umgebungsvariablen; einphasige Geräte werden mit `-1` für nicht vorhandene Phasen unterstützt.

- Ordner: [`siemens-pac-ortsnetz-auslastung`](siemens-pac-ortsnetz-auslastung)
- Script: [`ortsnetz-siemens-pac.js`](siemens-pac-ortsnetz-auslastung/ortsnetz-siemens-pac.js)
- Voraussetzungen: Siemens-Messgerät mit REST-API, Node.js ab 18 oder Docker und Internetzugang

Installation und Umgebungsvariablen stehen in der [Siemens-README](siemens-pac-ortsnetz-auslastung/README.md).

## SAX Power Smartmeter

Das Python-Script liest die Phasenspannungen und die Netzfrequenz des SAX-Smartmeters (SunSpec Model 203) per Modbus TCP vom SAX-Master und sendet sofort nach dem Start und danach alle fünf Minuten. Nicht plausible Phasen werden mit `-1` gesendet; Zählernummern und Energiezähler werden nicht gelesen. Mit `--simulate` lässt sich das Script ohne Zähler testen.

- Ordner: [`sax-ortsnetz-auslastung`](sax-ortsnetz-auslastung)
- Script: [`sax_ortsnetz_auslastung.py`](sax-ortsnetz-auslastung/sax_ortsnetz_auslastung.py)
- Voraussetzungen: SAX Power Home oder Home Plus mit Smartmeter und aktiviertem Modbus TCP, Python ab 3.8 mit `pyModbusTCP` und Internetzugang

Installation, Konfiguration und systemd-Beispiel stehen in der [SAX-README](sax-ortsnetz-auslastung/README.md).

## USV mit NUT

Das Shell-Script liest die Eingangsspannung einer über NUT eingebundenen einphasigen USV aus. Es überträgt nur bei Netzbetrieb (`OL`), damit keine Werte aus dem Batteriebetrieb als Netzspannung gemeldet werden. L2 und L3 werden als `-1` gesendet.

- Ordner: [`ups-ortsnetz-auslastung`](ups-ortsnetz-auslastung)
- Script: [`ortsnetz-ups.sh`](ups-ortsnetz-auslastung/ortsnetz-ups.sh)
- Voraussetzungen: NUT mit `upsc`, `curl`, Shell-Zugang, cron und Internetzugang

Installation, Konfiguration und der Cron-Eintrag stehen in der [NUT-USV-Anleitung](ups-ortsnetz-auslastung/ortsnetz_ups.md).

## WeeWX

- Ordner: [`weewx-ortsnetz-auslastung`](weewx-ortsnetz-auslastung)
- Voraussetzungen: Installation von WeeWX und eines WeeWX-Zusatzmoduls zur Abfrage des Umrichters

Installation und Konfiguration stehen in der [WeeWX-README](weewx-ortsnetz-auslastung/README.md).

## Gemeinsame Eigenschaften

- Übertragungsintervall: integrationsabhängig, die meisten Skripte verwenden fünf Minuten
- Pflichtfelder: Zeitstempel, Standort und Spannungswerte; einphasige Messungen verwenden für nicht vorhandene L2/L3-Phasen `-1`
- Optionale Felder: Netzfrequenz, PV-Leistung, PV-Prognose, Zählermodell und Kennung der Integration
- Keine Übertragung von Zählernummern, Gerätekennungen, Energiezählern oder IP-Adressen

## API

Die vollständige Request- und Response-Referenz steht in [API.md](API.md).

```text
POST https://www.ortsnetz-auslastung.de/v1/measurements
Content-Type: application/json
```

Bei erfolgreicher Annahme liefert der Service `202 Accepted`.

## Koordinaten

Koordinaten lassen sich über [OpenStreetMap](https://www.openstreetmap.org/) bestimmen: Ort suchen, mit der rechten Maustaste auf die Karte klicken und **„Abfrage starten“** auswählen.
