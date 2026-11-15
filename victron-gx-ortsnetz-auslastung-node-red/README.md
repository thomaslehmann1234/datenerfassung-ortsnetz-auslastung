# Ortsnetz-Auslastung für Victron GX (Node-RED)

Importierbarer Node-RED-Flow, der direkt auf einem Victron-GX-Gerät mit Venus OS Large läuft, zum Beispiel Cerbo GX. Er liest Netzspannungen und Frequenz über die Victron-Nodes und sendet die Messung 30 Sekunden nach dem Start und danach alle fünf Minuten an die Ortsnetz-Auslastung-API.

Der Flow macht dasselbe wie das Python-Script in [`victron-gx-ortsnetz-auslastung`](../victron-gx-ortsnetz-auslastung), braucht aber weder SSH noch Autostart-Eintrag.

## Inhalt

| Datei | Zweck |
|---|---|
| `Ortsnetz-Auslastung.json` | Node-RED-Flow zum Importieren |

## Voraussetzungen

- Victron GX mit **Venus OS Large** und aktiviertem Node-RED
- VE.Bus-Gerät (Multi/Quattro) oder Victron-Netzzähler
- Internetzugang des GX-Geräts
- Koordinaten des Messorts

Die benötigten Victron-Nodes (`@victronenergy/node-red-contrib-victron`) sind in Venus OS Large bereits installiert.

## Datenquellen

Der Flow verwendet in dieser Reihenfolge:

1. Netzzähler (`grid`-Nodes): `/Ac/L1..L3/Voltage` und `/Ac/Frequency`
2. VE.Bus (`vebus`-Nodes): `/Ac/ActiveIn/L1..L3/V` und `/Ac/ActiveIn/L1/F`

VE.Bus wird nur genutzt, wenn der Netzzähler keine gültige L1-Spannung liefert. Ungültige oder nicht vorhandene L2/L3-Phasen werden mit `-1` übertragen. Das ist für einphasige Messungen vorgesehen. Fehlt L1 oder ist L1 ungültig, wird nichts gesendet.

## Installation

1. Node-RED aktivieren: am GX *Einstellungen → Venus OS Large-Funktionen → Node-RED* einschalten. Node-RED ist danach unter `https://venus.local:1881` bzw. `https://<IP des GX>:1881` erreichbar.
2. In Node-RED *Menü → Importieren* wählen, `Ortsnetz-Auslastung.json` auswählen und importieren. Es entsteht ein Tab „Ortsnetz-Auslastung“.
3. Jeden der 8 blauen Victron-Nodes öffnen, das eigene Gerät auswählen und mit *Fertig* bestätigen. Im Flow sind `com.victronenergy.grid/30` und `com.victronenergy.vebus/276` voreingestellt; die Geräteinstanz kann bei dir anders sein.
   - Ohne Netzzähler die vier `grid`-Nodes löschen.
   - Bei einphasigen Anlagen können die L2/L3-Nodes bleiben oder gelöscht werden.
   - **Die Node-Namen (z. B. `grid L1`, `vebus F`) nicht ändern**, der Flow ordnet die Werte über diese Namen zu.
4. Den Function-Node **„Messung erstellen“** öffnen und im Konfigurationsblock mindestens `LATITUDE` und `LONGITUDE` anpassen.
5. *Übernahme (Deploy)* klicken.

Der Flow wird von Node-RED gespeichert und läuft nach einem Neustart oder Firmware-Update des GX automatisch weiter.

## Konfiguration

Im Function-Node „Messung erstellen“:

```js
const LATITUDE = 52.520008;
const LONGITUDE = 13.404954;
const PLANT_KWP = null;          // optional: tatsächliche installierte PV-Leistung in kWp
const PV_FORECAST_KWH = null;    // optional, z. B. 24.5
const SMARTMETER_MODEL = "Victron GX NodeRed";
const MAX_AGE_MS = 60 * 1000;    // ältere Werte gelten als ungültig
```

Das Sendeintervall (300 s) und die Verzögerung nach dem Start (30 s) stehen im Inject-Node „alle 5 min (erstmals nach 30 s)“.

Koordinaten lassen sich über [OpenStreetMap](https://www.openstreetmap.org/) bestimmen: Ort suchen, mit der rechten Maustaste auf die Karte klicken und **„Abfrage starten“** wählen. Siehe auch [Koordinaten](https://github.com/thomaslehmann1234/datenerfassung-ortsnetz-auslastung#koordinaten).

## Aufbau des Flows

| Node | Aufgabe |
|---|---|
| `grid …` / `vebus …` | Victron-Input-Nodes; liefern die Werte etwa alle 5 Sekunden |
| Werte speichern | Merkt sich jeden Wert mit Zeitstempel im Flow-Kontext |
| alle 5 min (erstmals nach 30 s) | Löst die Messung aus |
| Messung erstellen | Wählt die Quelle, prüft und rundet die Werte und baut den Payload |
| Messung merken | Hebt den gesendeten Payload für die Auswertung auf |
| POST measurements | Sendet an `https://www.ortsnetz-auslastung.de/v1/measurements` |
| Ergebnis | Zeigt das Ergebnis als Status unter dem Node und meldet Fehler im Debug-Fenster |

## Verhalten und Validierung

- Spannungen werden nur zwischen **150 und 300 V** akzeptiert und auf 0,1 V gerundet, sonst als `-1` übertragen.
- Die Frequenz wird nur bei **45–55 Hz** mitgesendet und auf 0,01 Hz gerundet.
- Werte, die länger als `MAX_AGE_MS` (Standard 60 s) nicht aktualisiert wurden, gelten als ungültig, zum Beispiel wenn ein Gerät getrennt wurde.
- `PLANT_KWP` und `PV_FORECAST_KWH` werden nur übertragen, wenn sie gesetzt sind.
- Als `integration_version` wird `venus-nodered-0.1.0` gesendet.

## Kontrolle im Betrieb

Unter dem Node **„Ergebnis“** steht nach jeder Übertragung der Status, zum Beispiel:

```
OK (grid): L1=230.1 L2=229.8 L3=230.5 V, f=50.01 Hz -> green
```

Grün bedeutet Ampel „green“, blau eine andere Ampelfarbe, rot einen Fehler. Unter „Messung erstellen“ steht die zuletzt verwendete Quelle mit den Spannungen.

## Fehleranalyse

Warnungen erscheinen im Debug-Fenster von Node-RED.

- `Keine gültige L1-Spannung`: Victron-Node ohne ausgewähltes Gerät, falsche Geräteinstanz, Node-Name geändert oder das Gerät liefert keinen plausiblen L1-Wert.
- `HTTP ...`: Die API hat den Request abgelehnt, zum Beispiel wegen ungültiger Koordinaten; die Antwort steht in der Warnung.
- `Übertragung fehlgeschlagen`: Internetzugang, DNS und Systemzeit des GX-Geräts prüfen.
- Victron-Node zeigt „disconnected“: Gerät im Node neu auswählen und deployen.

## Datenschutz

Gesendet werden ausschließlich Zeitstempel, Standort, Spannungen/Frequenz und optionale Angaben (Anlagengröße, PV-Prognose, Zählermodell, Integrationsversion). Einzelheiten zur Datenverarbeitung: [Methodik & Datenschutz](https://www.ortsnetz-auslastung.de/methodik).
