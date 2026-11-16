'use strict';
/**
 * Table of all data points the adapter creates. A new value = a new line here;
 * README.md documents the same table.
 *
 * SITE_STATES are created below `ortsnetz-auslastung.<n>.<site>.`, GLOBAL_STATES directly below the instance.
 */

const s = (type, role, de, en, extra = {}) => ({ type, role, name: { de, en }, read: true, write: false, ...extra });

const SITE_CHANNELS = {
    measurement: { de: 'Gesendete Messwerte', en: 'Transmitted measurements' },
    grid: { de: 'Bewertung durch ortsnetz-auslastung.de', en: 'Rating by ortsnetz-auslastung.de' },
    upload: { de: 'Übertragung', en: 'Upload' },
    neighbours: { de: 'Messpunkte in der Umgebung', en: 'Measuring points nearby' },
};

const SITE_STATES = {
    // what was sent
    'measurement.voltageL1': s('number', 'value.voltage', 'Spannung L1', 'Voltage L1', { unit: 'V' }),
    'measurement.voltageL2': s('number', 'value.voltage', 'Spannung L2 (-1 = nicht gemessen)', 'Voltage L2 (-1 = not measured)', { unit: 'V' }),
    'measurement.voltageL3': s('number', 'value.voltage', 'Spannung L3 (-1 = nicht gemessen)', 'Voltage L3 (-1 = not measured)', { unit: 'V' }),
    'measurement.frequency': s('number', 'value.frequency', 'Netzfrequenz', 'Grid frequency', { unit: 'Hz' }),
    'measurement.sourceL1': s('string', 'text', 'Quelle Spannung L1', 'Source voltage L1'),
    'measurement.sourceL2': s('string', 'text', 'Quelle Spannung L2', 'Source voltage L2'),
    'measurement.sourceL3': s('string', 'text', 'Quelle Spannung L3', 'Source voltage L3'),
    'measurement.sourceFrequency': s('string', 'text', 'Quelle Netzfrequenz', 'Source grid frequency'),
    // answer of the API
    'grid.statusOverall': s('string', 'text', 'Ampel gesamt (green/yellow/red)', 'Traffic light overall (green/yellow/red)'),
    'grid.statusL1': s('string', 'text', 'Ampel L1', 'Traffic light L1'),
    'grid.statusL2': s('string', 'text', 'Ampel L2', 'Traffic light L2'),
    'grid.statusL3': s('string', 'text', 'Ampel L3', 'Traffic light L3'),
    'grid.storageRecommendation': s('string', 'text', 'Speicherladeempfehlung (charge/discharge/none)', 'Storage recommendation (charge/discharge/none)', {
        states: { charge: 'laden', discharge: 'entladen', none: 'keine Aktion' },
    }),
    'grid.redispatchActive': s('mixed', 'indicator', 'Redispatch in 50 km aktiv (null = unbekannt)', 'Redispatch within 50 km active (null = unknown)'),
    'grid.redispatchAffectedUnits': s('number', 'value', 'Redispatch: betroffene Anlagen', 'Redispatch: affected units'),
    'grid.redispatchActiveMeasures': s('number', 'value', 'Redispatch: Maßnahmen', 'Redispatch: measures'),
    'grid.redispatchUpdatedAt': s('string', 'date', 'Redispatch: Datenstand', 'Redispatch: data timestamp'),
    // transport
    'upload.lastUpload': s('string', 'date', 'Letzter angenommener Upload', 'Last accepted upload'),
    'upload.lastAttempt': s('string', 'date', 'Letzter Versuch', 'Last attempt'),
    'upload.lastHttpStatus': s('number', 'value', 'Letzter HTTP-Status', 'Last HTTP status'),
    'upload.lastError': s('string', 'text', 'Letzter Fehler (leer = ok)', 'Last error (empty = ok)'),
    'upload.uploadsOk': s('number', 'value', 'Angenommene Uploads seit Start', 'Accepted uploads since start'),
    'upload.uploadsFailed': s('number', 'value', 'Fehlgeschlagene/übersprungene Uploads seit Start', 'Failed/skipped uploads since start'),
    'upload.lastPayload': s('string', 'json', 'Letzter Payload', 'Last payload'),
    'upload.lastResponse': s('string', 'json', 'Letzte API-Antwort', 'Last API response'),
    'upload.history': s('string', 'json', 'Verlauf der letzten 24 h (für den Reiter)', 'History of the last 24 h (for the tab)'),
    // neighbourhood on the public map
    'neighbours.publicId': s('string', 'text', 'Kennung des eigenen Punkts auf der Karte', 'Id of the own point on the map'),
    'neighbours.count': s('number', 'value', 'Messpunkte im Umkreis', 'Measuring points within radius'),
    'neighbours.avgVoltage': s('number', 'value.voltage', 'Mittlere Spannung im Umkreis', 'Average voltage within radius', { unit: 'V' }),
    'neighbours.minVoltage': s('number', 'value.voltage', 'Kleinste Spannung im Umkreis', 'Lowest voltage within radius', { unit: 'V' }),
    'neighbours.maxVoltage': s('number', 'value.voltage', 'Größte Spannung im Umkreis', 'Highest voltage within radius', { unit: 'V' }),
    'neighbours.deviation': s('number', 'value.voltage', 'Eigene Spannung L1 minus Mittel im Umkreis', 'Own voltage L1 minus average within radius', { unit: 'V' }),
    'neighbours.nearestKm': s('number', 'value.distance', 'Entfernung zum nächsten Messpunkt', 'Distance to nearest measuring point', { unit: 'km' }),
};

const GLOBAL_STATES = {
    'info.connection': s('boolean', 'indicator.connected', 'Letzter Upload angenommen', 'Last upload accepted', { def: false }),
    'map.pointCount': s('number', 'value', 'Messpunkte auf der Karte', 'Measuring points on the map'),
    'map.lastUpdate': s('string', 'date', 'Karte zuletzt geladen', 'Map last loaded'),
    'map.normal24h': s('number', 'value', 'Messungen normal (24 h, bundesweit)', 'Measurements normal (24 h, nationwide)'),
    'map.warning24h': s('number', 'value', 'Messungen mit Warnung (24 h, bundesweit)', 'Measurements with warning (24 h, nationwide)'),
    'map.critical24h': s('number', 'value', 'Messungen kritisch (24 h, bundesweit)', 'Measurements critical (24 h, nationwide)'),
};

module.exports = { SITE_CHANNELS, SITE_STATES, GLOBAL_STATES };
