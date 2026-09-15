# API-Beschreibung

## Endpoint

```text
POST https://www.ortsnetz-auslastung.de/v1/measurements
Content-Type: application/json
```

Der Endpoint ist öffentlich und benötigt keine Authentifizierung. Jede Messung wird einzeln übertragen.

## Request-Felder

| Feld | Typ | Pflicht | Beschreibung |
| --- | --- | --- | --- |
| `observed_at` | String | Ja | ISO-8601-Zeitstempel mit Zeitzone, bevorzugt UTC, z. B. `2026-09-15T08:00:00Z` |
| `latitude` | Zahl | Ja | Breitengrad von -90 bis 90 |
| `longitude` | Zahl | Ja | Längengrad von -180 bis 180 |
| `l1_v` | Zahl | Ja | Spannung Phase L1 in Volt, größer als 0 und maximal 500 |
| `l2_v` | Zahl | Ja | Spannung Phase L2 in Volt, größer als 0 und maximal 500 |
| `l3_v` | Zahl | Ja | Spannung Phase L3 in Volt, größer als 0 und maximal 500 |
| `grid_frequency_hz` | Zahl | Nein | Netzfrequenz in Hertz, 45 bis 55 |
| `plant_capacity_kwp` | Zahl | Nein | Installierte PV-Leistung in kWp, größer als 0 und maximal 1000 |
| `pv_forecast_kwh` | Zahl | Nein | PV-Prognose in kWh, 0 bis 100000 |
| `smartmeter_model` | String | Nein | Freie Bezeichnung des Messgeräts, maximal 120 Zeichen |
| `integration_version` | String | Nein | Kennung der Integration, maximal 32 Zeichen |

## Beispiel

```json
{
  "observed_at": "2026-09-15T08:00:00Z",
  "latitude": 52.520008,
  "longitude": 13.404954,
  "l1_v": 230.1,
  "l2_v": 229.9,
  "l3_v": 230.4,
  "grid_frequency_hz": 50.0,
  "integration_version": "iobroker-0.1.0"
}
```

## Responses

| Status | Bedeutung |
| --- | --- |
| `202 Accepted` | Messung angenommen; die Antwort enthält `accepted`, `created` und eine Ampelbewertung je Phase und insgesamt. |
| `422 Unprocessable Entity` | Pflichtfeld fehlt, hat ein ungültiges Format oder liegt außerhalb des erlaubten Wertebereichs. |
| `403 Forbidden` | Der Standort ist für die Annahme gesperrt. |

Beispielantwort bei Annahme:

```json
{
  "accepted": true,
  "created": true,
  "status": {
    "l1": "green",
    "l2": "green",
    "l3": "green",
    "overall": "green"
  }
}
```
