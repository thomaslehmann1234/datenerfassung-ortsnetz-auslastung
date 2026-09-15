# Ortsnetz-Auslastung für Tasmota

Dieses Projekt sendet die am optischen Lesekopf empfangenen SML-Messwerte eines Stromzählers direkt an die Ortsnetz-Auslastung-API. Es benötigt keinen MQTT-Broker und keine weitere Middleware.

## Voraussetzungen

- Ein **ESP32** mit Tasmota und optischem IR-Lesekopf. Der direkte API-Aufruf nutzt HTTPS; für ESP8266 unterstützt `WebQuery` nur unverschlüsseltes HTTP.
- Eine selbst kompilierte Tasmota-Firmware. Smart Meter Interface und Tasmota-Scripting sind nicht Teil der vorgefertigten Firmware-Images.
- Ein Zähler, der über die optische Schnittstelle SML-Telegramme sendet und die benötigten Phasenspannungen ausgibt. Häufig muss dafür beim Messstellenbetreiber eine PIN angefordert und die Info-Schnittstelle am Zähler freigeschaltet werden.
- WLAN-Zugang und NTP-Zeitabgleich.

## Firmware bauen

Folgendes in `user_config_override.h` ergänzen und ein ESP32-Image bauen:

```c
#ifndef USE_SCRIPT
#define USE_SCRIPT
#endif
#ifndef USE_SML_M
#define USE_SML_M
#endif
#ifdef USE_RULES
#undef USE_RULES
#endif
```

## Installation

1. Lesekopf auf die optische Schnittstelle des Zählers setzen und dessen RX-Leitung mit einem freien ESP32-GPIO verbinden.
2. In Tasmota unter **Configuration → Configure Module** diesen GPIO auf `None` setzen. Der Smart-Meter-Descriptor steuert den Pin selbst.
3. In der Tasmota-Konsole einmalig ausführen:

   ```text
   Time 0
   Timezone 0
   TelePeriod 300
   ```

   `Timezone 0` ist wichtig: Das Script hängt `Z` an Tasmotas lokalen Zeitstempel an und überträgt damit einen ISO-8601-Zeitstempel in UTC.

4. [ortsnetz-auslastung.tasmota](ortsnetz-auslastung.tasmota) in **Consoles → Edit Script** einfügen, eigene `latitude` und `longitude` setzen und speichern. Koordinaten lassen sich z. B. mit [OpenStreetMap](https://www.openstreetmap.org/) bestimmen: Standort suchen, Rechtsklick auf die Karte und **„Abfrage starten“** wählen.
5. Falls nötig, in der `>M`-Sektion RX-GPIO und Baudrate an den Lesekopf/Zähler anpassen. Das mitgelieferte Beispiel ist für binäres SML mit 9600 Baud und GPIO 3.
6. Mit `sensor53 d1` in der Tasmota-Konsole die Rohdaten prüfen. Mit `sensor53 d0` den Debug-Modus wieder beenden. Sobald alle vier Decoderwerte eintreffen, wird alle fünf Minuten ein Upload ausgelöst.

## Unterstützte Messwerte

Das schlanke Script übermittelt ausschließlich:

- Zeitpunkt (`observed_at`)
- Standort (`latitude`, `longitude`)
- Spannung L1/L2/L3 in Volt
- Netzfrequenz in Hertz, sofern der Zähler OBIS `1-0:14.7.0` ausgibt
- Integrationsversion

Es sendet keine Zählernummer, keine Verbrauchs- oder Einspeisewerte und keine WLAN-/Gerätekennung.

## Zähler-Kompatibilität

Die OBIS-Codes im Beispiel sind bei deutschen SML-fähigen Zählern üblich:

| Wert | OBIS |
| --- | --- |
| Spannung L1 | `1-0:32.7.0` |
| Spannung L2 | `1-0:52.7.0` |
| Spannung L3 | `1-0:72.7.0` |
| Frequenz | `1-0:14.7.0` |

Nicht jeder Zähler gibt Phasenwerte aus. Fehlen sie, sendet das Script absichtlich nichts. Bei einem anderen Protokoll, einer anderen Baudrate oder abweichenden OBIS-Werten müssen nur die Zeilen in der `>M`-Sektion angepasst werden.

## Fehleranalyse

- `sensor53 d1` zeigt keine Daten: GPIO, Lesekopf-Ausrichtung, PIN-Freischaltung, Baudrate und das Zählerprotokoll prüfen.
- Es erscheinen Daten, aber kein Upload: `Timezone 0`, NTP/WLAN und die Spannungswerte prüfen. Das Script ignoriert Werte außerhalb von 150–300 V.
- Bei `duplicate GPIO defined`: Der RX-Pin ist parallel in der Tasmota-Modulkonfiguration belegt; ihn dort auf `None` setzen und Tasmota neu starten.
- HTTPS-Fehler auf ESP8266: Ein ESP32 verwenden oder einen eigenen HTTP→HTTPS-Proxy im lokalen Netz bereitstellen.

## Quellen

- [Tasmota Smart Meter Interface](https://tasmota.github.io/docs/Smart-Meter-Interface/)
- [Tasmota Scripting Language](https://tasmota.github.io/docs/Scripting-Language/)
- [Tasmota WebQuery command](https://tasmota.github.io/docs/Commands/)
