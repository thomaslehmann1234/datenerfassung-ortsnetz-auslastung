# API-Beschreibung

## Endpoint

```text
POST https://www.ortsnetz-auslastung.de/v1/measurements
Content-Type: application/json
```

Der Endpoint ist öffentlich und benötigt keine Authentifizierung. Jede Messung wird einzeln übertragen.

## Sendeintervall

Messungen sollen pro Messquelle alle **300 Sekunden (5 Minuten)** gesendet werden. Das Sendeintervall wird durch den Client bzw. die Integration gesteuert.

## Request-Felder

| Feld | Typ | Pflicht | Beschreibung |
| --- | --- | --- | --- |
| `observed_at` | String | Ja | ISO-8601-Zeitstempel mit Zeitzone, bevorzugt UTC, z. B. `2026-09-15T08:00:00Z` |
| `latitude` | Zahl | Ja | Breitengrad von -90 bis 90 |
| `longitude` | Zahl | Ja | Längengrad von -180 bis 180 |
| `l1_v` | Zahl | Ja | Spannung Phase L1 in Volt, größer als 0 und maximal 500; bei nicht gemessener Phase `-1` |
| `l2_v` | Zahl | Ja | Spannung Phase L2 in Volt, größer als 0 und maximal 500; bei nicht gemessener Phase `-1` |
| `l3_v` | Zahl | Ja | Spannung Phase L3 in Volt, größer als 0 und maximal 500; bei nicht gemessener Phase `-1` |
| `grid_frequency_hz` | Zahl | Nein | Netzfrequenz in Hertz, 45 bis 55 |
| `plant_capacity_kwp` | Zahl | Nein | Installierte PV-Leistung in kWp, größer als 0 und maximal 1000; für Forecasts erforderlich, sofern nicht bereits am Standort gespeichert |
| `pv_forecast_kwh` | Zahl | Nein | Heutige PV-Gesamtprognose in kWh, 0 bis 100000; benötigt eine mitgesendete oder am Standort gespeicherte Anlagengröße und darf 10 kWh je kWp pro Tag nicht überschreiten; andernfalls HTTP 422 für die gesamte Messung |
| `smartmeter_model` | String | Nein | Freie Bezeichnung des Messgeräts, maximal 120 Zeichen |
| `integration_version` | String | Nein | Kennung der Integration, maximal 32 Zeichen |

## Beispiel

```json
{
  "observed_at": "2026-09-15T08:00:00Z",
  "latitude": 52.520008,
  "longitude": 13.404954,
  "l1_v": 230.1,
  "l2_v": 229.9,
  "l3_v": 230.4,
  "grid_frequency_hz": 50.0,
  "integration_version": "iobroker-0.1.0"
}
```

## Responses

| Status | Bedeutung |
| --- | --- |
| `202 Accepted` | Messung angenommen; die Antwort enthält `accepted`, `created`, eine Ampelbewertung je Phase und insgesamt sowie eine Speicherladeempfehlung. |
| `422 Unprocessable Entity` | Pflichtfeld fehlt, hat ein ungültiges Format oder liegt außerhalb des erlaubten Wertebereichs. |
| `403 Forbidden` | Der Standort ist für die Annahme gesperrt. |

Beispielantwort bei Annahme:

```json
{
  "accepted": true,
  "created": true,
  "status": {
    "l1": "green",
    "l2": "green",
    "l3": "green",
    "overall": "green"
  },
  "storage_recommendation": "none",
  "redispatch": {
    "active": null,
    "affected_units": null,
    "active_measures": null,
    "data_updated_at": null
  }
}
```

## Speicherladeempfehlung

`storage_recommendation` ist eine direkt aus der übertragenen Messung abgeleitete Empfehlung. Es gibt keinen zusätzlichen API-Aufruf.

| Wert | Bedeutung | Bedingung |
| --- | --- | --- |
| `discharge` | Speicher entladen | Mindestens eine gemessene Phase liegt unter ihrer unteren Warnschwelle. |
| `charge` | Speicher laden | Keine Phase liegt unter der unteren Warnschwelle und mindestens eine gemessene Phase liegt über ihrer oberen Warnschwelle. |
| `none` | Keine Aktion | Alle gemessenen Phasen liegen innerhalb der Warnschwellen. |

