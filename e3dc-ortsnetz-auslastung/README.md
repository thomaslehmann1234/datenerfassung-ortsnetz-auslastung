# E3/DC Ortsnetz-Auslastung Integration

Dieses Python-Skript liest die Phasenspannungen (L1, L2, L3), die Netzfrequenz, die Netzleistung am Hausanschluss und den Ladezustand des Speichers lokal über das RSCP-Protokoll von einem E3/DC-Hauskraftwerk und sendet die Messwerte an das Projekt **Ortsnetz-Auslastung** (`ortsnetz-auslastung.de`).

Das Skript läuft im **Minutentakt**: jeder Aufruf liest eine Stichprobe, hängt sie an die State-Datei und endet mit einem Exit-Code, den cron, systemd und Monitoring auswerten können. Gesendet wird erst, wenn seit der letzten Annahme das Sendeintervall von 300 Sekunden vergangen ist – also alle fünf Minuten – und nach einer zusätzlichen Zufallsverzögerung von bis zu 60 Sekunden, damit nicht alle Integrationen zur vollen Minute gleichzeitig auf die API treffen. Aus den Stichproben dieses Intervalls werden die Min-, Max- und Durchschnittswerte der Spannungen und der Netzfrequenz gebildet.

---

## 📋 Voraussetzungen

* **Python:** Version 3.8 oder höher
* **pye3dc:** `pip install pye3dc` (Version 0.10.0 oder neuer, Modulname `e3dc`)
* **Netzwerk:** Lokaler Zugriff auf das E3/DC Hauskraftwerk über dessen IP-Adresse
* **Zeitsynchronisation:** NTP/chrony aktiv (`timedatectl` prüfen). Die Stichproben des Intervalls und `observed_at` werden aus der Systemzeit gebildet.
* **Zugangsdaten:**
  * Zugang zum E3/DC-Portal (Benutzername und Passwort, für die RSCP-Anmeldung)
  * Lokaler RSCP-Schlüssel (am Display des E3/DC unter *Einstellungen > Personalisieren* einstellbar)

---

## ⚙️ Installation

```bash
sudo install -d -o root -g root -m 755 /opt/ortsnetz-e3dc
sudo install -o root -g root -m 755 e3dc_ortsnetz.py /opt/ortsnetz-e3dc/
```

Script und Ordner gehören bewusst `root` und sind für normale Benutzer nicht beschreibbar, weil der systemd-Dienst das Script ausführt. Die Zugangsdaten gehören in eine `.env`-Datei, nicht in das Script.

---

## 🔧 Konfiguration

Zugangsdaten und Standort stehen in einer `.env`-Datei oder in Environment-Variablen, nicht im Script.

