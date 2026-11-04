# E3/DC Ortsnetz-Auslastung Integration

Dieses Python-Skript liest die aktuellen Phasenspannungen (L1, L2, L3) und die Netzfrequenz lokal über das RSCP-Protokoll von einem E3/DC-Hauskraftwerk aus und sendet die Messwerte an das Projekt **Ortsnetz-Auslastung** (`ortsnetz-auslastung.de`).

Jeder Aufruf führt genau eine Messung und Übertragung aus und endet mit einem Exit-Code, den cron, systemd und Monitoring auswerten können.

---

## 📋 Voraussetzungen

* **Python:** Version 3.8 oder höher
* **pye3dc:** `pip install pye3dc` (Version 0.10.0 oder neuer, Modulname `e3dc`)
* **Netzwerk:** Lokaler Zugriff auf das E3/DC Hauskraftwerk über dessen IP-Adresse
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
| `PLANT_CAPACITY_KWP` | – | Installierte PV-Leistung in kWp (größer 0, höchstens 1000), nicht gesetzt = nicht senden |
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

Im Log steht bei jeder Messung, welcher Zähler verwendet wurde:

```
2026-11-03 10:00:01 Benutzter Zähler: Index 1 Typ PM_TYPE_ROOT | L1=230.15 L2=231.02 L3=229.85 V | f=50.01 Hz
```

## 🌡️ Netzfrequenz

`grid_frequency_hz` wird nur übertragen, wenn die Frequenz gemessen und plausibel ist (45 bis 55 Hz):

* pye3dc bis 0.9.x liefert die Frequenz im Zählerdatensatz (`frequency`).
* pye3dc ab 0.10.0 hat die Frequenz **nicht** im Zählerdatensatz. Das Skript fragt sie dann als RSCP-Tag `PVI_REQ_AC_FREQUENCY` innerhalb eines `PVI_REQ_DATA`-Containers am ersten PV-Wechselrichter ab; die Antwort enthält `PVI_AC_FREQUENCY` mit `PVI_VALUE` in Hz.
* Ist beides nicht verfügbar, wird eine Warnung ins Log geschrieben und das Feld weggelassen; die Messung selbst wird trotzdem übertragen.

An einem E3/DC-Kraftwerk mit PV-Wechselrichtern funktioniert dieser Weg (Testlauf: `f=50.02 Hz`). Ohne Wechselrichter fällt die Frequenzübertragung weg; die Spannungswerte bleiben davon unberührt.

---

## 🚀 Testlauf

```bash
python3 /opt/ortsnetz-e3dc/e3dc_ortsnetz.py --dry-run
```

`--dry-run` ruft die Werte ab, prüft sie und zeigt den Payload, sendet ihn aber nicht:

```json
{
  "observed_at": "2026-11-03T10:00:00Z",
  "latitude": 48.109569,
  "longitude": 11.726477,
  "l1_v": 230.15,
  "l2_v": 231.02,
  "l3_v": 229.85,
  "smartmeter_model": "E3DC Hauskraftwerk",
  "integration_version": "e3dc-rscp-1.1",
  "grid_frequency_hz": 50.01
}
```

Die Unit-Tests laufen ohne Hauskraftwerk: `python3 test_e3dc.py`

---

## ⏱️ Betrieb per cron

```bash
crontab -e
```

```
*/5 * * * * /usr/bin/timeout 90 /usr/bin/python3 /opt/ortsnetz-e3dc/e3dc_ortsnetz.py >> $HOME/ortsnetz-e3dc.log 2>&1
```

Das Skript liest die `.env`-Datei selbst, die Zugangsdaten stehen also nicht in der Crontab. Die API erwartet pro Messquelle ein Sendeintervall von 300 Sekunden, das Intervall nicht verkürzen. Das Skript bricht nach 60 Sekunden ab (`MAX_LAUFZEIT_S`), `timeout 90` fängt zusätzlich einen hängenden Lauf ab, damit sich bei einem nicht antwortenden Hauskraftwerk keine Prozesse ansammeln. Der Eintrag gehört in die Crontab eines normalen, unprivilegierten Benutzers, nicht in die von root.

