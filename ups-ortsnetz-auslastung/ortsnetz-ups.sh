#!/bin/sh

# ------------------------------------------------------------
# Ortsnetz-Auslastung per NUT / USV
#
# Liest die Eingangsspannung einer per NUT angebundenen USV aus
# und sendet den Messwert an:
#
#   https://www.ortsnetz-auslastung.de
#
# Gedacht für einphasige USVs, z. B. APC Back-UPS an QNAP/NAS.
#
# Voraussetzung:
#   - NUT / upsc ist installiert und erreichbar
#   - curl ist vorhanden
#   - Die USV liefert "input.voltage"
#
# Beispiel:
#   upsc qnapups input.voltage
#   236.0
#
# Empfohlenes Intervall:
#   alle 5 Minuten per cron
# ------------------------------------------------------------


# PATH explizit setzen, da Cron oft mit eingeschränktem PATH läuft
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin
export PATH


# ------------------------------------------------------------
# Konfiguration
# ------------------------------------------------------------

# Name der USV in NUT
# Mit "upsc -l" können die verfügbaren Geräte angezeigt werden.
UPS_NAME="qnapups"

# Standort des Messpunkts
#
# Bitte hier die eigenen Koordinaten eintragen.
# Beispiel:
# LATITUDE="50.775"
# LONGITUDE="7.190"
#
# Für die Ortsnetz-Auswertung reicht in der Regel eine leicht
# gerundete Position. Die exakte Hausposition ist nicht notwendig.
LATITUDE="XX.XXX"
LONGITUDE="X.XXX"

# API-Endpunkt
API_URL="https://www.ortsnetz-auslastung.de/v1/measurements"

# Lokale Logdatei
LOG="/share/Public/ortsnetz-ups.log"


# ------------------------------------------------------------
# Messwerte aus NUT lesen
# ------------------------------------------------------------

# Zeitstempel in UTC / ISO 8601
TIMESTAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if ! VOLTAGE="$(upsc "$UPS_NAME" input.voltage 2>/dev/null)"; then
    echo "$TIMESTAMP upsc_failed metric=input.voltage" >> "$LOG"
    exit 1
fi

if ! STATUS="$(upsc "$UPS_NAME" ups.status 2>/dev/null)"; then
    echo "$TIMESTAMP upsc_failed metric=ups.status" >> "$LOG"
    exit 1
fi


# ------------------------------------------------------------
# Prüfen, ob die USV aktuell am Netz hängt
#
# "OL" = On Line
#
# Bei Batteriebetrieb soll kein Netzspannungswert übertragen
# werden, da die Messung dann nicht mehr dem Stromnetz entspricht.
# ------------------------------------------------------------

if ! echo "$STATUS" | grep -qw 'OL'; then
    echo "$TIMESTAMP skip status=\"$STATUS\"" >> "$LOG"
    exit 0
fi


# ------------------------------------------------------------
# Prüfen, ob input.voltage einen plausiblen numerischen Wert
# geliefert hat.
# ------------------------------------------------------------

case "$VOLTAGE" in
    ''|*[!0-9.]*)
        echo "$TIMESTAMP invalid_voltage=\"$VOLTAGE\"" >> "$LOG"
        exit 1
        ;;
esac


# ------------------------------------------------------------
# JSON-Payload erzeugen
#
# Die meisten kleinen USVs sind einphasig.
# Nicht vorhandene Phasen werden von der API mit -1 angegeben.
# ------------------------------------------------------------

PAYLOAD=$(cat <<EOF
{
  "observed_at": "$TIMESTAMP",
  "latitude": $LATITUDE,
  "longitude": $LONGITUDE,
  "l1_v": $VOLTAGE,
  "l2_v": -1,
  "l3_v": -1,
  "smartmeter_model": "NUT-connected UPS",
  "integration_version": "nut-shell-0.1"
}
EOF
)


# ------------------------------------------------------------
# Messwert übertragen
# ------------------------------------------------------------

TMP_RESPONSE="/tmp/ortsnetz-response.$$"

HTTP_CODE="$(curl -sS \
    --connect-timeout 10 \
    --max-time 20 \
    -o "$TMP_RESPONSE" \
    -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -X POST \
    -d "$PAYLOAD" \
    "$API_URL")"
CURL_EXIT=$?

RESPONSE="$(cat "$TMP_RESPONSE" 2>/dev/null)"


# ------------------------------------------------------------
# Ergebnis protokollieren
#
# Erwartete erfolgreiche Antwort:
# HTTP 202
# ------------------------------------------------------------

echo "$TIMESTAMP voltage=$VOLTAGE status=\"$STATUS\" http=$HTTP_CODE response='$RESPONSE'" >> "$LOG"


# Temporäre Datei entfernen
rm -f "$TMP_RESPONSE"

if [ "$CURL_EXIT" -ne 0 ]; then
    exit 1
fi


# ------------------------------------------------------------
# Bei Fehlern einen Fehlercode an Cron zurückgeben
# ------------------------------------------------------------

if [ "$HTTP_CODE" != "202" ]; then
    exit 1
fi

exit 0