Nicht verfügbare Phasen mit dem Wert `-1` werden ignoriert. Liegen gleichzeitig Unter- und Überspannungen vor, hat `discharge` Vorrang. Die Schwellenwerte entsprechen immer der auf dem Server konfigurierten Spannungsskala.

## Versionierung und Kompatibilität

Alle hier beschriebenen Felder sind im Backend implementiert und verwenden
weiterhin `POST /v1/measurements`. Der Zielserver muss diese Version bereits
ausgerollt haben. Ein neuer `/v2`-Endpoint ist nicht erforderlich: Bestehende
Pflichtfelder, Statuscodes, Einheiten, Spannungsbewertung und Speicherladeempfehlung
bleiben unverändert. Neue Request-Felder sind optional; Clients müssen zusätzliche
Antwortfelder ignorieren und mit einem fehlenden `redispatch`-Objekt auf älteren
Servern umgehen können.

Die vorhandenen Scripts und Integrationen senden neue Felder nicht automatisch.
Sie dürfen nur tatsächlich verfügbare Messwerte liefern. Unbekannte Werte werden
weggelassen oder als `null` übertragen, nicht durch `0` oder Schätzungen ersetzt.
Ein API-Versionswechsel wäre erst bei inkompatiblen Änderungen nötig.

## Zusätzliche optionale Messfelder

### Dynamische Messwerte

Die folgenden Felder werden mit einer regulären Messung im 5-Minuten-Raster
gesendet. Strom, Scheinleistung, Wirkleistung und Leistungsfaktor müssen nicht
gleichzeitig geliefert werden; es gibt keine automatische Ableitung fehlender
Werte. Alle Zahlen müssen endlich sein, also weder `NaN` noch Unendlich.

| Feld | Typ | Einheit / Bereich | Beschreibung |
| --- | --- | --- | --- |
| `l1_v_min`, `l1_v_max`, `l1_v_avg` | Zahl | V, größer 0 bis 500 oder `-1` | Minimum, Maximum und arithmetischer Mittelwert der Spannung an L1 |
| `l2_v_min`, `l2_v_max`, `l2_v_avg` | Zahl | V, größer 0 bis 500 oder `-1` | Entsprechende Spannungskennzahlen an L2 |
| `l3_v_min`, `l3_v_max`, `l3_v_avg` | Zahl | V, größer 0 bis 500 oder `-1` | Entsprechende Spannungskennzahlen an L3 |
| `grid_frequency_hz_min`, `grid_frequency_hz_max`, `grid_frequency_hz_avg` | Zahl | Hz, 45 bis 55 | Minimum, Maximum und Mittelwert der Netzfrequenz |
| `battery_soc_percent` | Zahl | %, 0 bis 100 | Aktueller Ladezustand; 0 ist ein gültiger Wert |
| `grid_power_w` | Zahl | W, vorzeichenbehaftet | Gesamte Wirkleistung aller Phasen am Hausanschluss: positiv = Bezug, negativ = Einspeisung |
| `power_factor` | Zahl | 0 bis 1 | Betrag des Leistungsfaktors am Hausanschluss: `abs(P) / S`; bei `S = 0` weglassen |
| `apparent_power_va` | Zahl | VA, mindestens 0 | Gesamte Scheinleistung am Hausanschluss |
| `l1_a`, `l2_a`, `l3_a` | Zahl | A, mindestens 0 oder `-1` | Effektivwert der Stromstärke der jeweiligen Phase; keine Leistung |

`min`, `max` und `avg` werden vom Client über dasselbe Übertragungsintervall
gebildet, üblicherweise fünf Minuten. Es werden keine zusätzlichen Intervallgrenzen
übermittelt. Die vorhandenen Werte müssen untereinander `min <= avg <= max`
erfüllen; das wird auch geprüft, wenn nur zwei dieser Werte vorhanden sind.
`-1` und `null` werden dabei als fehlend ignoriert.

Bei einer einphasigen Messung darf jede der drei Phasen die gemessene sein;
die anderen Pflichtfelder `l1_v`, `l2_v`, `l3_v` erhalten `-1`.
Mindestens eine Spannung muss gültig sein. Auch optionale phasenbezogene
Spannungskennzahlen und Stromstärken können fehlende Werte mit `-1` markieren.
Für Frequenz, SOC, Kapazität und Leistungsfaktor ist `-1` kein Ersatzwert.
`grid_power_w = -1` bedeutet hingegen eine Einspeisung von 1 W.