| Variable | Pflicht | Beschreibung |
|---|---|---|
| `E3DC_HOST` | ja | IP-Adresse des E3/DC-Hauskraftwerks im Heimnetz |
| `E3DC_USERNAME`, `E3DC_PASSWORD` | ja | Zugang zum E3/DC-Portal, für die RSCP-Anmeldung am Hauskraftwerk |
| `RSCP_KEY` | ja | Lokaler RSCP-Schlüssel: Display > Einstellungen > Personalisieren |
| `LATITUDE`, `LONGITUDE` | ja | Ungefährer Standort in Dezimalgrad, z. B. `48.109569` und `11.726477` |
| `METER_INDEX` | – | Index des Netzzählers, Standard ist die automatische Suche nach `PM_TYPE_ROOT` |
| `PLANT_CAPACITY_KWP` | – | Installierte PV-Leistung in kWp. Leer = die installierte Spitzenleistung des Kraftwerks |
| `BATTERY_CAPACITY_KWH` | – | Nutzbare Batteriespeicherkapazität aus dem Datenblatt. Leer = die installierte Kapazität als Näherung |
| `SMARTMETER_MODEL` | – | Freie Bezeichnung des Messgeräts. Leer = Modell des Kraftwerks ohne Seriennummer |
| `PV_FORECAST_HA_URL` | – | Basis-URL des Home Assistant, z. B. `http://192.168.60.10:8123`; nur für die Prognose |
| `PV_FORECAST_HA_TOKEN` | – | Long-lived Token mit Scope *Read & Historical* für die Prognose aus Home Assistant |
| `PV_FORECAST_HA_ENTITY` | – | Kommata-Liste der Prognosesensoren, z. B. `sensor.pv_prognose_sud,sensor.pv_prognose_west` |
| `PV_FORECAST_MAX_AGE_S` | – | Prognosewerte älter als diese Sekunden werden nicht gesendet, Standard 3600; `0` schaltet die Altersprüfung ab. Für Solcast-Sensoren 21600 empfehlen |
| `PV_FORECAST_DATEI` | – | Datei mit der PV-Tagesprognose in kWh (evcc, Home Assistant, ioBroker) |
| `PV_FORECAST_BEFEHL` | – | Befehl, der die kWh-Zahl der Prognose in die Standardsausgabe schreibt |
| `STATE_DATEI` | – | State-Datei der Stichproben. Leer = `~/.local/state/ortsnetz-e3dc/state.json`, bei systemd `/var/lib/ortsnetz-e3dc/state.json` |
| `SENDINTERVALL_S` | – | Sendeintervall in Sekunden, Standard 300; darf nicht kleiner sein |
| `SENDEZUFALL_S` | – | Zufallsverzögerung vor dem Senden in Sekunden, Standard 60, Maximum 120; `0` schaltet sie aus. Nur auf Sendeläufen |
| `ENV_DATEI` | – | Pfad einer alternativen `.env`-Datei, Standard ist `.env` neben dem Script |

### `.env`-Datei

```bash
cp .env.example .env
nano .env          # Zugangsdaten und Standort eintragen
chmod 600 .env     # Zugangsdaten nur für den Besitzer lesbar
```

Die Datei liegt neben dem Script (`.env` ist in der `.gitignore`, wird also nicht eingecommitted). Leere Zeilen und Kommentare (`#`) werden ignoriert, Anführungszeichen um Werte entfernt. **Gesetzte Environment-Variablen haben Vorrang** vor der Datei; leere Environment-Variablen gelten als nicht gesetzt. So bleibt das Script unverändert und lässt sich bei einem Update einfach ersetzen.

Ein einmaliger Aufruf mit Variablen in der Shell:

```bash
E3DC_HOST=192.168.60.220 E3DC_USERNAME=deine_email@domain.de E3DC_PASSWORD=dein_passwort \
  RSCP_KEY=dein_key LATITUDE=48.109569 LONGITUDE=11.726477 \
  python3 /opt/ortsnetz-e3dc/e3dc_ortsnetz.py --dry-run
```

---

## 🔍 Welcher Zähler wird benutzt?

Der Netzzähler ist **nicht** automatisch `powermeters[0]`: E3/DC meldet die installierten Zähler in Reihenfolge der RSCP-Indizes, und in vielen Installationen stehen dort auch Wallbox-, PV-, Batteriezähler oder S0-Zähler. Das Skript deshalb:

1. Liste aller Zähler über `get_powermeters()` abfragen.
2. Den Zähler auswählen, dessen Typ `PM_TYPE_ROOT` ist (Name geprüft, weil der Zahlenwert des Typs von der pye3dc-Version abhängt).
3. `METER_INDEX` setzen, um einen bestimmten Index zu erzwingen. Das Skript verlangt auch dann den Typ `PM_TYPE_ROOT` und bricht andernfalls ab – so kann kein fremder Zähler gemeldet werden.

Fund der Typ nicht (sehr alte pye3dc-Versionen nennen keine Typnamen), wird der erste Zähler benutzt und das im Log ausdrücklich als Warnung vermerkt.