## ⏱️ Betrieb per systemd-Timer

Der Timer ersetzt cron: Er startet das Skript alle fünf Minuten als `oneshot`-Service, die Logs landen im Journal. Ein nicht null Exit-Code markiert den Lauf als fehlgeschlagen.

```bash
sudo cp systemd/ortsnetz-e3dc.service systemd/ortsnetz-e3dc.timer /etc/systemd/system/
sudo cp systemd/ortsnetz-e3dc.env.example /etc/ortsnetz-e3dc.env
sudo nano /etc/ortsnetz-e3dc.env     # Zugangsdaten und Standort anpassen
sudo chmod 600 /etc/ortsnetz-e3dc.env
sudo systemctl daemon-reload
sudo systemctl enable --now ortsnetz-e3dc.timer
```

Der Dienst läuft mit `DynamicUser=yes` als unprivilegierter, temporärer Benutzer und nicht als root. `TimeoutStartSec=60s` begrenzt die Laufzeit einer Messung. Pfade bei Bedarf an die eigene Installation anpassen.

Kontrolle:

```bash
systemctl list-timers ortsnetz-e3dc.timer
sudo systemctl start ortsnetz-e3dc.service   # sofort eine Messung auslösen
journalctl -u ortsnetz-e3dc.service -n 20
```

Nur einen der beiden Wege (cron **oder** systemd-Timer) einrichten, sonst wird doppelt gesendet.

---

## 📤 Übertragene Daten

Übertragen werden nur:

* Zeitstempel der Messung (Systemzeit)
* Breiten- und Längengrad aus der Konfiguration
* Spannungen L1, L2 und L3 (nicht gemessene Phasen als `-1`)
* Netzfrequenz, sofern plausibel
* Zählermodell `E3DC Hauskraftwerk` und Kennung der Integration
* optional die installierte PV-Leistung aus der Konfiguration

Nicht übertragen werden insbesondere: Zugangsdaten, RSCP-Schlüssel, IP-Adresse des Hauskraftwerks, Zählerindex, Strom, Leistung und Energiezähler.

---

## 🛠️ Log, Exit-Codes und Fehler

Bei erfolgreicher Übertragung:

```
2026-11-03 10:00:01 Benutzter Zähler: Index 1 Typ PM_TYPE_ROOT | L1=230.15 L2=231.02 L3=229.85 V | f=50.01 Hz
2026-11-03 10:00:02 Übertragen (2026-11-03T10:00:01Z): HTTP 202, Messung angenommen.
```

Das Skript sendet nur, wenn die API `HTTP 202` antwortet **und** die Antwort `accepted: true` enthält. Exit-Codes:

| Exit-Code | Bedeutung |
|---|---|
| `0` | Messung übertragen und von der API angenommen |
| `1` | Konfiguration fehlt oder ist ungültig (`.env` prüfen) |
| `2` | RSCP-Verbindung zum Hauskraftwerk gestört (IP, RSCP-Schlüssel, Pye3dc-Version) |
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
| `Warnung: Netzfrequenz nicht verfügbar` | Hauskraftwerk beantwortet die Frequenzabfrage nicht, Feld wird weggelassen |
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
3. **Datenextraktion:** Spannungen L1, L2, L3 und Netzfrequenz lesen, Form älterer und neuerer pye3dc-Versionen normalisieren.
4. **Plausibilitätsprüfung:** Spannungen 150 bis 300 V, Frequenz 45 bis 55 Hz.
5. **Übertragung:** HTTP POST (JSON) an `https://www.ortsnetz-auslastung.de/v1/measurements`, Exit-Code je Ergebnis.

---

## Weitere Informationen

* API-Beschreibung und weitere Integrationen: [datenerfassung-ortsnetz-auslastung](https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung)
* pye3dc: [pye3dc auf PyPI](https://pypi.org/project/pye3dc/)