Netzleistung darf nicht durch Wechselrichterleistung oder eine einzelne Phase
eines mehrphasigen Hausanschlusses ersetzt werden. Umgekehrte Gerätekonventionen
müssen vor der Übertragung auf Bezug positiv / Einspeisung negativ umgerechnet
werden. Das unspezifische Entwurfsfeld `power_w` wurde nicht implementiert.

Bei passenden Effektivwerten ergibt `U × I` die Scheinleistung je Phase.
Phasen müssen passend zusammengeführt werden; eine einzelne Spannung mal
Gesamtstrom ist kein allgemeingültiger Gesamtwert. Für eine einzelne Phase mit
sinusförmigen Signalen entspricht der hier nichtnegative Leistungsfaktor
`abs(cos(φ))`; bei verzerrten Signalen reicht der Phasenwinkel allein nicht aus.
Der Leistungsfaktor bestimmt keine Energieflussrichtung. Bei gleichzeitigem
`apparent_power_va = 0` und vorhandenem `power_factor` antwortet die API mit 422.

Ein Feld „Eigenverbrauch“ ist nicht vorgesehen: Hausverbrauch und selbst genutzter
PV-Strom sind unterschiedliche Größen. PV-Leistung minus Netzeinspeisung ergibt
bei einem Batteriespeicher nicht automatisch den Hausverbrauch.

### Statische Standortangaben

Diese Angaben werden bei Einrichtung, Änderung und Client-Neustart zusammen mit
einer regulären Messung gesendet; eine zyklische Übertragung ist nicht nötig.
Auslassung oder `null` erhält den gespeicherten Wert und löscht ihn nicht.
Nach einem Standortwechsel durch geänderte Koordinaten müssen sie erneut gesendet werden.

| Feld | Typ / Bereich | Bedeutung |
| --- | --- | --- |
| `plant_capacity_kwp` | Zahl, größer 0 bis 1000 kWp | Installierte PV-Leistung; muss vor oder mit dem ersten Forecast bekannt sein |
| `smartmeter_model` | String, maximal 120 Zeichen | Hersteller und Modell des Messgeräts, nicht die übertragende Software |
| `battery_capacity` | Zahl, größer 0 kWh | Nutzbare Batteriespeicherkapazität, kein SOC oder aktueller Energieinhalt |

Das Messgerätemodell hilft bei der Einordnung, garantiert aber keine bestimmte Genauigkeit.
`pv_forecast_kwh` darf maximal 10 kWh je gespeicherter/mitgesendeter kWp pro Tag betragen;
ohne bekannte Anlagengröße oder bei Überschreitung folgt HTTP 422.

### Speicherung

Zusätzliche dynamische Werte werden in Rohmessungen und im letzten Messstand
gespeichert. Stundenwerte erhalten das kleinste gemeldete `_min`, größte `_max`
und den arithmetischen Mittelwert der übrigen verfügbaren Werte. Fehlende Werte
werden ignoriert; ein fehlender Stundenwert bleibt `null`, nicht 0.
Es wird nicht zwischen Messungen interpoliert. Die Aufbewahrung bleibt:
Rohmessungen 30 Tage, Stundenaggregate drei Jahre. Alte Datensätze erhalten
keine erfundenen Zusatzwerte. Bestehende Karten- und Statistikdiagramme ändern sich nicht.

Beispiel zusätzlicher Felder (Auszug, kein vollständiger Request):

```json
{
  "l1_v_min": 228.4,
  "l1_v_max": 232.1,
  "l1_v_avg": 230.2,
  "grid_frequency_hz_min": 49.98,
  "grid_frequency_hz_max": 50.03,
  "grid_frequency_hz_avg": 50.01,
  "battery_soc_percent": 62.5,
  "grid_power_w": -3515.0
}
```

Scheinleistung, Leistungsfaktor und Strom sind bewusst nicht erforderlich.
Bei Einrichtung oder Änderung können beispielsweise `"battery_capacity": 10.2`
und `"smartmeter_model": "Hersteller Modell"` im selben Request stehen.

## Redispatch-Feedback

Die Antwort enthält zusätzlich `redispatch`. Es sind keine zusätzlichen
Request-Felder oder Client-Aufrufe nötig:

```json
{
  "redispatch": {
    "active": true,
    "affected_units": 3,
    "active_measures": 2,
    "data_updated_at": "2026-10-19T12:00:00Z"
  }
}
```

