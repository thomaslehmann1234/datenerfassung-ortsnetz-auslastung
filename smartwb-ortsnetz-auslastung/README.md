# smartWB → Ortsnetz-Auslastung

Python-Script, das die Phasenspannungen einer **smartWB / EVSE-WiFi 2.0** Wallbox über deren lokale HTTP-API liest und an [ortsnetz-auslastung.de](https://www.ortsnetz-auslastung.de) überträgt. Optional wird die installierte PV-Leistung mitgesendet.

Das Script führt pro Aufruf genau eine Messung und Übertragung aus und wird per cron oder systemd-Timer alle fünf Minuten gestartet.

## Funktionsweise

1. Die Wallbox wird mit einer Anfrage abgefragt:
```
	http://<SMARTWB_HOST>/getParameters
```
2. Aus der Antwort (`list[0]`) werden `voltageP1`, `voltageP2` und `voltageP3` gelesen. Die Spannungen sind unabhängig davon vorhanden, ob ein Fahrzeug angeschlossen ist.
3. Die Werte werden geprüft: Spannungen müssen zwischen 150 V und 300 V liegen.
4. Die Wallbox liefert keinen Zeitstempel, `observed_at` ist daher die Systemzeit (UTC). Die Uhrzeit des Rechners muss stimmen (NTP).
5. Die Messung wird per `POST` an `https://www.ortsnetz-auslastung.de/v1/measurements` gesendet. Die Antwort der API wird ins Log geschrieben.

Ist die L1-Spannung nicht plausibel, wird nichts gesendet. Liefert die Wallbox weder für L2 noch für L3 eine plausible Spannung, zum Beispiel bei einer einphasigen Wallbox, werden L2 und L3 mit `-1` übertragen. Ist nur eine der beiden Phasen unplausibel, wird ebenfalls nichts gesendet. Die Wallbox liefert keine Netzfrequenz, daher wird `grid_frequency_hz` nicht übertragen.

## Voraussetzungen

- smartWB bzw. EVSE-WiFi 2.0 Wallbox mit konfiguriertem Stromzähler (`useMeter` = `true`), siehe [API-Dokumentation](https://www.evse-wifi.de)
- **Die Wallbox ist im Heimnetz (WLAN/LAN) erreichbar und ihre IP-Adresse ist bekannt.** `192.168.4.1` gilt nur im Access-Point-Modus der Wallbox und funktioniert im Normalbetrieb nicht. Am besten im Router eine feste IP für die Wallbox vergeben.
- **Die API ist in den Einstellungen der Wallbox aktiviert.** Ist sie deaktiviert, antwortet `/getParameters` nicht.
- **Wallbox nicht im Remote-Modus.** Die Integration ruft nur `/getParameters` ab, ein reiner Lese-Aufruf. Im Remote-Modus (`opMode` = `remote`, siehe `/evseHost`) ist nicht geprüft, ob der Abruf das Verhalten einer fernsteuernden Software beeinflusst (zum Beispiel Heartbeat oder Zeitüberwachung der Firmware). Die Integration daher nur bei `opMode` = `normal` oder `alwaysActive` einsetzen. Getestet wurde mit Firmware 2.4.2 im Modus `normal`.
- Linux-Rechner im selben Netz, zum Beispiel ein Raspberry Pi, mit cron oder systemd und Internetzugang
- Python ab 3.8 (nur Standardbibliothek, keine zusätzlichen Pakete)
- Korrekte Systemzeit (NTP)

### Test im Browser oder mit curl

```bash
curl http://<IP-der-Wallbox>/getParameters
```

Relevant für das Script (gekürzt):

```json
{
	"type": "parameters",
	"list": [
		{
			"voltageP1": 228.28,
			"voltageP2": 231.85,
			"voltageP3": 232.07,
			"useMeter": true
		}
	]
}
```

Erscheint keine Antwort, ist die IP falsch oder die API in der Wallbox deaktiviert.

### Hinweis zum Messort

Die Wallbox misst hinter der Hausverteilung am Abgang der Wallbox, nicht am Netzanschlusspunkt. Die Genauigkeit entspricht dem internen Zähler der Wallbox. Die Werte spiegeln die Netzspannung am Standort der Wallbox wider.

## Installation

```bash
sudo install -d -o root -g root -m 755 /opt/ortsnetz-smartwb
sudo install -o root -g root -m 755 ortsnetz_smartwb.py /opt/ortsnetz-smartwb/
```

Script und Ordner gehören bewusst `root` und sind für normale Benutzer nicht beschreibbar. Das ist wichtig, weil der systemd-Dienst das Script ausführt: Ein beschreibbares Script könnte sonst von jedem, der es ändern kann, mit den Rechten des Dienstes ausgeführt werden. Für `--dry-run` und Tests genügt ein Aufruf als normaler Benutzer (`python3 /opt/ortsnetz-smartwb/ortsnetz_smartwb.py --dry-run`).

## Konfiguration

Die Konfiguration steht im Block am Anfang von `ortsnetz_smartwb.py` oder wird per Environment-Variablen gesetzt (siehe unten).

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `SMARTWB_HOST` | ja | IP-Adresse oder Hostname der Wallbox im Heimnetz, optional mit Port. Ist sie nicht gesetzt, bricht das Script ab |
| `LATITUDE`, `LONGITUDE` | ja | Ungefährer Standort in Dezimalgrad, z. B. `52.52` und `13.40`. Sind sie nicht gesetzt, bricht das Script ab |
| `PLANT_CAPACITY_KWP` | – | Installierte PV-Leistung in kWp (größer 0, höchstens 1000), `None` = nicht senden |
| `API_URL` | – | Endpunkt der Ortsnetz-Auslastung-API (nur im Script) |
| `INTEGRATION_VERSION` | – | Kennung dieser Integration (nur im Script) |

Zahlen werden mit Punkt als Dezimaltrennzeichen und ohne Anführungszeichen eingetragen.

### Konfiguration per Environment-Variablen

`SMARTWB_HOST`, `LATITUDE`, `LONGITUDE` und `PLANT_CAPACITY_KWP` können statt im Script auch als gleichnamige Environment-Variablen gesetzt werden. Gesetzte Variablen haben Vorrang vor den Werten im Script, leere Variablen werden ignoriert. So bleibt das Script unverändert und lässt sich bei einem Update einfach ersetzen.

```bash
SMARTWB_HOST=192.168.1.50 LATITUDE=52.52 LONGITUDE=13.40 /opt/ortsnetz-smartwb/ortsnetz_smartwb.py --dry-run
```

## Test

```bash
/opt/ortsnetz-smartwb/ortsnetz_smartwb.py --dry-run
```

Mit `--dry-run` werden die Werte abgerufen, geprüft und als Payload ausgegeben, aber nicht gesendet:

```json
{
	"observed_at": "2026-10-12T08:00:00Z",
	"latitude": 52.52,
	"longitude": 13.4,
	"l1_v": 228.28,
	"l2_v": 231.85,
	"l3_v": 232.07,
	"smartmeter_model": "smartWB",
	"integration_version": "smartwb-0.1.0"
}
```

Die Unit-Tests laufen ohne Wallbox: `python3 test_smartwb.py`

## Betrieb per cron

```bash
crontab -e
```

```
*/5 * * * * SMARTWB_HOST=192.168.1.50 LATITUDE=52.52 LONGITUDE=13.40 /usr/bin/timeout 60 /usr/bin/python3 /opt/ortsnetz-smartwb/ortsnetz_smartwb.py >> $HOME/ortsnetz-smartwb.log 2>&1
```

Das Script läuft alle fünf Minuten. Die API erwartet pro Messquelle ein Sendeintervall von 300 Sekunden, das Intervall also nicht verkürzen. `timeout 60` beendet einen hängenden Lauf nach 60 Sekunden, damit sich bei einer nicht antwortenden Wallbox keine Prozesse ansammeln. Zusätzlich bricht das Script selbst nach 60 Sekunden ab (`MAX_LAUFZEIT_S`). Alternativ stehen die Variablen als eigene Zeilen über dem Eintrag in der Crontab, zum Beispiel `LATITUDE=52.52`. Das cron-Beispiel gehört in die Crontab eines normalen, unprivilegierten Benutzers, nicht in die von root.

## Betrieb per systemd-Timer

Der Timer ersetzt cron: Er startet das Script alle fünf Minuten als `oneshot`-Service. Die Logs landen im Journal. Das Script läuft nicht dauerhaft als Prozess.

```bash
sudo cp systemd/ortsnetz-smartwb.service systemd/ortsnetz-smartwb.timer /etc/systemd/system/
sudo cp systemd/ortsnetz-smartwb.env.example /etc/ortsnetz-smartwb.env
sudo nano /etc/ortsnetz-smartwb.env     # SMARTWB_HOST, LATITUDE, LONGITUDE anpassen
sudo systemctl daemon-reload
sudo systemctl enable --now ortsnetz-smartwb.timer
```

Der Dienst läuft mit `DynamicUser=yes` als unprivilegierter, temporärer Benutzer und nicht als root. `TimeoutStartSec=60s` begrenzt die Laufzeit einer Messung. Pfade bei Bedarf an die eigene Installation anpassen. Ein anderer fester Benutzer ist über `User=` möglich, das Script bleibt dann trotzdem `root`-eigen.

Kontrolle:

```bash
systemctl list-timers ortsnetz-smartwb.timer
sudo systemctl start ortsnetz-smartwb.service   # sofort eine Messung auslösen
journalctl -u ortsnetz-smartwb.service -n 20
```

Nur einen der beiden Wege (cron **oder** systemd-Timer) einrichten, sonst wird doppelt gesendet.

## Übertragene Daten

Übertragen werden nur:

- Zeitstempel der Messung (Systemzeit)
- Breiten- und Längengrad aus der Konfiguration
- Spannungen L1, L2 und L3
- Zählermodell `smartWB`
- Kennung der Integration
- optional die installierte PV-Leistung aus der Konfiguration

Nicht übertragen werden insbesondere:

- IP-Adresse und Port der Wallbox
- Ströme, Leistung, Zählerstand und Ladedaten (`currentP*`, `actualPower`, `energy`, `meterReading`)
- RFID-Kennungen und Benutzernamen (`RFIDUID`, `lastActionUser`)
- MAC-Adresse und weitere Netzwerkdaten (`/evseHost`)

## Log und Fehler

Bei erfolgreicher Übertragung erscheint eine Zeile mit den Messwerten und der Antwort der API:

```
2026-10-12 10:00:01 Übertragen (2026-10-12T08:00:00Z): L1=228.28 L2=231.85 L3=232.07 | HTTP 202: {"accepted":true,"created":true,"status":{"l1":"green","l2":"green","l3":"green","overall":"green"},"storage_recommendation":"none"}
```

Bei Fehlern endet das Script mit Exit-Code 1 und einer Meldung, die mit `FEHLER:` beginnt:

| Meldung | Ursache |
|---|---|
| `… ist nicht gesetzt` / `… müssen als Zahl gesetzt sein` / `… muss …` | Pflichtwert in der Konfiguration fehlt oder liegt außerhalb des gültigen Bereichs |
| `Environment-Variable … ist ungültig` | Eine Environment-Variable lässt sich nicht als Zahl lesen |
| `Maximale Laufzeit von 60 s überschritten` | Die Wallbox oder die API antwortet nur sehr langsam, Netzwerk und Wallbox prüfen |
| `Abruf von … fehlgeschlagen` | Wallbox nicht erreichbar, falsche IP, API in der Wallbox deaktiviert oder Antwort kein gültiges JSON |
| `Antwort der Wallbox hat ein unerwartetes Format` | Die Antwort enthält kein `list[0]`, Firmware prüfen |
| `L1: keine plausible Spannung` | `voltageP1` fehlt oder liegt außerhalb von 150 bis 300 V, Stromzähler der Wallbox prüfen |
| `L2/L3: nur eine Phase …` | Bei dreiphasiger Wallbox fehlt eine Phase oder liefert einen unplausiblen Wert |
| `403` | Der Standort ist für die Annahme gesperrt |
| `422` | Payload von der API abgelehnt, die Antwort nennt das betroffene Feld |

## Weitere Informationen

- API-Beschreibung und weitere Integrationen: [datenerfassung-ortsnetz-auslastung](https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung)
- API der Wallbox: [EVSE-WiFi.de](https://www.evse-wifi.de)
