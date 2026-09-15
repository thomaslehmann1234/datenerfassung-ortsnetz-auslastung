# Ortsnetz-Auslastung für Shelly Pro 3EM

Ein Shelly-Script, das die drei Netzspannungen eines Shelly Pro 3EM oder Pro 3EM-400 direkt an die Ortsnetz-Auslastung-API überträgt. Es sendet sofort nach dem Start und danach alle fünf Minuten.

Es gibt keine Cloud-Abhängigkeit, keine lokale Datenhaltung und keine Wiederholungslogik: Ist die API einmal nicht erreichbar, erfolgt der nächste Versuch regulär fünf Minuten später.

## Voraussetzungen

- Shelly **Pro 3EM** oder **Pro 3EM-400** mit aktueller Firmware und aktivierter Script-Funktion.
- Der Shelly muss per NTP die korrekte Uhrzeit beziehen; der Server verlangt einen ISO-8601-Zeitstempel.
- Netzanschluss mit Sternpunkt/Neutralleiter, entsprechend dem Einsatzbereich des Shelly Pro 3EM.
- Internetzugriff des Shelly auf `https://www.ortsnetz-auslastung.de`.
- Breitengrad und Längengrad des Messortes.

Der klassische Shelly 3EM (Gen1) kann keine Shelly Scripts ausführen und wird von diesem Repository nicht unterstützt.

## Installation

1. Öffne die Weboberfläche des Shelly und wechsle zu **Scripts**.
2. Erstelle ein neues Script, beispielsweise `ortsnetz-auslastung`.
3. Kopiere den Inhalt von [`ortsnetz-auslastung.js`](ortsnetz-auslastung.js) in den Editor.
4. Passe im Block `CONFIG` mindestens `latitude` und `longitude` an. Die API-Adresse kann normalerweise unverändert bleiben. Details weiter unten > Standortkoordinaten finden
5. Speichere das Script, starte es und aktiviere **Run on startup**.

### Standortkoordinaten finden

Öffne [OpenStreetMap](https://www.openstreetmap.org/), suche nach deinem Ort oder deiner Adresse und zoome auf den Messort. Ein Rechtsklick auf den gewünschten Punkt zeigt die Koordinaten; über **Adresse anzeigen** > **Intern** lassen sie sich kopieren. Übernimm sie im Dezimalformat in den `CONFIG`-Block, zum Beispiel:

```javascript
latitude: 52.510607,
longitude: 13.389853,
```

Verwende bei Bedarf einen leicht versetzten Punkt, wenn du den exakten Standort nicht übertragen möchtest. Der Ort und die Straße sollen stimmen. 

## Übertragene Messwerte

Das Script liest `em:0` aus:

| Ortsnetz-Wert | Shelly-Pro-3EM-Wert |
| --- | --- |
| L1 | `a_voltage` |
| L2 | `b_voltage` |
| L3 | `c_voltage` |
| Netzfrequenz | `a_freq` |

Es überträgt nur Spannungen zwischen 150 und 300 V. Die Frequenz wird nur gesendet, wenn sie zwischen 45 und 55 Hz liegt.

## Prüfung

Nach dem Start sollte die Shelly-Konsole keine Fehlermeldung ausgeben. Ein Messpunkt erscheint sofort in der Ortsnetz-Karte; die Live-Karte kann bis zu 15 Minuten benötigen. Bei HTTP-Fehlern schreibt das Script den Status in die Shelly-Konsole.

## Datenschutz

Übertragen werden Zeitstempel, Koordinaten, L1/L2/L3-Spannung, Netzfrequenz, Smartmeter-Modell und Script-Version. Die Karte zeigt Koordinaten nur gerastert mit etwa 100 Metern Genauigkeit.

## Quellen

- [Shelly EM-Komponente](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM/)
- [Shelly Scripts](https://shelly-api-docs.shelly.cloud/gen2/Scripts/Overview/)
