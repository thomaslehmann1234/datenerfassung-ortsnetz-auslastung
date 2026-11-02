# Loxone Miniserver → Ortsnetz-Auslastung

Python-Script, das Netzspannungen aus einem **Loxone Miniserver** liest und an [ortsnetz-auslastung.de](https://www.ortsnetz-auslastung.de) überträgt. Gelesen werden Bausteine, die im Miniserver bereits Spannungswerte tragen, zum Beispiel Virtuelle Eingänge eines Modbus-Zählers, eines Wechselrichters oder eines Energiezählers. Optional werden Netzfrequenz, Phasenströme, Leistungsfaktor, Netzleistung am Hausanschluss und Ladezustand eines Speichers mitgesendet.

Im Dauerbetrieb liest das Script alle 10 Sekunden und sendet alle fünf Minuten eine Messung mit **Minimum, Maximum und Mittelwert** der Spannungen und der Frequenz über das Intervall. Alternativ führt `--once` genau eine Messung und Übertragung aus (für cron).

## Funktionsweise

1. Jeder konfigurierte Baustein wird über den Webservice des Miniservers gelesen:
```
	http://<LOXONE_HOST>/jdev/sps/io/<Bezeichnung des Bausteins>
```
2. Der Miniserver liefert den Wert mit Einheit, zum Beispiel `"237.68 V"`; das Script übernimmt die Zahl am Anfang.
3. Spannungen müssen zwischen 150 V und 300 V liegen, sonst wird die Probe verworfen. Ein optionaler Wert, der nicht gelesen werden kann oder nicht plausibel ist, fehlt nur in dieser Probe.
4. Im Dauerbetrieb wird an jeder Fünf-Minuten-Grenze (:00, :05, ...) die letzte Probe als Messung gesendet, dazu `l1_v_min` / `l1_v_max` / `l1_v_avg` usw. über alle Proben des Intervalls. Ein Intervall ohne gültige Probe wird nicht gesendet.
5. `observed_at` ist die Zeit der letzten Probe (UTC). Die Uhrzeit des Rechners muss stimmen (NTP).

## Voraussetzungen

- Loxone Miniserver im Heimnetz, Spannungen als Bausteine mit eindeutiger Bezeichnung (z. B. Virtuelle Eingänge `L1 voltage`, `L2 voltage`, `L3 voltage`)
- **Ein Loxone-Benutzer mit Leserechten auf genau diese Bausteine.** Am besten einen eigenen Benutzer anlegen und ihm in Loxone Config die Rechte nur für die gelesenen Bausteine geben. Fehlen die Rechte, antwortet der Miniserver mit Code `403` und das Script meldet `keine Rechte auf diesen Baustein`.
- Linux-Rechner im selben Netz, zum Beispiel ein Raspberry Pi, mit systemd oder cron und Internetzugang
- Python ab 3.8 (nur Standardbibliothek)

### Test mit curl

```bash
curl -u <Benutzer>:<Passwort> "http://<IP-des-Miniservers>/jdev/sps/io/L1%20voltage"
```

```json
{"LL": { "control": "dev/sps/io/L1 voltage", "value": "237.68 V", "Code": "200"}}
```

### Hinweis zum Messort

Das Script überträgt, was der Miniserver misst. Stammen die Spannungen von einem Wechselrichter oder Speicher (z. B. SigenStor über Modbus), liegen sie an dessen AC-Klemmen und nicht am Netzanschlusspunkt; unter Last weichen sie um einige Zehntel Volt ab. Den Messort in `SMARTMETER_MODEL` angeben, z. B. `Sigenergy SigenStor (Wechselrichter-AC) via Loxone`.

## Konfiguration

Im Konfigurationsblock des Scripts oder per Environment-Variablen (diese haben Vorrang), siehe [`systemd/ortsnetz-loxone.env.example`](systemd/ortsnetz-loxone.env.example).

| Variable | Pflicht | Beschreibung |
| --- | --- | --- |
| `LOXONE_HOST` | Ja | IP oder Hostname des Miniservers, optional mit Port |
| `LOXONE_USER`, `LOXONE_PASSWORD` | Ja | Loxone-Benutzer mit Leserechten auf die Bausteine |
| `LATITUDE`, `LONGITUDE` | Ja | Ungefährer Standort, siehe [Koordinaten](../README.md#koordinaten) |
| `NAME_L1` | Ja | Bezeichnung des Bausteins der Spannung L1 |
| `NAME_L2`, `NAME_L3` | Nein | Beide setzen oder beide leer lassen (einphasig, `-1`) |
| `NAME_FREQUENZ` | Nein | Netzfrequenz in Hz |
| `NAME_STROM_L1` … `NAME_STROM_L3` | Nein | Phasenströme in A (als Betrag übertragen) |
| `NAME_LEISTUNGSFAKTOR` | Nein | Leistungsfaktor (als Betrag übertragen) |
| `NAME_NETZLEISTUNG`, `NETZLEISTUNG_FAKTOR` | Nein | Netzleistung am Hausanschluss; der Faktor rechnet auf W mit Bezug positiv um (`1000` für kW, `-1000` für kW mit Einspeisung positiv) |
| `NAME_SOC` | Nein | Ladezustand des Speichers in % |
| `NAME_PV_PROGNOSE` | Nein | Heutige PV-Gesamtprognose in kWh (z. B. ein Virtueller Eingang, den ein Prognosedienst befüllt); braucht `PLANT_CAPACITY_KWP`, ein Wert über 10 kWh je kWp wird nicht übertragen |
| `PLANT_CAPACITY_KWP` | Nein | Installierte PV-Leistung in kWp; Pflicht mit `NAME_PV_PROGNOSE` |
| `BATTERY_CAPACITY_KWH` | Nein | Nutzbare Kapazität des Batteriespeichers in kWh |
| `SMARTMETER_MODEL` | Nein | Bezeichnung von Messgerät und Messort |
| `ABTAST_S`, `INTERVALL_S` | Nein | Abtastung (Standard 10 s) und Sendeintervall (Standard 300 s) |

Nicht gesetzte optionale Werte werden nicht übertragen. Die Netzleistung nur angeben, wenn sie wirklich am Hausanschluss gemessen wird, nicht die Leistung eines Wechselrichters.

## Ausprobieren

```bash
export LOXONE_HOST=192.168.1.77 LOXONE_USER=ortsnetz LOXONE_PASSWORD=... LATITUDE=52.52 LONGITUDE=13.40
export NAME_L1="L1 voltage" NAME_L2="L2 voltage" NAME_L3="L3 voltage" NAME_FREQUENZ="Grid frequency"
python3 ortsnetz_loxone.py --dry-run     # liest einmal und gibt die Payload aus, sendet nichts
python3 ortsnetz_loxone.py --once        # liest einmal und sendet
```

## Installation als systemd-Dienst (Dauerbetrieb)

```bash
sudo mkdir -p /opt/ortsnetz-loxone
sudo cp ortsnetz_loxone.py /opt/ortsnetz-loxone/
sudo cp systemd/ortsnetz-loxone.env.example /etc/ortsnetz-loxone.env
sudo chmod 600 /etc/ortsnetz-loxone.env       # enthält das Loxone-Passwort
sudo nano /etc/ortsnetz-loxone.env
sudo cp systemd/ortsnetz-loxone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ortsnetz-loxone.service
journalctl -u ortsnetz-loxone.service -f
```

## Alternative: cron (eine Messung je Aufruf, ohne Minimum/Maximum/Mittelwert)

```
*/5 * * * * set -a; . /etc/ortsnetz-loxone.env; set +a; /usr/bin/python3 /opt/ortsnetz-loxone/ortsnetz_loxone.py --once >> $HOME/ortsnetz-loxone.log 2>&1
```

## Tests

```bash
python3 -m unittest test_loxone
```

Die Tests starten einen lokalen Schein-Miniserver und einen Schein-Endpunkt; es wird nichts an die echte API gesendet.