## 🌡️ Netzfrequenz

`grid_frequency_hz` wird nur übertragen, wenn die Frequenz gemessen und plausibel ist (45 bis 55 Hz):

* pye3dc bis 0.9.x liefert die Frequenz im Zählerdatensatz (`frequency`).
* pye3dc ab 0.10.0 hat die Frequenz **nicht** im Zählerdatensatz. Das Skript fragt sie dann als RSCP-Tag `PVI_REQ_AC_FREQUENCY` innerhalb eines `PVI_REQ_DATA`-Containers am ersten PV-Wechselrichter ab; die Antwort enthält `PVI_AC_FREQUENCY` mit `PVI_VALUE` in Hz.
* Ist beides nicht verfügbar, wird eine Warnung ins Log geschrieben und das Feld weggelassen; die Messung selbst wird trotzdem übertragen.

An einem E3/DC-Kraftwerk mit PV-Wechselrichtern funktioniert dieser Weg (Testlauf: `f=50.02 Hz`). Ohne Wechselrichter fällt die Frequenzübertragung weg; die Spannungswerte bleiben davon unberührt. Nachts liefert der Wechselrichter keine gültige Frequenz – dann werden die Frequenzkennzahlen aus den Stichproben gebildet, die gültige Werte enthalten.

## ⚡ Netzleistung und Ladezustand

* `grid_power_w`: RSCP-Tag `EMS_REQ_POWER_GRID`. pye3dc dokumentiert den Wert als „absorption from grid in W“, also **positiv = Bezug, negativ = Einspeisung** – genau die Konvention, die die API verlangt. Werte außerhalb von ±60 kW werden nicht übertragen.
* `battery_soc_percent`: RSCP-Tag `EMS_REQ_BAT_SOC`, 0 bis 100. `0` ist ein gültiger Wert. Ein Hauskraftwerk ohne Speicher beantwortet die Abfrage nicht; das Feld wird dann weggelassen.
* `plant_capacity_kwp` und `battery_capacity`: aus den statischen Systemangaben des Kraftwerks (`installedPeakPower` in W, `installedBatteryCapacity` in Wh), die pye3dc beim Verbindungsaufbau ohnehin einliest. Ein Konfigurationswert hat Vorrang, weil die API die **nutzbare** Kapazität will und `installedBatteryCapacity` die **installierte** nennt.
* `smartmeter_model`: Modell des Hauskraftwerks, das pye3dc beim Verbindungsaufbau einliest, z. B. `E3/DC S10_Mini`. Die Seriennummer wird **nicht** übertragen – sie ist eine Gerätekennung und das Repo überträgt keine Gerätekennungen. Wer sie ausdrücklich wünscht, setzt sie über `SMARTMETER_MODEL`.

---

## 📊 Min, Max und Mittelwert über das Intervall

Die API erwartet die Kennzahlen `l1_v_min`, `l1_v_max`, `l1_v_avg` (entsprechend L2, L3) und `grid_frequency_hz_min/max/avg` über das **Übertragungsintervall von 300 Sekunden**. Eine einzelne Messung pro Lauf würde `min = max = avg` ergeben. Deshalb:

* Jeder Minutenlauf hängt die Stichprobe `[Zeit, L1, L2, L3, Frequenz]` an die State-Datei.
* Beim Senden werden nur die Stichproben des Fensters `[jetzt − 300 s, jetzt]` ausgewertet.
* Stichproben älter als 15 Minuten und Stichproben aus der Zukunft werden verworfen, damit ein verschobener Timer die Kennzahlen nicht mit alten Werten füllt. Das setzt eine synchronisierte Uhr voraus: eine voreilende Uhr wirft die eigenen Stichproben still als Zukunft weg, eine nacheilende Uhr füllt das Fenster mit alten Werten.
* Nicht gemessene Phasen (`None`) werden bei den Kennzahlen ignoriert; eine Phase ohne jegliche gültige Stichprobe bekommt `-1`, wie die API es verlangt.
* Fehlende Frequenz: die Frequenzkennzahlen werden weggelassen, nicht mit `-1` gefüllt.
* Die State-Datei wird atomar geschrieben (Schreiben in `.tmp`, dann `os.replace`). Ein Schreibfehler bricht die Messung nicht ab.
* Nach einem Sendefehler bleibt `last_send` unverändert, der nächste Lauf versucht es erneut; die bereits gespeicherte Stichprobe geht nicht verloren.

