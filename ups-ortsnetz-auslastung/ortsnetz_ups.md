# USV-Spannungsmessung für Ortsnetz-Auslastung

Dieses kleine Shellscript liest über **NUT (Network UPS Tools)** die aktuelle Eingangsspannung einer USV aus und sendet den Messwert an:

`https://www.ortsnetz-auslastung.de`

Die Idee ist, bereits vorhandene USVs als zusätzliche Messquelle für die lokale Netzspannung zu nutzen.

Getestet wurde das Setup mit einer **APC Back-UPS RS 550G**, die per USB an einer QNAP hängt.

## ⚠️ Benutzung auf eigene Gefahr!

**Benutzung auf eigene Gefahr!**

Das Script greift auf die lokale NUT-/USV-Konfiguration zu und sendet Messdaten an einen externen Dienst.

Vor dem Einsatz sollte geprüft werden:

- ob `upsc` auf dem eigenen System korrekt funktioniert
- ob die ausgelesenen Werte plausibel sind
- ob die verwendeten Koordinaten korrekt bzw. ausreichend anonymisiert sind
- ob das Script auf dem eigenen NAS / Server dauerhaft ausgeführt werden soll

Für Schäden, Fehlkonfigurationen, falsche Messwerte oder unerwünschte Datenübertragungen wird keine Haftung übernommen.

## Voraussetzungen

Benötigt werden:

- eine von NUT unterstützte USV
- `upsc`
- `curl`
- Shell-Zugriff auf das System
- Internetzugang

Zuerst prüfen, welche USV in NUT vorhanden ist:

```bash
upsc -l
```

Beispiel:

```text
qnapups
```

Danach testen, ob die Eingangsspannung verfügbar ist:

```bash
upsc qnapups input.voltage
```

Beispiel:

```text
236.0
```

Optional kann auch der Status geprüft werden:

```bash
upsc qnapups ups.status
```

Beispiel:

```text
ALARM OL RB OFF
```

Für das Script ist insbesondere `OL` relevant. Das steht für **On Line** und zeigt an, dass die USV aktuell vom Stromnetz versorgt wird.

## Installation

Script zum Beispiel unter folgendem Pfad speichern:

```text
/share/Public/ortsnetz-ups.sh
```

Danach ausführbar machen:

```bash
chmod +x /share/Public/ortsnetz-ups.sh
```

## Konfiguration

Im Script müssen mindestens folgende Werte angepasst werden:

```bash
UPS_NAME="qnapups"

LATITUDE="XX.XXX"
LONGITUDE="X.XXX"
```

`UPS_NAME` entspricht dem Namen aus:

```bash
upsc -l
```

Bei den Koordinaten muss nicht zwingend die exakte Hausposition verwendet werden. Für die Ortsnetz-Auswertung kann eine leicht gerundete Position sinnvoll sein.

## Manueller Test

Vor der Einrichtung von Cron sollte das Script einmal manuell ausgeführt werden:

```bash
/share/Public/ortsnetz-ups.sh
```

Danach das Log prüfen:

```bash
tail -n 10 /share/Public/ortsnetz-ups.log
```

Bei erfolgreicher Übertragung sollte unter anderem ein HTTP-Status `202` erscheinen:

```text
2026-10-01T17:20:00Z voltage=236.0 status="OL" http=202
```

`202 Accepted` bedeutet, dass die Messung von der API angenommen wurde.

## Automatische Ausführung mit Cron

Für eine Messung alle fünf Minuten kann folgender Cronjob verwendet werden:

```cron
*/5 * * * * /share/Public/ortsnetz-ups.sh
```

Das entspricht auch dem Messintervall vieler anderer Integrationen des Ortsnetz-Auslastung-Projekts.

Je nach System muss darauf geachtet werden, dass Änderungen an der Crontab einen Neustart überleben. Das gilt insbesondere für einige NAS-Systeme wie QNAP.

## Welche Werte werden übertragen?

Bei einer einphasigen USV wird die Eingangsspannung als
