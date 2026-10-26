# E3/DC Ortsnetz-Auslastung Integration

Dieses Python-Skript liest die aktuellen Phasenspannungen (L1, L2, L3) und die Netzfrequenz lokal über das RSCP-Protokoll von einem E3/DC-Hauskraftwerk aus und sendet die Messwerte an das Projekt **Ortsnetz-Auslastung** (`ortsnetz-auslastung.de`).

---

## 📋 Voraussetzungen

* **Python:** Version 3.7 oder höher
* **Netzwerk:** Lokaler Zugriff auf das E3/DC Hauskraftwerk über dessen IP-Adresse
* **E3/DC-Zugang:** 
  * Zugangsdaten zum E3/DC-Portal (Benutzername & Passwort)
  * Lokaler RSCP-Schlüssel (kann am Display des E3/DC unter *Einstellungen > Personalisieren* eingerichtet/eingesehen werden)

---

## ⚙️ Installation

1. **Repository klonen / Skript herunterladen:**
   Sichere das Skript `e3dc_ortsnetz.py` im gewünschten Verzeichnis.

2. **Abhängigkeiten installieren:**
   Das Skript benötigt das `e3dc`-Python-Modul zur Kommunikation über RSCP.

   ```bash
   pip install pye3dc
   ```

---

## 🔧 Konfiguration

Öffne die Datei `e3dc_ortsnetz.py` in einem Texteditor und passe den Konfigurationsbereich an:

```python
# --- Konfiguration ---
E3DC_IP   = "IP_Adresse"     # IP-Adresse deines E3/DC Kraftwerks
E3DC_USER = "deine_email@domain.de"  # E3/DC Portal-Benutzername
E3DC_PASS = "dein_passwort"      # E3/DC Portal-Passwort
RSCP_KEY  = "dein_rscp_key"      # Lokales RSCP-Passwort

# Geografischer Standort (Dezimalgrad)
LATITUDE  = 45.0000            # Breitengrad
LONGITUDE = 8.0000            # Längengrad
```


---

## 🚀 Benutzung

### Manueller Testlauf

Starte das Skript manuell im Terminal, um die Funktion zu überprüfen:

```bash
python3 e3dc_ortsnetz.py
```

**Erfolgreiche Ausgabe:**
```text
Verbinde mit E3/DC...
Rufe Zählerdaten ab...
Gelesene Werte: L1=230.15V, L2=231.02V, L3=229.85V | Frequenz: 50.0Hz
Erfolgreich übertragen (202): L1=230.15V, L2=231.02V, L3=229.85V | Frequenz: 50.0Hz
```

---

## ⏱️ Automatisierung (Cronjob)

Um regelmäßige Messwerte zu liefern, kannst du das Skript z. B. alle 5 bis 15 Minuten per `cron` ausführen lassen:

1. Crontab öffnen:
   ```bash
   crontab -e
   ```

2. Zeile hinzufügen (Beispiel für eine Übertragung alle 5 Minuten):
   ```cron
   */5 * * * * /usr/bin/python3 /pfad/zu/deinem/skript/e3dc_ortsnetz.py >/dev/null 2>&1
   ```

---

## 🛠️ Funktionsweise

1. **RSCP-Verbindung:** Stellt eine lokale Verbindung zum E3/DC-Hauskraftwerk her und fragt die Zählerdaten (`get_powermeters_data()`) ab.
2. **Datenextraktion:** Identifiziert den Netzzähler (Grid Meter) und extrahiert die Effektivspannungen L1, L2, L3 sowie optional die Netzfrequenz f.
3. **Plausibilitätsprüfung:** Stellt sicher, dass die Phasenspannungen im realistischen Bereich von 150V bis 300V liegen.
4. **Übertragung:** Sendet den Payload via HTTP POST (JSON) an die API unter `https://www.ortsnetz-auslastung.de/v1/measurements`.