`STATE_DATEI` muss beschreibbar sein:

| Betrieb | Pfad |
|---|---|
| cron als normaler Benutzer | `~/.local/state/ortsnetz-e3dc/state.json` (oder `XDG_STATE_HOME`) |
| systemd-Dienst mit `DynamicUser` | `/var/lib/ortsnetz-e3dc/state.json` (vom Service über `StateDirectory` gesetzt) |

---

## 🚀 Testlauf

```bash
python3 /opt/ortsnetz-e3dc/e3dc_ortsnetz.py --dry-run
```

`--dry-run` ruft die Werte ab, prüft sie und zeigt den Payload, sendet ihn aber nicht und schreibt keine State-Datei:

```json
{
  "observed_at": "2026-11-04T09:00:00Z",
  "latitude": 48.109569,
  "longitude": 11.726477,
  "l1_v": 230.15,
  "l2_v": 231.02,
  "l3_v": 229.85,
  "smartmeter_model": "E3/DC S10_Mini",
  "integration_version": "e3dc-rscp-1.4",
  "l1_v_min": 229.0,
  "l1_v_max": 231.5,
  "l1_v_avg": 230.23,
  "l2_v_min": 229.5,
  "l2_v_max": 232.0,
  "l2_v_avg": 230.88,
  "l3_v_min": 229.5,
  "l3_v_max": 231.5,
  "l3_v_avg": 230.5,
  "grid_frequency_hz": 50.01,
  "grid_frequency_hz_min": 49.9,
  "grid_frequency_hz_max": 50.1,
  "grid_frequency_hz_avg": 50.01,
  "grid_power_w": -4200.0,
  "battery_soc_percent": 57,
  "plant_capacity_kwp": 9.8,
  "battery_capacity": 10.4,
  "pv_forecast_kwh": 24.5
}
```

Die Unit-Tests laufen ohne Hauskraftwerk: `python3 test_e3dc.py`

---

## ⏱️ Betrieb per cron

```bash
crontab -e
```

```
*/1 * * * * /usr/bin/timeout 180 /usr/bin/python3 /opt/ortsnetz-e3dc/e3dc_ortsnetz.py >> $HOME/ortsnetz-e3dc.log 2>&1
```

Das Skript liest die `.env`-Datei selbst, die Zugangsdaten stehen also nicht in der Crontab. Eine Stichprobe je Minute, Senden alle 5 Minuten: die API erwartet pro Messquelle ein Sendeintervall von 300 Sekunden, das Sendeintervall wird durch `SENDINTERVALL_S` nicht verkürzt. Vor dem Senden wartet das Skript eine zufällige Zeit (`SENDEZUFALL_S`), damit nicht alle Integrationen, die auf die vollen Minuten getimt sind, gleichzeitig auf die API treffen. Das Skript bricht nach 120 Sekunden ab (`MAX_LAUFZEIT_S`), `timeout 180` fängt zusätzlich einen hängenden Lauf ab, damit sich bei einem nicht antwortenden Hauskraftwerk keine Prozesse ansammeln. Der Eintrag gehört in die Crontab eines normalen, unprivilegierten Benutzers, nicht in die von root.

## ⏱️ Betrieb per systemd-Timer

Der Timer ersetzt cron: Er startet das Skript alle **eine Minute** als `oneshot`-Service, die Logs landen im Journal. Ein nicht null Exit-Code markiert den Lauf als fehlgeschlagen.

