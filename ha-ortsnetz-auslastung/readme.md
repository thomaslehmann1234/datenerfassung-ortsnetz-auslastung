# ortsnetz-auslastung.de mit Homeassistant Boardmitteln

Diese Dateien beinhalten Konfiguration im yaml Format und sind an den relevanten Stellen kommentiert zur besseren Nachvollziehbarkeit.

Die Datein müssen an 2 Stellen in Homeassistant eingearbeitet werden, um den Automatismus zum Senden von Daten an die ortsnetz-auslastung.de API zu aktivieren.

## configuration.yaml

Diese Datei enthält die notwendigen Einrichtung des `ortsnetz-auslastung.de` API Endpunktes als sogenanntes `rest_command`, siehe [Homeassistant RESTful Command](https://www.home-assistant.io/integrations/rest_command/). 

Dieser Abschnitt muss in die globale Homeassistant-Konfiguration eingearbeitet werden. Typischerweise wird dazu eine Datei namens "configuration.yaml" bearbeitet, siehe [Homeassistant Configuration](https://www.home-assistant.io/docs/configuration/)

## ortsnetz-auslastung.yaml

Der Aktionsname lautet `rest_command.ortsnetz_auslastung_de`. Bei bestehenden Installationen den bisherigen Namen mit Bindestrichen sowohl in `configuration.yaml` als auch im Automationsaufruf durch Unterstriche ersetzen. Die API-URL bleibt unverändert. Anschließend die RESTful-Command-Konfiguration und die Automation neu laden oder Home Assistant neu starten.

Diese Datei enthält die Beschreibung eines Automatismus. Der Inhalt kann vollständig in den YAML-Editor einer neuen Automatisierung kopiert werden.

Über die Homeassistant Web-Ansicht:

`Einstellungen > Automtisierungen > Automatisierung erstellen > neue Automatisierung > 3 Punkte Menü (⋮) > YAML bearbeiten`.

Nachdem die Inhalte eingefügt wurden, kann die Automatisierung im visuellen Editor weiter bearbeitet werden.

### Einrichtung: nur Schritt 1 „Konfiguration“ anpassen

Die eigenen Sensoren werden an genau einer Stelle eingetragen: im ersten Schritt der Aktionen, „Konfiguration“. Alle weiteren Schritte lesen ihre Werte daraus und müssen nicht angepasst werden.

```yaml
l1_voltage: sensor.ksem_l1_voltage
l2_voltage: sensor.ksem_l2_voltage
l3_voltage: sensor.ksem_l3_voltage
frequency: sensor.ksem_netzfrequenz
location_zone: zone.home
max_age_minutes: 10
```

- **1, 2 oder 3 Phasen:** Für eine nicht vorhandene Phase `""` eintragen. Sie wird gemäß API mit `-1` gesendet. Beispiel: zwei Mikrowechselrichter auf L1 und L2 → `l3_voltage: ""`.
- **Ohne Frequenzsensor:** `frequency: ""`. Das optionale Feld wird dann weggelassen.
- **Optionale Zusatzfelder** wie `plant_capacity_kwp`, `pv_forecast_kwh` oder `smartmeter_model` unter `optional_fields` aktivieren.

### Umgang mit fehlenden Messwerten

Jeder Messwert wird einzeln geprüft. Übernommen wird er nur, wenn der Sensor existiert, eine Zahl im erlaubten Bereich liefert (Spannung über 0 bis 500 V, Frequenz 45 bis 55 Hz) und nicht älter als `max_age_minutes` ist.

| Situation | Gesendet wird |
| --- | --- |
| Phase `unavailable`, `unknown`, `0 V` oder veraltet | `-1` für diese Phase |
| Frequenz fehlt, ungültig oder veraltet | Feld `grid_frequency_hz` entfällt |
| Keine einzige gültige Phase (z.B. nachts alle Mikrowechselrichter aus) | nichts; Warnung im System Log |

Die Altersprüfung verhindert, dass ein abgeschalteter Mikrowechselrichter morgens und abends seinen letzten Wert weiter liefert. Meldet eine Integration unveränderte Werte nicht neu und gilt deshalb fälschlich als veraltet, schaltet `max_age_minutes: 0` die Prüfung ab.

## Tests

Mit installiertem Home Assistant und PyYAML prüft `python3 test_templates.py` die beiden YAML-Dateien gegen die Home-Assistant-Schemas und kontrolliert, dass Definition und Aufruf denselben Aktionsnamen verwenden.