Ausgewertet werden bekannte Maßnahmen im **50-km-Luftlinienradius** um die
gesendeten Koordinaten während der Stunde vor `observed_at`. Ihr Zeitraum muss
das Fenster `[observed_at - 1h, observed_at)` überschneiden. Ein Ende genau
am Fensteranfang oder ein Beginn genau am Fensterende zählt nicht.
Offene Maßnahmen benötigen die aktuelle Aktiv-Kennung des Snapshots.

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `active` | Boolean oder `null` | `true` bei **mindestens drei Anlagen und mindestens zwei Maßnahmen** im vorliegenden Snapshot, auch bei unvollständiger Abdeckung. Unterhalb der Schwelle bei vollständigem, frischem Datenstand `false`, andernfalls `null`. |
| `affected_units` | Ganzzahl oder `null` | Bekannte unterschiedliche betroffene PV-/Wind-Anlagen; jede Anlage zählt einmal. Bekannte Treffer werden auch bei unvollständigen oder veralteten Daten zurückgegeben. |
| `active_measures` | Ganzzahl oder `null` | Bekannte unterschiedliche Maßnahmen, identifiziert durch Anbieter und Maßnahmen-ID; dieselbe Maßnahme an mehreren Anlagen zählt einmal. Bekannte Anzahlen werden auch bei unvollständigen oder veralteten Daten zurückgegeben. |
| `data_updated_at` | String oder `null` | UTC-Zeitstempel des veröffentlichten Snapshots (`generated_at`), nicht der Messannahme; ohne lesbaren Datenstand `null`. |

`active` beschreibt das Stundenfenster anhand des zuletzt vorliegenden Snapshots,
nicht zwingend eine jetzt noch laufende Maßnahme. Zwei Anlagen mit zwei Maßnahmen
oder drei Anlagen mit nur einer Maßnahme reichen nicht für `true`.
Radius, nächste Entfernung und `data_status` werden nicht ausgegeben.

**Unvollständige Daten verwerfen keine bekannten Treffer.** Reine Finished-Feeds
wie LEW und LSW liefern zählbare abgeschlossene Maßnahmen. Sie blockieren weder
bekannte Zähler noch eine positive Bewertung durch ausreichende Treffer.
Unterhalb der Schwelle gilt bei unvollständigen Daten beispielsweise:

```json
{
  "redispatch": {
    "active": null,
    "affected_units": 2,
    "active_measures": 1,
    "data_updated_at": "2026-10-19T12:00:00Z"
  }
}
```

Auch bekannte Zähler von 0 werden zurückgegeben; sie beweisen bei unvollständigen
Daten nicht die tatsächliche Abwesenheit weiterer Maßnahmen.

Die App liest ausschließlich den lokalen Snapshot; es gibt keinen Upstream-Aufruf
pro Messung. Es gelten `REDISPATCH_ENABLED` und der bisherige Datenpfad.
Nur bei deaktiviertem Feature, fehlendem/defektem Snapshot oder zukünftiger Messzeit
bleiben `active`, `affected_units` und `active_measures` jeweils `null`.
Ein lesbarer Datenzeitstempel bleibt erhalten.

Für `active: false` müssen alle im Snapshot konfigurierten Anbieter das komplette
Stundenfenster abdecken und aktuelle sowie abgeschlossene Maßnahmen liefern.
Snapshot und Current-Prüfung dürfen höchstens 2,5 Stunden, Finished-Prüfungen
höchstens 10 Stunden alt sein. Fehlgeschlagene Importe und reine Finished-Feeds
verhindern eine sichere negative Bewertung. Frische offene Current-Maßnahmen
dürfen für aktuelle Messungen nach der letzten Veröffentlichung weiter
berücksichtigt werden. Bei veralteten Daten beschreiben die Zähler und eine
daraus abgeleitete positive Bewertung den gespeicherten Stand, keine bestätigte
Live-Situation; `data_updated_at` muss entsprechend berücksichtigt werden.

Es zählen nur Maßnahmen mit zugeordneten Anlagenkoordinaten innerhalb der
verfügbaren Anbieterabdeckung, nicht sämtliche Maßnahmen in Deutschland.
Nähe bedeutet weder denselben Stromkreis noch eine Betroffenheit des Messpunkts.
Fehler dieser optionalen Auswertung verhindern keine gültige Messannahme und
ändern weder Spannungsbewertung noch Speicherladeempfehlung.