```bash
sudo cp systemd/ortsnetz-e3dc.service systemd/ortsnetz-e3dc.timer /etc/systemd/system/
sudo cp systemd/ortsnetz-e3dc.env.example /etc/ortsnetz-e3dc.env
sudo nano /etc/ortsnetz-e3dc.env     # Zugangsdaten und Standort anpassen
sudo chmod 600 /etc/ortsnetz-e3dc.env
sudo systemctl daemon-reload
sudo systemctl enable --now ortsnetz-e3dc.timer
```

Der Dienst läuft mit `DynamicUser=yes` als unprivilegierter, temporärer Benutzer und nicht als root. `StateDirectory=ortsnetz-e3dc` gibt ihm den einzigen schreibbaren Ordner für die State-Datei; `Environment=STATE_DATEI` zeigt ihm den Pfad. `TimeoutStartSec=130s` begrenzt die Laufzeit eines Laufs und nimmt den Sendeversatz (`SENDEZUFALL_S`) mit auf. Pfade bei Bedarf an die eigene Installation anpassen.

Kontrolle:

```bash
systemctl list-timers ortsnetz-e3dc.timer
sudo systemctl start ortsnetz-e3dc.service   # sofort eine Stichprobe auslösen
journalctl -u ortsnetz-e3dc.service -n 20
```

Nur einen der beiden Wege (cron **oder** systemd-Timer) einrichten, sonst werden doppelt Stichproben gesammelt und gesendet.

---

## 📤 Übertragene Daten

Übertragen werden:

* Zeitstempel der Messung (Systemzeit)
* Breiten- und Längengrad aus der Konfiguration
* Spannungen L1, L2, L3 (nicht gemessene Phasen als `-1`) und ihre Min-, Max- und Durchschnittswerte über das Intervall
* Netzfrequenz und ihre Kennzahlen, sofern plausibel
* Netzleistung am Hausanschluss (`grid_power_w`, negativ = Einspeisung)
* Ladezustand des Batteriespeichers (`battery_soc_percent`)
* installierte PV-Leistung und Batteriespeicherkapazität, aus den Systemangaben des Kraftwerks oder der Konfiguration
* Modell des Hauskraftwerks als Bezeichnung des Messgeräts, ohne Seriennummer
* optional die PV-Tagesprognose aus Home Assistant (REST API), einer Datei oder einem Befehl
* Kennung der Integration

**Neu gegenüber der ersten Version:** Netzleistung, Ladezustand, Kapazitäten, Modell des Kraftwerks und die Kennzahlen über das Intervall.

Nicht übertragen werden insbesondere: Zugangsdaten, RSCP-Schlüssel, IP-Adresse des Hauskraftwerks, Zählerindex, **Seriennummer und weitere Gerätekennungen**, Energiezähler, Strom (`l1_a` …), Scheinleistung (`apparent_power_va`) und Leistungsfaktor (`power_factor`). Die Strom- und Leistungsfaktorfelder entfallen bewusst: der Netzzähler (`PM_TYPE_ROOT`) meldet über RSCP nur Leistung, Spannung, Energie, Modus und Phasen – kein Strom und keine Scheinleistung. Werte vom PV-Wechselrichter (`PVI_AC_CURRENT`, `PVI_AC_APPARENTPOWER`) sind laut API-Beschreibung kein Ersatz für den Hausanschluss, und ein aus `P / U` gerechneter Strom wäre ohne Leistungsfaktor falsch. Die API erlaubt das Weglassen dieser Felder ausdrücklich.

### PV-Prognose

pye3dc liefert **keine** PV-Prognose – weder lokal noch über die Web-Verbindung (`wss://s10.e3dc.com/ws` ist nur ein RSCP-Kanal zum Kraftwerk, die Portal-Prognose gehört nicht zum RSCP-Tag-Satz). `pv_forecast_kwh` kommt deshalb aus einer externen Quelle, wie in den anderen Integrationen dieses Repos. Reihenfolge: **Home Assistant, dann Datei, dann Befehl**; alle leer = das Feld wird nicht übertragen.

