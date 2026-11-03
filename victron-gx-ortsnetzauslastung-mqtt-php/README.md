# Victron GX (MQTT) → ortsnetz-auslastung.de

PHP-Script, das die Netzspannung (L1–L3) und optional die Netzfrequenz eines Victron GX-Geräts
(Cerbo GX, Venus GX, …) per **MQTT** ausliest und alle 5 Minuten an
[ortsnetz-auslastung.de](https://www.ortsnetz-auslastung.de) sendet.

- Es muss **nichts auf dem Cerbo installiert werden** – das Script läuft auf einem beliebigen Rechner im selben Netz (Raspberry Pi, NAS, Server, VM).
- Alle Einstellungen stehen in einer eigenen Datei (`config.php`). Das Script selbst muss nicht angepasst werden.
- Läuft als systemd-Dienst, protokolliert in Log und Statusdatei.

## Inhalt

| Datei | Zweck |
|---|---|
| `victron-ortsnetz.php` | Das Script (nicht bearbeiten) |
| `config.example.php` | Vorlage für die Einstellungen |
| `composer.json` | Abhängigkeit `php-mqtt/client` |
| `victron-ortsnetz.service` | systemd-Dienstdatei |

## Voraussetzungen

- PHP ≥ 8.0 (CLI) mit den Erweiterungen `openssl` (für https). Auf Debian/Ubuntu/Raspberry Pi OS:
  ```bash
  sudo apt install php-cli php-mbstring unzip composer
  ```
- Ein Rechner, der den Cerbo GX (bzw. dessen MQTT-Broker) im Netzwerk erreicht und Internetzugang hat.
- Einen Standort (Breiten-/Längengrad) – z. B. über [OpenStreetMap](https://www.openstreetmap.org) per Rechtsklick → „Abfrage starten".

## 1. Cerbo GX vorbereiten

1. MQTT am GX aktivieren: *Einstellungen → Dienste → MQTT am LAN (Klartext)* einschalten
   (oder die SSL-Variante, dann in der Config `'tls' => true` und den passenden Port setzen).
   Falls du bereits einen eigenen Mosquitto-Broker verwendest, der die Daten des Cerbo spiegelt, nimm dessen Adresse.
2. **VRM Portal-ID** notieren: *Einstellungen → VRM Online-Portal → VRM-Portal-ID* (12 Zeichen, z. B. `xxxxxxxxxxxx`).
3. Die Spannungen müssen am GX verfügbar sein, d. h. ein Netzzähler (z. B. Victron EM24/ET340) oder ein Multi/Quattro am Netz ist angeschlossen.

## 2. Installation

```bash
# Zielverzeichnis anlegen und Dateien dorthin kopieren
sudo mkdir -p /opt/victron-ortsnetz
sudo cp victron-ortsnetz.php config.example.php composer.json victron-ortsnetz.service /opt/victron-ortsnetz/
cd /opt/victron-ortsnetz

# Abhängigkeit installieren
sudo composer install --no-dev

# Konfiguration anlegen
sudo cp config.example.php config.php
sudo nano config.php
```

Wichtige Einstellungen in `config.php`:

| Einstellung | Bedeutung |
|---|---|
| `mqtt.host` / `mqtt.port` | Adresse des MQTT-Brokers (Cerbo oder eigener Broker) |
| `portal_id` | VRM Portal-ID des GX |
| `service` | `grid` = Netzzähler (Standard), `vebus` = AC-Eingang eines Multi/Quattro |
| `instance` | Geräteinstanz (z. B. `40`). `'+'` = automatisch, nur bei genau einem passenden Gerät |
| `phases` | `1` oder `3` |
| `latitude` / `longitude` | Standort der Messung |
| `plant_capacity_kwp` | Optional: Anlagengröße in kWp |
| `log_file`, `status_file` | Pfade für Log und Statusdatei |

Die Geräteinstanz findest du im VRM-Portal in der Geräteliste oder per
`mosquitto_sub -h <broker> -t 'N/<Portal-ID>/#' -v` (Pfad `grid/<Instanz>/…`).

Schutz der Konfiguration (enthält ggf. Zugangsdaten):

```bash
sudo chown -R www-data:www-data /opt/victron-ortsnetz     # Benutzer wie in der .service-Datei
sudo chmod 600 /opt/victron-ortsnetz/config.php
```

## 3. Testen (ohne zu senden)

```bash
cd /opt/victron-ortsnetz
sudo -u www-data php victron-ortsnetz.php --test
```

Das Script lauscht 20 Sekunden, zeigt die gelesenen Werte, die empfangenen Topics und den Payload, der gesendet würde – **sendet aber nichts**. Vergleiche die Spannung mit der Anzeige am GX.

Typische Meldungen:

- `L1=230.1 L2=229.8 L3=230.5 f=50.01` → alles in Ordnung
- `Nichts empfangen` → Portal-ID, `service`, `instance` oder MQTT-Einstellung am GX prüfen

## 4. Als systemd-Dienst einrichten

Die mitgelieferte Datei `victron-ortsnetz.service` geht davon aus, dass alles in `/opt/victron-ortsnetz` liegt und unter dem Benutzer `www-data` läuft (anpassen bei Bedarf: `User=`, `ExecStart=`-Pfad zu PHP prüfen mit `which php`).

**Variante A – per Link (empfohlen, die Datei bleibt im Projektordner):**

```bash
sudo systemctl link /opt/victron-ortsnetz/victron-ortsnetz.service
```

(entspricht einem Symlink: `sudo ln -s /opt/victron-ortsnetz/victron-ortsnetz.service /etc/systemd/system/victron-ortsnetz.service`)

**Variante B – kopieren:**

```bash
sudo cp /opt/victron-ortsnetz/victron-ortsnetz.service /etc/systemd/system/
```

Dann aktivieren und starten:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now victron-ortsnetz
```

Nützliche Befehle:

```bash
sudo systemctl status victron-ortsnetz        # läuft der Dienst?
sudo systemctl restart victron-ortsnetz       # nach Änderung der config.php
sudo systemctl stop victron-ortsnetz
journalctl -u victron-ortsnetz -f             # Live-Log
```

## 5. Kontrolle im Betrieb

**Log** (`journalctl -u victron-ortsnetz -f` oder `victron-ortsnetz.log`):

```
[2026-10-21 10:05:00] Gesendet OK (202): L1=230.1 L2=229.8 L3=230.5 f=50.01 | Ampel: green
[2026-10-21 10:10:00] FEHLER beim Senden (...): API nicht erreichbar
[2026-10-21 10:15:00] L2 fehlt oder unplausibel -> nichts gesendet.
```

**Statusdatei** (`status.json`):

| Feld | Bedeutung |
|---|---|
| `last_success` | Zeitpunkt (UTC) der letzten erfolgreichen Meldung |
| `last_values`, `last_ampel` | zuletzt gesendete Werte und Antwort der API |
| `success_count`, `error_count` | Zähler seit der ersten Meldung |
| `consecutive_errors` | Fehler in Folge (für Monitoring nutzen) |
| `last_error_message` | Text des letzten Fehlers |
| `last_skipped` | Letzte Runde, in der wegen fehlender/unplausibler Werte nichts gesendet wurde |

Ist `last_success` älter als ca. 10 Minuten, stimmt etwas nicht.

## Verhalten und Validierung

- Das Script sendet beim Start sobald Werte vorliegen (spätestens nach 30 s), danach alle `interval` Sekunden (Standard 300, Minimum 60).
- Es sendet nur, wenn alle erwarteten Phasen zwischen **150 und 300 V** liegen und nicht älter als `max_age` (Standard 15 min) sind. Die Frequenz wird nur bei 45–55 Hz mitgesendet.
- Einphasige Anlagen: `phases => 1`; L2 und L3 werden als `-1` übertragen.
- Zum GX sendet das Script alle 30 s ein MQTT-Keepalive (`R/<Portal-ID>/keepalive`), damit der GX Werte weiter veröffentlicht.

## Fehlersuche

| Problem | Ursache / Lösung |
|---|---|
| `Nichts empfangen` im Test | Portal-ID falsch, MQTT am GX nicht aktiv, falsche `instance`/`service`, Firewall |
| `Konfigurationsdatei fehlt` | `config.example.php` nach `config.php` kopieren |
| `vendor/autoload.php` nicht gefunden | `composer install` im Ordner ausführen |
| Dienst startet nicht | `journalctl -u victron-ortsnetz -e`; PHP-Pfad und `User=` in der Service-Datei prüfen |
| Keine Schreibrechte für Log/Status | `chown -R www-data:www-data /opt/victron-ortsnetz` |
| API-Antwort 4xx | Meldung im Log lesen (z. B. Koordinaten oder Werte ungültig) |
| Werte bleiben nach einigen Minuten aus | Keepalive-Optionen des GX/der Firmware prüfen (Issue im Projekt melden) |

## Datenschutz

Gesendet werden ausschließlich Zeitstempel, Standort, Spannungen/Frequenz und optionale Angaben (Anlagengröße, Zählermodell, Skriptversion). Zugangsdaten bleiben lokal in `config.php`. Einzelheiten zur Datenverarbeitung: [Methodik & Datenschutz](https://www.ortsnetz-auslastung.de/methodik).
