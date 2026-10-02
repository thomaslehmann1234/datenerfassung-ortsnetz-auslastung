# evcc → Ortsnetz-Auslastung

Diese Integration verwendet dieselbe Messquelle wie evcc und sendet deren Netzspannungen alle fünf Minuten an die Ortsnetz-Auslastung-API. Unterstützt werden Shelly Gen2/3 EM-Geräte und generisches Modbus TCP.

evcc-Plugins lesen oder schreiben einzelne Gerätewerte, bieten aber keinen unabhängigen, periodischen HTTPS-Export. Das Script läuft deshalb neben evcc per cron oder Systemd-Timer. Es verändert die evcc-Konfiguration nicht.

## Voraussetzungen

- Python ab 3.8, nur Standardbibliothek
- Zugriff auf den Shelly oder Modbus-TCP-Zähler, der auch in evcc verwendet wird
- evcc ist optional: Das Script liest direkt vom Zähler und funktioniert auch ohne laufendes evcc.

## Installation

```sh
sudo install -d /opt/ortsnetz-auslastung
sudo install -m 755 ortsnetz_evcc.py /opt/ortsnetz-auslastung/
```

Im Konfigurationsblock mindestens `SOURCE`, `LATITUDE` und `LONGITUDE` setzen. Die Beispielkoordinaten zeigen auf Berlin-Mitte; die Anlagenleistung ist mit 10 kWp vorbelegt.

### Shelly Gen2/3

Für Shelly Pro 3EM oder Pro 3EM-400:

```python
SOURCE = "shelly"
SHELLY_HOST = "192.168.1.50"
SHELLY_EM_ID = 0
SHELLY_SINGLE_PHASE = False
SMARTMETER_MODEL = "Shelly Pro 3EM"
```

Das Script nutzt `EM.GetStatus` und die Felder `a_voltage`, `b_voltage`, `c_voltage` sowie optional `a_freq`. Für einen Pro EM50 `SHELLY_SINGLE_PHASE = True` setzen; L2 und L3 werden dann als `-1` übertragen.

### Modbus TCP

```python
SOURCE = "modbus"
MODBUS_HOST = "192.168.1.51"
MODBUS_UNIT_ID = 1
MODBUS_FUNCTION = 4
MODBUS_VALUE_TYPE = "float32"
MODBUS_WORD_SWAP = False
MODBUS_L1_REGISTER = 0
MODBUS_L2_REGISTER = 2
MODBUS_L3_REGISTER = 4
MODBUS_FREQUENCY_REGISTER = 6
SMARTMETER_MODEL = "Mein Modbus-Zähler"
```

Registeradressen sind nullbasiert: Die Herstelleradresse `30001` entspricht `0`. `MODBUS_FUNCTION` ist `4` für Input- und `3` für Holding-Register. Bei Geräten mit vertauschter 32-Bit-Registerreihenfolge `MODBUS_WORD_SWAP = True` setzen. Die Registerwerte und der Datentyp müssen zur bereits funktionierenden evcc-Meter-Konfiguration passen.

## Test und Betrieb

```sh
/usr/bin/python3 /opt/ortsnetz-auslastung/ortsnetz_evcc.py --dry-run
```

Bei korrektem Payload ohne `--dry-run` ausführen. Für fünf Minuten Intervall in `crontab -e` eintragen:

```cron
3-59/5 * * * * /usr/bin/python3 /opt/ortsnetz-auslastung/ortsnetz_evcc.py > /dev/null 2>&1
```

Die Umleitung nach `/dev/null` vermeidet dauerhafte Schreibzugriffe. Für eine kurze Fehlersuche kann die Ausgabe temporär nach `/tmp/ortsnetz-auslastung.log` umgeleitet werden; `/tmp` belegt jedoch RAM.

## evcc-Meter-Konfiguration

Die Quelle muss bereits in evcc als Netz-Zähler konfiguriert sein. Für einen eigenen Modbus-Zähler unterstützt evcc `type: custom` mit den Plugins `modbus` und `voltages`; für Shelly kann dessen integriertes Template oder ebenfalls ein HTTP-Plugin verwendet werden. Die Datenerfassung nutzt bewusst dieselbe direkte Quelle und nicht `/api/state`, weil die öffentliche evcc-State-API keine Netzspannungen garantiert.

- [evcc: eigene Geräte und Meter](https://docs.evcc.io/en/user-defined-devices/)
- [evcc: Plugin-Referenz](https://docs.evcc.io/de/reference/plugins/)
- [Shelly EM.GetStatus](https://shelly-api-docs.shelly.cloud/gen2/ComponentsAndServices/EM/)