### Prognose aus Home Assistant

Home Assistant hat die Prognose meist schon (Solar-Forecast, entao, EVCC-Integration). Das Skript fragt die Sensoren über die REST API ab, ohne selbst zu prognostizieren:

```
PV_FORECAST_HA_URL=http://192.168.60.10:8123
PV_FORECAST_HA_TOKEN=<long-lived Token, Scope Read & Historical>
PV_FORECAST_HA_ENTITY=sensor.pv_prognose_sud,sensor.pv_prognose_west
PV_FORECAST_MAX_AGE_S=3600
```

`PV_FORECAST_MAX_AGE_S` auf die Aktualisierungsfrequenz der Quelle stellen: stündliche Quellen passen zu 3600. **Solcast** aktualisiert nur wenige Male am Tag (Lücken von 4–6 h); mit 3600 fiele die Prognose tagsüber meist weg, hier sind 21600 der passende Wert.

* Der Aufruf ist `GET /api/states/<entity>` mit `Authorization: Bearer …`, 15 s Timeout je Sensor. Mehrere Sensoren werden **addiert**, für eine Ost/West-Anlage also ein Sensor je Teilanlage.
* Der Sensor muss **Energie in kWh** melden (`unit_of_measurement: "kWh"`). `Wh` und `MWh` werden umgerechnet; eine fehlende oder unbekannte Einheit (besonders `W`, also Leistung) wird **nicht geraten**, der Sensor übersprungen. Ein Template-Sensor in kWh:

  ```yaml
  template:
    - sensor:
        - name: pv_prognose_today_kwh
          unit_of_measurement: "kWh"
          state: >-
            {{ ((states('sensor.solar_forecast_production_today') | float(0)) / 1000) | round(1) }}
  ```

* Das Alter wird über `last_reported` (ersatzweise `last_updated`) geprüft. Nachts behält ein Sensor den Abendwert; ein Wert älter als `PV_FORECAST_MAX_AGE_S` Sekunden wird übersprungen. `unavailable` und `unknown` (nachts) ebenfalls.
* Token in der `.env` mit `chmod 600`, nie als Befehlsargument und nie ins Log.
* Ein Sensorausfall überschreibt die Messung nicht: das Skript warnt und sendet die Messung ohne `pv_forecast_kwh` (Exit-Code `0`).
* Bei mehreren Sensoren und 15 s Timeout je Sensor bleiben bei drei Sensoren noch rund 15 s für Hauskraftwerk und API innerhalb der 60 s Laufzeit.

### Prognose aus Datei oder Befehl

* `PV_FORECAST_DATEI`: eine Datei, die evcc, Home Assistant oder ioBroker mit der kWh-Zahl schreiben (Zahl, Text oder JSON mit einem der Schlüssel `pv_forecast_kwh`, `pv_forecast`, `kwh`, `forecast`, `value`).
* `PV_FORECAST_BEFEHL`: ein Befehl ohne Shell, der die kWh-Zahl in die Standardsausgabe schreibt (15 s Timeout).

Alle Quellen leer = das Feld wird nicht übertragen. Vor dem Senden prüft das Skript die Grenzen der API: eine Prognose ohne bekannte Anlagengröße und mehr als 10 kWh je kWp werden **nicht** gesendet, weil die API solche Messungen mit HTTP 422 verwirft.


---

## 🛠️ Log, Exit-Codes und Fehler

Bei erfolgreicher Übertragung:

```
2026-11-04 09:05:01 Benutzter Zähler: Index 1 Typ PM_TYPE_ROOT | L1=230.15 L2=231.02 L3=229.85 V | f=50.01 Hz | P=-4200.0 W | SOC=57 % | 5 Stichproben im Intervall
2026-11-04 09:05:01 Sendeversatz: warte 23 s, damit nicht alle Quellen gleichzeitig senden.
2026-11-04 09:05:24 Übertragen (2026-11-04T09:05:01Z): HTTP 202, Messung angenommen.
2026-11-04 09:05:24 Ampel: l1=normal l2=normal l3=normal | gesamt=green
2026-11-04 09:05:24 Speicherladeempfehlung: charge.
2026-11-04 09:05:24 Redispatch: active=True affected_units=2 active_measures=[...] data_updated_at=2026-11-04T09:00:00Z
```

Bei einer Laufzeit, die noch nicht sendet:

```
2026-11-04 09:06:01 Benutzter Zähler: Index 1 Typ PM_TYPE_ROOT | L1=230.20 L2=231.10 L3=229.90 V | f=50.01 Hz | P=-4100.0 W | SOC=57 % | 2 Stichproben im Intervall
2026-11-04 09:06:01 Stichprobe gespeichert, Senden erst in 240 s.
```

Das Skript sendet nur, wenn die API `HTTP 202` antwortet **und** die Antwort `accepted: true` enthält. `observed_at` ist die Zeit der Stichprobe, nicht die Zeit nach dem Versatz; Stichproben-Zeitstempel und Kennzahlenfenster bleiben durch den Versatz unverändert. Die Antwortfelder `status` (Ampel je Phase und gesamt), `storage_recommendation` und `redispatch` werden ins Log geschrieben; fehlen sie (ältere Server), wird nichts spekuliert. Exit-Codes:

| Exit-Code | Bedeutung |
|---|---|
| `0` | Stichprobe gespeichert **oder** Messung übertragen und von der API angenommen |
| `1` | Konfiguration fehlt oder ist ungültig (`.env` prüfen) |
| `2` | RSCP-Verbindung zum Hauskraftwerk gestört (IP, RSCP-Schlüssel, pye3dc-Version) |
| `3` | Keine plausible Messung (kein Zähler, Zählertyp passt nicht, Spannungen unplausibel) |
| `4` | API-Antwort unbrauchbar (HTTP-Fehler, Verbindungsabbruch) |
| `130` | Process abgebrochen |

| Meldung | Ursache |
|---|---|
| `E3DC_HOST ist nicht gesetzt` / `LATITUDE und LONGITUDE müssen …` | `.env` fehlt, ist unvollständig, oder Zugangsdaten nicht gesetzt |
| `Environment-Variable … ist ungültig` | Ein Wert in `.env` lässt sich nicht als Zahl lesen |
| `Zählerindex 2 existiert nicht` / `kein Netzzähler` / `Zählerindex 0 ist kein Netzzähler` | `METER_INDEX` auf einen Zähler gesetzt, der nicht der Netzzähler ist; gemeldete Liste aller Zähler hilft |
| `Kein Netzzähler vom Typ PM_TYPE_ROOT gefunden` | Installation hat keinen Root-Zähler gemeldet; Zähler am Hauskraftwerk prüfen |
| `L1: keine plausible Spannung` | Spannung fehlt oder liegt außerhalb von 150 bis 300 V |
| `Warnung: Netzfrequenz … unplausibel` | Frequenz außerhalb von 45 bis 55 Hz, Feld wird weggelassen |
| `Warnung: Netzleistung nicht verfügbar` | Hauskraftwerk beantwortet `EMS_REQ_POWER_GRID` nicht, Feld wird weggelassen |
| `Warnung: Ladezustand … unplausibel` | Kein Speicher oder Antwort außerhalb 0 bis 100 %, Feld wird weggelassen |
| `Warnung: State-Datei … ist unlesbar` | State-Datei defekt; Min/Max/avg nur aus der aktuellen Stichprobe, Datei wird neu angelegt |
| `Warnung: State-Datei … konnte nicht geschrieben werden` | `STATE_DATEI` nicht beschreibbar (bei systemd `StateDirectory` prüfen) |
| `Warnung: Home Assistant … nicht abrufbar` | Token abgelaufen, HA nicht erreichbar, URL falsch; Sensor übersprungen, Messung wird trotzdem gesendet |
| `Warnung: Sensor … meldet … – keine Zahl` | Sensor meldet `unavailable`/`unknown` (nachts), Feld wird weggelassen |
| `Warnung: Sensor … hat Einheit … – keine bekannte Energieeinheit` | Sensor deklariert keine Energieeinheit in kWh/Wh/MWh (oft `W`), Feld wird weggelassen |
| `Warnung: Sensor … ist … s alt` | Sensor hält einen veralteten Wert älter als `PV_FORECAST_MAX_AGE_S`, Feld wird weggelassen |
| `Warnung: Prognosedatei … ist nicht lesbar` | `PV_FORECAST_DATEI` zeigt auf eine fehlende oder gesperrte Datei |
| `Warnung: PV-Prognose … überschreitet …` | Prognose über 10 kWh je kWp, Feld wird weggelassen (API: HTTP 422) |
| `RSCP-Verbindung … fehlgeschlagen` | Hauskraftwerk nicht erreichbar, RSCP-Schlüssel falsch, pye3dc-Version zu alt |
| `Maximale Laufzeit von 60 s überschritten` | Hauskraftwerk oder API antwortet nur sehr langsam |
| `HTTP 403` | Der Standort ist für die Annahme gesperrt |
| `HTTP 422` | Payload von der API abgelehnt, die Antwort nennt das betroffene Feld |

