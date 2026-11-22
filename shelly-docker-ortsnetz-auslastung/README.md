# Ortsnetz-Auslastung für Shelly Pro 3EM (Docker)

Ein Docker-Container, der die drei Netzspannungen eines Shelly Pro 3EM oder Pro 3EM-400 lokal über die RPC-Schnittstelle abfragt und an die Ortsnetz-Auslastung-API überträgt. Er ist die Alternative zum [Shelly-Script](../shelly-ortsnetz-auslastung), wenn das Script nicht auf dem Shelly selbst laufen soll, etwa um den Shelly zu entlasten oder weil bereits ein Docker-Host vorhanden ist.

Der Container sendet sofort nach dem Start und danach alle fünf Minuten. Dazwischen fragt er den Shelly alle 15 Sekunden ab und überträgt zusätzlich Minimum, Maximum und Mittelwert der Spannungen (`l1_v_min`, `l1_v_max`, `l1_v_avg` usw.), damit kurze Spannungsspitzen und -einbrüche nicht verloren gehen.

Es gibt keine Cloud-Abhängigkeit, keine lokale Datenhaltung und keine Wiederholungslogik: Ist der Shelly oder die API nicht erreichbar, wird die Messung verworfen und der nächste Versuch erfolgt regulär fünf Minuten später.

## Voraussetzungen

- Shelly **Pro 3EM** oder **Pro 3EM-400** (Gen2+), im selben Netz wie der Docker-Host erreichbar
- Docker mit Compose (alternativ Python ab 3.8, nur Standardbibliothek)
- Internetzugang des Docker-Hosts auf `https://www.ortsnetz-auslastung.de`
- Breitengrad und Längengrad des Messortes (siehe [Koordinaten](../README.md#koordinaten))

Die RPC-Schnittstelle des Shelly muss ohne Anmeldung erreichbar sein (Standard: **Authentication** in den Geräteeinstellungen deaktiviert). Eine Digest-Authentifizierung wird nicht unterstützt.

## Installation

1. Ordner auf den Docker-Host kopieren und die Konfiguration anlegen:

   ```sh
   cp .env.example .env
   ```

2. In `.env` mindestens `ORTSNETZ_SHELLY_IP`, `ORTSNETZ_LATITUDE` und `ORTSNETZ_LONGITUDE` eintragen. Beim Pro 3EM-400 zusätzlich `ORTSNETZ_SHELLY_MODEL=Shelly Pro 3EM-400` und `ORTSNETZ_CURRENT_TRANSFORMER_A=400`.
3. Abfrage testen, ohne zu senden. Die Ausgabe zeigt den Payload; die Spannungen lassen sich mit der Shelly-Oberfläche vergleichen:

   ```sh
   docker compose run --rm ortsnetz-shelly python3 ortsnetz-shelly.py --dry-run
   ```

4. Container starten:

   ```sh
   docker compose up -d --build
   docker compose logs -f
   ```

   Jede angenommene Messung erscheint mit den gesendeten Werten im Log, z. B.:

   ```text
   2026-11-16 14:11:10 Messung angenommen (HTTP 202), Ampel: green | gesendet: L1 230.8 V, L2 229.0 V, L3 231.0 V, 50.00 Hz, 19.043 W
   ```

Ohne Docker lässt sich das Script direkt starten, die Variablen kommen dann aus der Umgebung:

```sh
export $(grep -v '^#' .env | xargs)
python3 ortsnetz-shelly.py --once
```

`--once` sendet eine Messung und beendet sich, `--dry-run` gibt sie nur aus. Beide liefern Exitcode 0 bei Erfolg, 1 bei Lese- oder Übertragungsfehlern und 2 bei ungültiger Konfiguration.

## Konfiguration

| Variable | Pflicht | Standard | Beschreibung |
| --- | --- | --- | --- |
| `ORTSNETZ_SHELLY_IP` | Ja | | IP-Adresse oder Hostname des Shelly |
| `ORTSNETZ_LATITUDE` | Ja | | Breitengrad des Messortes |
| `ORTSNETZ_LONGITUDE` | Ja | | Längengrad des Messortes |
| `ORTSNETZ_SHELLY_MODEL` | Nein | `Shelly Pro 3EM` | Bezeichnung des Messgeräts (`smartmeter_model`) |
| `ORTSNETZ_CURRENT_TRANSFORMER_A` | Nein | `120` | `120` oder `400`, Obergrenze für plausible Stromwerte |
| `ORTSNETZ_CAPACITY_KWP` | Nein | | Installierte PV-Leistung in kWp |
| `ORTSNETZ_BATTERY_KWH` | Nein | | Nutzbare Batteriekapazität in kWh |
| `ORTSNETZ_INTERVAL_S` | Nein | `300` | Sendeintervall, mindestens 300 |
| `ORTSNETZ_SAMPLE_INTERVAL_S` | Nein | `15` | Abfrageintervall für Minimum, Maximum und Mittelwert |

## Übertragene Messwerte

Der Container liest `EM.GetStatus` (Komponente `em:0`):

| Ortsnetz-Wert | Shelly-Wert |
| --- | --- |
| `l1_v`, `l2_v`, `l3_v` | `a_voltage`, `b_voltage`, `c_voltage` |
| `l1_a`, `l2_a`, `l3_a` | `a_current`, `b_current`, `c_current` |
| `grid_frequency_hz` | erste gültige von `a_freq`, `b_freq`, `c_freq` |
| `grid_power_w` | `total_act_power` (Bezug positiv, Einspeisung negativ) |
| `apparent_power_va` | `total_aprt_power` |

Spannungen werden nur zwischen 150 und 300 V übertragen, sonst steht `-1`. Die Frequenz wird nur zwischen 45 und 55 Hz gesendet. Hat keine Phase eine gültige Spannung, wird die Messung verworfen.

## Datenschutz

Übertragen werden Zeitstempel, Koordinaten, Smartmeter-Modell und Integrationsversion sowie Spannungen, Ströme, Netzfrequenz und Leistung des Shelly. Die Karte zeigt Koordinaten nur gerastert mit etwa 100 Metern Genauigkeit. Verwende bei Bedarf einen leicht versetzten Punkt, wenn du den exakten Standort nicht übertragen möchtest.

## Tests

```sh
python3 -I test_shelly.py
```

Die Tests laufen mit synthetischen Shelly-Antworten und benötigen weder Netzwerk noch Shelly.

## Quellen

- [Shelly EM-Komponente](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM/)
