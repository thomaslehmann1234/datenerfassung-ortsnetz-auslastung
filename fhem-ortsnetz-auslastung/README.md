# FHEM

Ein einzelnes FHEM-`at` liest drei vorhandene Spannungs-Readings und optional die Netzfrequenz. Die Werte werden alle fünf Minuten per HTTPS an die Ortsnetz-Auslastung-API gesendet. Die Antwort der API (Ampel, Speicherladeempfehlung, Redispatch) wird als Readings am `at` abgelegt. Ein eigenes Modul oder Einträge in `99_myUtils.pm` sind nicht nötig.

- Datei: [`at_ortsnetz.txt`](at_ortsnetz.txt)
- Voraussetzungen: FHEM, Geräte mit Spannungs-Reading (z. B. Shelly, Smart-Meter-Lesekopf oder Wechselrichter, je eines pro Phase), Perl-Modul `IO::Socket::SSL` für HTTPS, aktuelle CA-Zertifikate des Systems (z. B. Paket `ca-certificates`), Internetzugang

## Einrichtung

1. Ein leeres `at` anlegen, zum Beispiel über die Kommandozeile:

   ```
   defmod at_ortsnetz at +*00:05:00 { }
   ```

2. Im Device auf **DEF** klicken und den kompletten Inhalt von [`at_ortsnetz.txt`](at_ortsnetz.txt) einfügen, von `+*00:05:00 {` bis zur letzten `}`. Danach mit **modify** speichern.

   **Hinweis:** Der Code verwendet einfache Semikolons und gehört deshalb in das Feld DEF. In der Kommandozeile und in der `fhem.cfg` trennt FHEM Befehle an `;`. Dort müsste jedes `;` als `;;` geschrieben werden.

3. Im DEF die Werte im Block **Konfiguration** anpassen:
   - `$lat` und `$lon`: ungefährer Standort, siehe Abschnitt Koordinaten im [Haupt-README](../README.md)
   - `@src`: pro Phase Device-Name und Reading mit der Spannung in Volt, je nach Gerät z. B. `voltage` oder `voltage_0`. Für eine nicht gemessene Phase `[]` eintragen; sie wird als `-1` gesendet.
   - `@freq`: Device und Reading der Netzfrequenz in Hz, `()` wenn nicht vorhanden
   - `$alle`: `1` sendet nur, wenn alle konfigurierten Phasen gültig sind (Standard). `0` sendet auch, wenn einzelne Phasen fehlen, und meldet diese als `-1`.
   - `$model`: optional Hersteller und Modell des Messgeräts. Es wird einmalig gesendet und nach einer Änderung erneut.

4. Mit `set at_ortsnetz execNow` sofort testen. Bei Erfolg steht im Reading `api_status` der Wert `HTTP 202`.

Den Gerätenamen ermittelt der Code selbst, das `at` kann also beliebig heißen.

## Verhalten

- Gesendet wird alle fünf Minuten.
- Ein Spannungswert gilt als gültig, wenn er größer als 0 und höchstens 500 V ist und das Reading nicht älter als 10 Minuten ist. Für die Frequenz gelten 45 bis 55 Hz und dieselbe Altersgrenze.
- Übertragen werden `l1_v`, `l2_v`, `l3_v` und, falls vorhanden, `grid_frequency_hz`. Dazu kommen `integration_version` (`fhem-0.3`) und einmalig `smartmeter_model`.
- Readings am `at`:
  - `l1_v`, `l2_v`, `l3_v`: Rohwerte, auch ungültige
  - `api_status`: `HTTP 202` bei Annahme, sonst Fehler oder Grund für das Überspringen
  - `gueltig`: `1`, wenn die folgenden Werte aus der letzten erfolgreichen Antwort stammen, sonst `0`
  - `ampel`, `ampel_l1` … `ampel_l3`: Spannungsbewertung der API, bei Fehlern `ungueltig`
  - `speicher_empfehlung`: `charge`, `discharge` oder `none`, siehe [API.md](../API.md), bei Fehlern `ungueltig`
  - `redispatch`: `ja`, `nein` oder `unbekannt`
- Bei Fehlern steht mit `verbose 3` ein Eintrag im Log, mit `verbose 5` auch der gesendete Datensatz und die Antwort des Servers.
- Die Übertragung läuft nicht blockierend (`HttpUtils_NonblockingGet`).
- HTTPS mit Prüfung von Serverzertifikat und Hostname. Schlägt die Prüfung fehl, steht der Grund in `api_status`, und es wird nichts übertragen.

## Gültigkeit

Kommt keine gültige Antwort (Timeout, HTTP-Fehler wie 403 oder 422, unlesbare Antwort) oder wird wegen ungültiger oder veralteter Spannungswerte nichts gesendet, setzt der Code `gueltig` auf `0`, `ampel*` und `speicher_empfehlung` auf `ungueltig` und `redispatch` auf `unbekannt`. Alte Empfehlungen bleiben so nicht stehen.

Eine Speichersteuerung sollte eine Empfehlung nur verwenden, wenn `gueltig` gleich `1` ist und der Wert frisch ist, z. B. höchstens 10 Minuten alt (zwei Sendeintervalle). Fällt FHEM oder das `at` ganz aus, wird nichts mehr geschrieben; das fängt nur die Altersprüfung ab. Beispiel als DEF eines `notify` (einfache Semikolons, wie oben beim `at`):

```
at_ortsnetz:speicher_empfehlung:.* {
  return if (ReadingsVal('at_ortsnetz', 'gueltig', 0) ne '1');
  return if (ReadingsAge('at_ortsnetz', 'speicher_empfehlung', 99999) > 600);
  # ... Speicher je nach $EVTPART1 (charge/discharge/none) steuern
}
```

## Hinweise

- Jedes Gerät sollte dauerhaft derselben Phase zugeordnet bleiben, damit die Messreihe konsistent bleibt.
- Die Spannung wird dort gemessen, wo das Gerät angeschlossen ist. Ein Gerät nahe am Hausanschluss liefert aussagekräftigere Werte als eines am Ende einer langen Leitung.
- Leistung am Hausanschluss oder Akkustand werden bewusst nicht gesendet. Nach [API.md](../API.md) darf `grid_power_w` nicht durch Wechselrichterleistung ersetzt werden; wer einen passenden Zählerwert hat, kann den Block entsprechend erweitern.