---

## 🔐 Zugangsdaten

* `.env` mit `chmod 600` schützen und nicht ins Repository committen (`.env` ist in der `.gitignore`).
* Portal-Passwort und RSCP-Schlüssel sind Schlüssel zum Hauskraftwerk – nicht per E-Mail, Chat oder Issue-Tracker weitergeben.
* Falls Zugangsdaten jemals im Code gestanden haben, am besten aus dem Git-History entfernen (`git filter-repo`) und das Passwort ändern.

---

## 🛠️ Funktionsweise

1. **RSCP-Verbindung:** Verbindung zum E3/DC-Hauskraftwerk über `E3DC(CONNECT_LOCAL, …)` mit Portal-Zugang und RSCP-Schlüssel.
2. **Zählerauswahl:** Alle Zähler auflisten, den Typ `PM_TYPE_ROOT` auswählen (Index konfigurierbar).
3. **Stichprobe:** Spannungen L1, L2, L3 und Netzfrequenz lesen, Form älterer und neuerer pye3dc-Versionen normalisieren; Netzleistung (`EMS_REQ_POWER_GRID`) und Ladezustand (`EMS_REQ_BAT_SOC`) abfragen.
4. **Plausibilitätsprüfung:** Spannungen 150 bis 300 V, Frequenz 45 bis 55 Hz, Netzleistung ±60 kW, Ladezustand 0 bis 100 %.
5. **State-Datei:** Stichprobe anhängen, Altlasten verwerfen, atomar schreiben.
6. **Sende-Gating:** nur senden, wenn seit der letzten Annahme `SENDINTERVALL_S` Sekunden vergangen sind.
7. **Payload:** Min, Max und Mittelwert aus den Stichproben des Intervalls; statische Angaben aus den Systemangaben des Kraftwerks; Prognose aus der externen Quelle.
8. **Übertragung:** HTTP POST (JSON) an `https://www.ortsnetz-auslastung.de/v1/measurements`, Antwortfelder ins Log, Exit-Code je Ergebnis.

---

## Weitere Informationen

* API-Beschreibung und weitere Integrationen: [datenerfassung-ortsnetz-auslastung](https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung)
* pye3dc: [pye3dc auf PyPI](https://pypi.org/project/pye3dc/)
