# Ortsnetz-Auslastung für Shelly Pro 3EM

Ein Shelly-Script, das die drei Netzspannungen eines Shelly Pro 3EM oder Pro 3EM-400 direkt an die Ortsnetz-Auslastung-API überträgt. Es sendet sofort nach dem Start und danach alle fünf Minuten.

Es gibt keine Cloud-Abhängigkeit, keine lokale Datenhaltung und keine Wiederholungslogik: Ist die API einmal nicht erreichbar, erfolgt der nächste Versuch regulär fünf Minuten später.

## Voraussetzungen

- Shelly **Pro 3EM**, **Pro 3EM-400**, **PlusPlugS / PlugS Gen2+**, **PM1 / PM Mini** mit aktueller Firmware und aktivierter Script-Funktion.
- Der Shelly muss per NTP die korrekte Uhrzeit beziehen; der Server verlangt einen ISO-8601-Zeitstempel.
- Netzanschluss mit Sternpunkt/Neutralleiter, entsprechend dem Einsatzbereich des jeweiligen Shelly-Modells.
- Internetzugriff des Shelly auf `https://www.ortsnetz-auslastung.de`.
- Breitengrad und Längengrad des Messortes.

Der klassische Shelly 3EM (Gen1) kann keine Shelly Scripts ausführen und wird von diesem Repository nicht unterstützt.

## Installation

1. Öffne die Weboberfläche des Shelly und wechsle zu **Scripts**.
2. Erstelle ein neues Script, beispielsweise `ortsnetz-auslastung`.
3. Kopiere den Inhalt vom für den entsprechenden Shelly passenden Script in den Editor.
4. Passe im Block `CONFIG` mindestens `latitude` und `longitude` an. Die API-Adresse kann normalerweise unverändert bleiben. Details weiter unten > Standortkoordinaten finden
5. Speichere das Script, starte es und aktiviere **Run on startup**.

### Standortkoordinaten finden

Öffne [OpenStreetMap](https://www.openstreetmap.org/), suche nach deinem Ort oder deiner Adresse und zoome auf den Messort. Ein Rechtsklick auf den gewünschten Punkt zeigt die Koordinaten; über **Adresse anzeigen** > **Intern** lassen sie sich kopieren. Übernimm sie im Dezimalformat in den `CONFIG`-Block, zum Beispiel:

```javascript
latitude: 52.510607,
longitude: 13.389853,
```

Verwende bei Bedarf einen leicht versetzten Punkt, wenn du den exakten Standort nicht übertragen möchtest. Der Ort und die Straße sollten jedoch stimmen. 

## Einphasige Messung (PlusPlug / PlugS / PM1 / PM Mini)
Sollte bekannt sein, an welcher Phase der Shelly angeschlossen ist, kann das jeweilige Script auch entsprechend angepasst werden.

Hierfür in der Funktion `sendMeasurement` bei `let payload` die Angaben wie folgt anpassen:

| Phase L1 | Phase L2 | Phase L3 |
| --- | --- | --- |
| `l1_v: em.voltage,` | `l1_v: -1,` | `l1_v: -1,` |
| `l2_v: -1,` | `l2_v: em.voltage,` | `l2_v: -1,` |
| `l3_v:-1,` | `l3_v: -1,`  | `l3_v: em.voltage,` |

## Übertragene Messwerte

Je nach Script werden `em:0`, `switch:0` oder `PM1:0` ausgelesen:

| Ortsnetz-Wert | Shelly-Wert | Bemwerkung
| --- | --- | --- |
| L1 | `a_voltage` | `voltage` wenn vom Shelly nur L1 gemessen wird |
| L2 | `b_voltage` | `-1` wenn vom Shelly nur L1 gemessen wird |
| L3 | `c_voltage` | `-1` wenn vom Shelly nur L1 gemessen wird |
| Netzfrequenz | `a_freq` | oder `freq` jedoch nur, wenn vom Shelly gemessen |

Es überträgt nur Spannungen zwischen 150 und 300 V. Die Frequenz wird nur gesendet, wenn sie zwischen 45 und 55 Hz liegt.

## Prüfung

Nach dem Start sollte die Shelly-Konsole keine Fehlermeldung ausgeben. Ein Messpunkt erscheint sofort in der Ortsnetz-Karte; die Live-Karte kann bis zu 15 Minuten benötigen. Bei HTTP-Fehlern schreibt das Script den Status in die Shelly-Konsole.

## Datenschutz

Übertragen werden Zeitstempel, Koordinaten, Smartmeter-Modell und Script-Version, sowie, je nach Shelly-Modell, die L1/L2/L3-Spannungen und die Netzfrequenz. Die Karte zeigt Koordinaten nur gerastert mit etwa 100 Metern Genauigkeit.

## Quellen

- [Shelly EM-Komponente](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM/)
- [Shelly Scripts](https://shelly-api-docs.shelly.cloud/gen2/Scripts/Overview/)
