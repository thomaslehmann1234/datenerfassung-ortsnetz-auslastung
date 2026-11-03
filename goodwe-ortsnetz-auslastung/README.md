# GoodWe → Ortsnetz-Auslastung

Python-Script, das die Phasenspannungen, die Netzfrequenz und weitere Messwerte des GoodWe Smart Meters am Netzanschlusspunkt über die Modbus-TCP-Schnittstelle eines GoodWe-Hybridwechselrichters liest und an [ortsnetz-auslastung.de](https://www.ortsnetz-auslastung.de) überträgt. Optional werden die installierte PV-Leistung und die Batteriekapazität mitgesendet.

Das Script wird per cron gestartet und führt pro Aufruf genau eine Messung und Übertragung aus. Es greift ausschließlich lesend auf den Wechselrichter zu (Modbus-Funktion 03).

## Funktionsweise

1. Das Script verbindet sich per Modbus TCP mit dem Wechselrichter (`GOODWE_HOST:GOODWE_PORT`, Unit-ID `GOODWE_UNIT_ID`).
2. Es liest den Smart-Meter-Block ab Register `36000`:

| Register | Inhalt | Skalierung | API-Feld |
|---|---|---|---|
| 36004 | Kommunikationsstatus des Smart Meters, `1` = in Ordnung | – | – |
| 36052–36054 | Spannung L1–L3 | 0,1 V | `l1_v`, `l2_v`, `l3_v` |
| 36055–36057 | Strom L1–L3 | 0,1 A | `l1_a`, `l2_a`, `l3_a` |
| 36014 | Netzfrequenz | 0,01 Hz | `grid_frequency_hz` |
| 36025–36026 | Gesamtwirkleistung, int32, GoodWe: Einspeisung positiv | 1 W | `grid_power_w` (Vorzeichen umgekehrt) |
| 36041–36042 | Gesamtscheinleistung, int32 | 1 VA | `apparent_power_va` (Betrag) |
| 37007 | Ladezustand der Batterie | 1 % | `battery_soc_percent` |

3. Die Werte werden geprüft:
	- Spannungen: größer 0 V und höchstens 500 V
	- Netzfrequenz: 45 Hz bis 55 Hz, sonst wird sie weggelassen
	- Leistungsfaktor: wird als `abs(P) / S` berechnet und nur gesendet, wenn die Scheinleistung größer 0 ist
	- Batterie-SOC: wird nur gesendet, wenn eine Batterie erkannt wird (Batteriespannung in Register `35180` größer 0)
4. Als `observed_at` wird die Systemzeit in UTC verwendet. Die Uhr des Rechners muss per NTP gestellt sein.
5. Die Messung wird per `POST` an `https://www.ortsnetz-auslastung.de/v1/measurements` gesendet. Die Antwort der API wird ins Log geschrieben.

Kommuniziert der Smart Meter nicht mit dem Wechselrichter oder fehlt die L1-Spannung, wird nichts gesendet. Liefert der Zähler weder für L2 noch für L3 gültige Werte, zum Beispiel ein einphasiger Smart Meter, werden L2 und L3 sowie die zugehörigen Ströme mit `-1` übertragen. Ist nur eine der beiden Phasen ungültig, wird ebenfalls nichts gesendet.

### Messquelle Wechselrichter

Ältere Firmwarestände liefern die Zählerspannungen in den Registern `36052` bis `36054` nicht. Das Script bricht dann mit einem Hinweis ab. Statt eines Firmware-Updates kann mit `GOODWE_QUELLE = "wechselrichter"` auf die Spannungen an den AC-Klemmen des Wechselrichters (Register `35121`, `35126`, `35131`, Frequenz `35123`) ausgewichen werden.

Diese Werte stammen nicht vom Netzanschlusspunkt: Bei Einspeisung liegen sie durch den Spannungsfall auf der Zuleitung etwas höher. In diesem Modus werden keine Ströme und Leistungen übertragen, weil die Wechselrichterwerte nicht die Werte des Hausanschlusses sind. Als `smartmeter_model` wird dann das Wechselrichtermodell aus den Registern `35011` bis `35015` gesendet, zum Beispiel `GoodWe GW10KN-ET`.

## Voraussetzungen

- GoodWe-Hybridwechselrichter der ET-Plattform, zum Beispiel GW5K-ET bis GW10K-ET, GW…KN-ET, EH, BT oder BH
- GoodWe Smart Meter am Netzanschlusspunkt, zum Beispiel GM3000
- Modbus TCP am Wechselrichter erreichbar, Port 502. Das ist bei Geräten mit LAN-Anschluss oder einem aktuellen WLAN/LAN-Kit der Fall; ältere WLAN-Sticks sprechen nur das UDP-Protokoll auf Port 8899 und werden nicht unterstützt
- Linux-Rechner im selben Netz, zum Beispiel ein Raspberry Pi, mit cron und Internetzugang
- Python ab 3.8 (nur Standardbibliothek, keine zusätzlichen Pakete)

Wechselrichter der DT-, MS- und XS-Serie verwenden eine andere Registerbelegung und werden von diesem Script nicht unterstützt.

## Installation

```bash
sudo mkdir -p /opt/ortsnetz-goodwe
sudo cp ortsnetz_goodwe.py /opt/ortsnetz-goodwe/
sudo chmod +x /opt/ortsnetz-goodwe/ortsnetz_goodwe.py
```

## Konfiguration

Im Konfigurationsblock am Anfang des Scripts:

| Variable | Pflicht | Bedeutung |
|---|---|---|
| `GOODWE_HOST` | ja | IP-Adresse oder Hostname des Wechselrichters |
| `GOODWE_PORT` | – | Modbus-TCP-Port, Standard `502` |
| `GOODWE_UNIT_ID` | – | Modbus Unit-ID, Standard `247` |
| `GOODWE_QUELLE` | – | `meter` (Standard) oder `wechselrichter`, siehe oben |
| `LATITUDE`, `LONGITUDE` | ja | Ungefährer Standort in Dezimalgrad, z. B. `52.52` und `13.40`. Sind sie nicht gesetzt, bricht das Script ab |
| `PLANT_CAPACITY_KWP` | – | Installierte PV-Leistung in kWp (größer 0, höchstens 1000), `None` = nicht senden |
| `BATTERY_CAPACITY_KWH` | – | Nutzbare Batteriekapazität in kWh (größer 0), `None` = nicht senden |
| `SMARTMETER_MODEL` | – | Hersteller und Modell des Zählers, z. B. `GoodWe GM3000`. `None` = `GoodWe Smart Meter` |
| `API_URL` | – | Endpunkt der Ortsnetz-Auslastung-API |
| `INTEGRATION_VERSION` | – | Kennung dieser Integration |

Zahlen werden mit Punkt als Dezimaltrennzeichen und ohne Anführungszeichen eingetragen. Das genaue Zählermodell lässt sich nicht zuverlässig per Modbus auslesen und kann daher über `SMARTMETER_MODEL` angegeben werden.

### Konfiguration per Environment-Variablen

Alle Variablen außer `API_URL` und `INTEGRATION_VERSION` können statt im Script auch als gleichnamige Environment-Variablen gesetzt werden. Gesetzte Variablen haben Vorrang vor den Werten im Script, leere Variablen werden ignoriert. So bleibt das Script unverändert und lässt sich bei einem Update einfach ersetzen.

```bash
GOODWE_HOST=<IP-des-Wechselrichters> LATITUDE=52.52 LONGITUDE=13.40 PLANT_CAPACITY_KWP=9.8 /opt/ortsnetz-goodwe/ortsnetz_goodwe.py --dry-run
```

Ein ungültiger Wert, zum Beispiel `LATITUDE=abc`, führt zum Abbruch mit einer Fehlermeldung.

## Test

```bash
/opt/ortsnetz-goodwe/ortsnetz_goodwe.py --dry-run
```

Mit `--dry-run` werden die Werte abgerufen, geprüft und als Payload ausgegeben, aber nicht gesendet. Beispiel von einem GW10KN-ET mit Batterie bei rund 400 W Netzbezug, `grid_power_w` ist daher positiv:

```json
{
	"observed_at": "2026-10-28T06:00:50Z",
	"latitude": 52.52,
	"longitude": 13.4,
	"l1_v": 228.9,
	"l2_v": 229.8,
	"l3_v": 230.2,
	"integration_version": "goodwe-0.1.0",
	"grid_frequency_hz": 50.01,
	"grid_power_w": 393.0,
	"apparent_power_va": 825.0,
	"power_factor": 0.476,
	"l1_a": 1.8,
	"l2_a": 0.9,
	"l3_a": 0.8,
	"battery_soc_percent": 10.0,
	"smartmeter_model": "GoodWe Smart Meter"
}
```

Die Unit-Tests laufen ohne Wechselrichter:

```bash
python3 test_ortsnetz_goodwe.py
```

## Betrieb per cron

```bash
crontab -e
```

```
*/5 * * * * /usr/bin/python3 /opt/ortsnetz-goodwe/ortsnetz_goodwe.py >> $HOME/ortsnetz-goodwe.log 2>&1
```

Das Script läuft alle fünf Minuten.

Mit Konfiguration per Environment-Variablen werden die Variablen vor den Aufruf gesetzt:

```
*/5 * * * * GOODWE_HOST=<IP-des-Wechselrichters> LATITUDE=52.52 LONGITUDE=13.40 /usr/bin/python3 /opt/ortsnetz-goodwe/ortsnetz_goodwe.py >> $HOME/ortsnetz-goodwe.log 2>&1
```

Manche GoodWe-Wechselrichter erlauben nur wenige gleichzeitige Modbus-TCP-Verbindungen. Das Script hält die Verbindung nur für die Dauer einer Abfrage offen und versucht einen fehlgeschlagenen Verbindungsaufbau nach zwei Sekunden ein zweites Mal.

## Übertragene Daten

Übertragen werden nur:

- Zeitstempel der Messung
- Breiten- und Längengrad aus der Konfiguration
- Spannungen und Ströme L1, L2 und L3 sowie die Netzfrequenz
- Wirkleistung, Scheinleistung und Leistungsfaktor am Netzanschlusspunkt
- Ladezustand der Batterie, sofern vorhanden
- Zählermodell, Kennung der Integration
- optional die installierte PV-Leistung und die Batteriekapazität aus der Konfiguration

Nicht übertragen werden insbesondere:

- Seriennummer des Wechselrichters (Register `35003` bis `35010`)
- Energiezählerstände
- PV-, Batterie- und Wechselrichterleistungen
- IP-Adresse und Port des Wechselrichters

## Log und Fehler

Bei erfolgreicher Übertragung erscheint eine Zeile mit den Messwerten und der Antwort der API:

```
2026-10-28 07:00:51 Übertragen (2026-10-28T06:00:50Z): L1=228.9 L2=229.8 L3=230.2 f=50.01 P=393.0 | HTTP 202: {"accepted":true,...}
```

Bei Fehlern endet das Script mit Exit-Code 1 und einer Meldung, die mit `FEHLER:` beginnt:

| Meldung | Ursache |
|---|---|
| `… ist nicht gesetzt` / `… müssen als Zahl gesetzt sein` / `… muss …` | Pflichtwert in der Konfiguration fehlt oder liegt außerhalb des gültigen Bereichs |
| `Environment-Variable … ist ungültig` | Eine Environment-Variable lässt sich nicht als Zahl lesen |
| `Verbindung zu … fehlgeschlagen` | Wechselrichter nicht erreichbar, falsche IP-Adresse oder Modbus TCP nicht verfügbar |
| `Modbus-Fehler …` | Der Wechselrichter kennt die Register nicht, zum Beispiel bei einem Modell außerhalb der ET-Plattform oder falscher Unit-ID |
| `Der Smart Meter kommuniziert nicht` | Smart Meter nicht angeschlossen oder RS485-Verbindung gestört |
| `… keine Zählerspannungen` | Firmware zu alt, siehe [Messquelle Wechselrichter](#messquelle-wechselrichter) |
| `L1: keine gültige Spannung` | Der Zähler liefert keine plausible L1-Spannung |
| `L2/L3: nur eine Phase …` | Bei einem dreiphasigen Zähler fehlt eine Phase oder liefert einen unplausiblen Wert |
| `403` | Der Standort ist für die Annahme gesperrt |
| `422` | Payload von der API abgelehnt, die Antwort nennt das betroffene Feld |

## Weitere Informationen

- API-Beschreibung und weitere Integrationen: [datenerfassung-ortsnetz-auslastung](https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung)
- Registerbelegung der ET-Plattform: [goodwe-Python-Bibliothek](https://github.com/marcelblijleven/goodwe/blob/master/goodwe/et.py)
