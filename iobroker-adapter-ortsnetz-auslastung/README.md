# ioBroker-Adapter „Ortsnetz-Auslastung“

Ein vollwertiger ioBroker-Adapter für [ortsnetz-auslastung.de](https://www.ortsnetz-auslastung.de/). Er ersetzt das JavaScript aus [`../iobroker-ortsnetz-auslastung`](../iobroker-ortsnetz-auslastung) und bietet zusätzlich:

- **Einstellungsdialog** statt `CONFIG`-Block: Name, Position, Messgerät, PV-Leistung, Speicherkapazität und eine Tabelle der Datenpunkte mit Objektauswahl
- **Prioritätslisten je Messgröße**: mehrere Datenpunkte pro Phase oder Frequenz; es gewinnt der erste mit **frischem** und plausiblem Wert (wichtig bei HomeMatic, SMA und anderen Geräten, die nur bei Änderungen melden)
- **Einphasige Messung**: Phasen ohne Datenpunkt werden laut [API.md](../API.md) als `-1` gesendet
- **Minimum, Maximum und Mittelwert** über das 5-Minuten-Intervall (`l1_v_min` …), optional
- Weitere optionale Felder: PV-Prognose, Speicher-Ladezustand, Netzleistung
- **Datenpunkte** mit der Antwort der API: Ampel je Phase, Speicherladeempfehlung, Redispatch im 50-km-Umkreis
- **Vergleich mit der Umgebung**: Messpunkte im Umkreis, mittlere/kleinste/größte Spannung, eigene Abweichung
- **Eigener Menüpunkt im Admin** (abschaltbar) mit der bundesweiten Karte aller Messpunkte und einer separaten Ansicht der eigenen Messpunkte inklusive 24-Stunden-Verlauf
- **Testbetrieb**: Payload nur protokollieren, nichts senden

Übertragen werden nur gerundete Koordinaten, Messwerte und – einmal pro Start – das Gerätemodell sowie PV- und Speichergröße. Gerätekennungen, Zählernummern und IP-Adressen werden **nicht** gesendet.

## Voraussetzungen

| | |
| --- | --- |
| js-controller | ab 5.0 |
| Admin | ab 7.0 (getestet mit 8.0.11) |
| Node.js | ab 20 (verwendet das eingebaute `fetch`) |
| Netz | ausgehender HTTPS-Zugriff auf `www.ortsnetz-auslastung.de`; der Browser lädt Kartenkacheln von `tile.openstreetmap.org` |

## Installation

Der Adapter ist (noch) nicht im offiziellen ioBroker-Repository. Drei Wege:

### a) Über die Admin-Oberfläche (GitHub)

**Adapter** → Symbol **„Benutzerdefiniert installieren“** (Katze/Oktokat) → Reiter **„Beliebig“** → URL eines Archivs mit diesem Verzeichnis als Paketwurzel, z. B. eines mit `npm pack` erzeugten `.tgz`.

### b) Auf der Kommandozeile des ioBroker-Hosts

```bash
cd iobroker-adapter-ortsnetz-auslastung
npm pack                                  # erzeugt iobroker.ortsnetz-auslastung-0.1.0.tgz
# Datei auf den ioBroker-Host kopieren, dann dort:
cd /opt/iobroker
npm install /pfad/zu/iobroker.ortsnetz-auslastung-0.1.0.tgz --omit=dev
iobroker upload ortsnetz-auslastung
iobroker add ortsnetz-auslastung          # legt Instanz .0 an
```

### c) ioBroker im Docker-Container auf einem anderen Rechner: `deploy.sh`

```bash
cp deploy.env.example deploy.env          # Ziel eintragen (SSH-Ziel, gemountetes Verzeichnis, Containername)
./deploy.sh                               # testen, packen, kopieren, installieren, hochladen, Instanzen neu starten
```

Das Skript legt beim ersten Mal eine (deaktivierte) Instanz an und startet bei Updates alle vorhandenen Instanzen neu.

## Konfiguration

**Eine Instanz = ein Messort.** Für einen weiteren Standort (z. B. eine Ferienwohnung) unter **Adapter → Ortsnetz-Auslastung → „+“** eine zweite Instanz anlegen. Der Menüpunkt zeigt alle Instanzen gemeinsam.

### Reiter „Standort“

| Einstellung | Bedeutung |
| --- | --- |
| **Name dieser Instanz** | z. B. `Haus Musterstadt`. Wird als Titel der Instanz (Instanzliste), in der Karte und im Protokoll verwendet. |
| **Breitengrad / Längengrad** | Position des Hausanschlusses. Drei Nachkommastellen (~100 m) genügen. Knopf **„Position aus den Systemeinstellungen“** übernimmt die ioBroker-Systemposition. |
| **Koordinaten runden auf** | 2, 3 (Standard) oder 4 Nachkommastellen beim Senden. Der eigene Punkt auf der Karte wird über die auf 3 Stellen gerundeten Koordinaten erkannt. |
| **Messgerät** | Hersteller und Modell, z. B. `Shelly Pro 3EM` (max. 120 Zeichen) |
| **PV-Leistung (kWp)** | optional; Voraussetzung für die PV-Prognose |
| **Speicherkapazität (kWh)** | optional; nutzbare Kapazität |

### Reiter „Geräte und Datenpunkte“

Tabelle mit je einer Zeile pro Datenpunkt:

| Spalte | Bedeutung |
| --- | --- |
| **Aktiv** | Zeile berücksichtigen |
| **Messgröße** | Spannung L1/L2/L3 (V), Netzfrequenz (Hz), PV-Prognose heute (kWh), Speicher-Ladezustand (%), Netzleistung (W, + Bezug / − Einspeisung) |
| **Datenpunkt** | Auswahl im Objektbaum |

Pro Messgröße sind mehrere Zeilen erlaubt; die **Reihenfolge der Tabelle ist die Priorität**. Bei jedem Upload wird der erste Datenpunkt genommen, dessen Wert

- numerisch und plausibel ist (Spannung 150–300 V, Frequenz 45–55 Hz, SOC 0–100 %) und
- nicht älter ist als **„Spannung höchstens … Minuten alt“** bzw. **„Frequenz, SOC, Netzleistung höchstens … Minuten alt“** (die PV-Prognose darf 24 h alt sein).

Regeln für die Phasen:

- Phase **ohne** Datenpunkt → wird als `-1` („nicht gemessen“) gesendet. Bei einphasiger Messung also nur L1 eintragen.
- Phase **mit** Datenpunkten, aber ohne frischen Wert → der Upload wird übersprungen und in `upload.lastError` gemeldet. So wird aus einem ausgefallenen Dreiphasenzähler nicht stillschweigend eine Einphasenmessung.

Hilfen (benötigen eine laufende Instanz):

- **„Spannungs- und Frequenz-Datenpunkte suchen“** listet alle Datenpunkte mit Rolle `value.voltage`/`value.frequency`, Einheit V/Hz oder passendem Namen, die gerade einen plausiblen Wert haben – frischeste zuerst.
- **„Payload testen“** zeigt mit den aktuell eingetragenen (auch ungespeicherten) Werten, welcher Datenpunkt je Messgröße gewinnt und welcher Payload entstünde.

### Reiter „Übertragung und Karte“

| Einstellung | Standard | Bedeutung |
| --- | --- | --- |
| Minimum, Maximum und Mittelwert mitsenden | an | aus allen Werten des gewählten Datenpunkts im Intervall (mindestens zwei) |
| Testbetrieb | aus | Payload nur ins Protokoll und nach `upload.lastPayload`, nichts senden |
| Menüpunkt im Admin-Seitenmenü anzeigen | an | blendet den Menüpunkt „Ortsnetz-Auslastung“ ein/aus; danach den Admin im Browser neu laden |
| Öffentliche Karte regelmäßig laden | an | Grundlage der Umgebungswerte (`neighbours.*`) |
| Karte laden alle … Minuten | 15 | ca. 0,7 MB je Abruf |
| Umkreis für Umgebungswerte | 25 km | |

### Beispiel: Umstieg vom JavaScript

| Script (`CONFIG`) | Adapter |
| --- | --- |
| `site: 'Musterstadt'` | Name der Instanz `Haus Musterstadt` |
| `latitude`, `longitude` | Breitengrad, Längengrad |
| `l1States: [a, b, c]` | drei Zeilen „Spannung L1“ in dieser Reihenfolge |
| `l2States: []`, `l3States: []` | keine Zeilen → `-1` |
| `frequencyStates: [...]` | Zeilen „Netzfrequenz“ |
| `maxAgeMin`, `maxAgeFreqMin` | Frische-Einstellungen |
| `plantCapacityKwp`, `pvForecastState` | PV-Leistung, Zeile „PV-Prognose heute“ |
| `smartmeterModel` | Messgerät |
| `dryRun` | Testbetrieb |

Nach dem ersten angenommenen Upload des Adapters das Script **deaktivieren**, sonst wird doppelt gesendet. Die alten Datenpunkte unter `0_userdata.0.Ortsnetz.<Standort>` werden nicht mehr aktualisiert und können gelöscht werden.

## Zeitverhalten

- Erster Upload 15 s nach dem Start, danach immer zur Minute 0, 5, 10, … (API: eine Messung je Quelle alle 300 s).
- Zeitüberschreitung je Übertragung 10 s; ein Fehler blockiert keinen folgenden Lauf.
- Gerätemodell, PV-Leistung und Speicherkapazität werden beim ersten Upload nach jedem Start gesendet (bis er angenommen wurde) – laut API genügt das, der Server speichert sie.

## Datenpunkte

Alle Datenpunkte liegen unter `ortsnetz-auslastung.<n>.` und sind nur lesbar.

| Datenpunkt | Typ | Bedeutung |
| --- | --- | --- |
| `info.connection` | boolean | letzter Upload wurde angenommen (HTTP 202) |
| `measurement.voltageL1` … `voltageL3` | number (V) | gesendete Spannung, `-1` = nicht gemessen |
| `measurement.frequency` | number (Hz) | gesendete Netzfrequenz |
| `measurement.sourceL1` … `sourceL3`, `sourceFrequency` | string | Datenpunkt, der beim letzten Upload gewonnen hat |
| `grid.statusOverall` | string | Ampel gesamt: `green` / `yellow` / `red` |
| `grid.statusL1` … `statusL3` | string | Ampel je Phase |
| `grid.storageRecommendation` | string | `charge` (laden) / `discharge` (entladen) / `none` |
| `grid.redispatchActive` | boolean/null | Redispatch im 50-km-Umkreis in der letzten Stunde; `null` = unbekannt |
| `grid.redispatchAffectedUnits` | number | betroffene Anlagen |
| `grid.redispatchActiveMeasures` | number | Maßnahmen |
| `grid.redispatchUpdatedAt` | string | Datenstand der Redispatch-Daten |
| `upload.lastUpload` | string | Zeitpunkt des letzten angenommenen Uploads (ISO) |
| `upload.lastAttempt` | string | letzter Versuch (ISO) |
| `upload.lastHttpStatus` | number | HTTP-Status der API |
| `upload.lastError` | string | letzter Fehler, leer = in Ordnung |
| `upload.uploadsOk`, `upload.uploadsFailed` | number | Zähler seit dem Start der Instanz |
| `upload.lastPayload`, `upload.lastResponse` | string (JSON) | zuletzt gesendet bzw. empfangen |
| `upload.history` | string (JSON) | eigener Verlauf der letzten 24 h (für den Menüpunkt) |
| `neighbours.publicId` | string | Kennung des eigenen Punkts auf der öffentlichen Karte |
| `neighbours.count` | number | Messpunkte im Umkreis (ohne eigenen, ohne veraltete) |
| `neighbours.avgVoltage`, `minVoltage`, `maxVoltage` | number (V) | über alle gemessenen Phasen im Umkreis |
| `neighbours.deviation` | number (V) | eigene L1-Spannung minus Mittel im Umkreis |
| `neighbours.nearestKm` | number (km) | Entfernung zum nächsten Messpunkt |
| `map.pointCount` | number | Messpunkte auf der Karte |
| `map.lastUpdate` | string | Karte zuletzt geladen |
| `map.normal24h`, `map.warning24h`, `map.critical24h` | number | bundesweite Messungen der letzten 24 h nach Bewertung |

Beispiel für eine Automatisierung (JavaScript-Adapter): Hausspeicher bei Überspannung laden.

```javascript
on({ id: 'ortsnetz-auslastung.0.grid.storageRecommendation', change: 'ne' }, (obj) => {
    if (obj.state.val === 'charge') setState('mein-speicher.0.forceCharge', true);
});
```

## Menüpunkt „Ortsnetz-Auslastung“

Erscheint im Seitenmenü des Admin, sobald eine Instanz läuft und die Option eingeschaltet ist.

- **🗺️ Karte**: alle Messpunkte der öffentlichen Karte, eingefärbt nach der schlechtesten Phase mit derselben Skala wie ortsnetz-auslastung.de (kritisch < 207 V, Warnung < 218 V bzw. > 242 V, kritisch > 253 V). Legende mit Filtern und Anzahl; veraltete Punkte sind standardmäßig ausgeblendet. Ein Klick zeigt Werte und den 24-Stunden-Verlauf des Punkts. Eigene Messpunkte sind mit violettem Ring und Namen hervorgehoben.
- **🏠 Eigene Messpunkte**: je Instanz eine Karte mit Spannung je Phase, Frequenz, Ampel, Speicherempfehlung, Redispatch, Umgebungsvergleich, Herkunft der Werte, letzter Meldung, 24-Stunden-Verlauf und Knopf **„Jetzt senden“**.

Der Browser spricht nie direkt mit ortsnetz-auslastung.de (die API erlaubt keine Aufrufe aus fremden Webseiten); alle Daten laufen über die Instanz (`sendTo`).

## Fehleranalyse

| Meldung in `upload.lastError` / Protokoll | Ursache |
| --- | --- |
| `keine frische, plausible Spannung für L1` | Kein Datenpunkt der Phase hat einen Wert 150–300 V, der jünger als die eingestellte Frische ist. Mit „Payload testen“ prüfen. |
| `Koordinaten fehlen oder sind ungültig` | Breiten-/Längengrad eintragen. |
| `HTTP 422: …` | Ein Wert liegt außerhalb des API-Bereichs (z. B. PV-Prognose ohne PV-Leistung). Details in `upload.lastResponse`. |
| `HTTP 403` | Der Standort ist beim Betreiber gesperrt. |
| `Testbetrieb (nichts gesendet)` | Testbetrieb ist eingeschaltet. |

## Entwicklung

```bash
npm test          # node --test test/   (Logik in lib/measure.js)
./deploy.sh       # auf den eigenen ioBroker
```

| Datei | Aufgabe |
| --- | --- |
| `main.js` | Adapter: Zeitplan, Upload, Datenpunkte, Karte, Kommandos für Menüpunkt und Dialog |
| `lib/measure.js` | reine Logik: Quellenauswahl, Payload, Statistik, Bewertung, Umgebung |
| `lib/states.js` | Tabelle aller Datenpunkte |
| `admin/jsonConfig.json`, `admin/i18n/` | Einstellungsdialog (Deutsch/Englisch) |
| `admin/tab.html`, `tab.js`, `tab.css` | Menüpunkt; Karte mit [Leaflet](https://leafletjs.com/) 1.9.4 (lokal in `admin/lib/leaflet`, BSD-2-Lizenz) |

## Lizenz

MIT – siehe [LICENSE](LICENSE). Kartendaten © OpenStreetMap-Mitwirkende, Messdaten von ortsnetz-auslastung.de.
