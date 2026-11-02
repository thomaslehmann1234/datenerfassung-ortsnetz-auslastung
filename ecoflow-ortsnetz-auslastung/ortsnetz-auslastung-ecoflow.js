/*
 * Ortsnetz-Auslastung for EcoFlow Smart Meter (ioBroker JavaScript adapter)
 * Version: 0.1.1
 *
 * Reads the phase voltages of an EcoFlow Smart Meter from the ioBroker
 * adapter ecoflow-mqtt and uploads them every five minutes.
 *
 * Based on iobroker-ortsnetz-auslastung v0.2.0. Additions:
 *   - min/max/avg voltage per phase over the 5-minute interval
 *   - staleness check: no upload when the EcoFlow cloud stops delivering
 *   - optional grid power at the house connection (grid_power_w)
 *   - static fields (model, kWp) once per script start
 *   - API response (traffic light, storage recommendation) as data points;
 *     every attempt rewrites them, so errors never leave an old result visible
 *
 * Requires: ioBroker.javascript >= 7.9.0 (httpPost),
 *           ioBroker.ecoflow-mqtt with the Smart Meter configured.
 */

const CONFIG = {
    // Approximate location, rounded to 2-3 decimals. Nothing is sent while null.
    latitude: null,
    longitude: null,

    // Replace SERIENNUMMER with the serial number of the Smart Meter
    // (visible under Objects as ecoflow-mqtt.0.<serial>).
    meterBase: 'ecoflow-mqtt.0.SERIENNUMMER.DisplayPropertyUpload',

    // Static fields, sent once per script start
    smartmeterModel: 'EcoFlow Smart Meter',
    plantCapacityKwp: null, // optional, e.g. 2.0

    // Send grid power (totalPower)? API convention: positive = import,
    // negative = export. The EcoFlow Smart Meter already reports totalPower
    // this way; invertGridPower is only a fallback (see README).
    sendGridPower: true,
    invertGridPower: false,

    // Values older than this are considered stale -> no upload
    maxAgeSeconds: 600,

    // Where the API response is stored; '' disables it
    statusPrefix: '0_userdata.0.ortsnetz',

    // true = log payload and response (level info)
    debug: false,
};

const API_URL = 'https://www.ortsnetz-auslastung.de/v1/measurements';
const VERSION = 'iobroker-ecoflow-0.1.1';
const LOG_PREFIX = 'Ortsnetz-Auslastung:';

const IDS = {
    l1: `${CONFIG.meterBase}.voltageL1`,
    l2: `${CONFIG.meterBase}.voltageL2`,
    l3: `${CONFIG.meterBase}.voltageL3`,
    power: `${CONFIG.meterBase}.totalPower`,
};
const PHASES = ['l1', 'l2', 'l3'];

// Voltage samples of the running interval
let samples = { l1: [], l2: [], l3: [] };
// Static fields already accepted by the API?
let staticSent = false;

function isValidVoltage(v) {
    // Plausibility limits as in the generic ioBroker script
    return Number.isFinite(v) && v >= 150 && v <= 300;
}

function round(v, digits = 2) {
    const f = 10 ** digits;
    return Math.round(v * f) / f;
}

// Reads a data point and returns its value and age in seconds
async function readState(id) {
    const state = await getStateAsync(id);
    if (!state || state.val === null || state.val === undefined || state.val === '') {
        throw new Error(`Datenpunkt leer: ${id}`);
    }
    return { value: Number(state.val), ageSec: (Date.now() - state.ts) / 1000 };
}

// Creates the status data points (existing ones are kept)
async function initStatusStates() {
    if (!CONFIG.statusPrefix) {
        return;
    }
    const defs = {
        overall: { type: 'string', role: 'text', name: 'Ampel gesamt' },
        l1: { type: 'string', role: 'text', name: 'Ampel L1' },
        l2: { type: 'string', role: 'text', name: 'Ampel L2' },
        l3: { type: 'string', role: 'text', name: 'Ampel L3' },
        storage_recommendation: { type: 'string', role: 'text', name: 'Speicherladeempfehlung' },
        http_status: { type: 'number', role: 'value', name: 'HTTP-Status des letzten Versuchs (null = keine Antwort)' },
        last_error: { type: 'string', role: 'text', name: 'Fehler des letzten Versuchs (leer = OK)' },
        last_upload: { type: 'number', role: 'date', name: 'Letzter erfolgreicher Upload' },
    };
    for (const [key, common] of Object.entries(defs)) {
        await createStateAsync(`${CONFIG.statusPrefix}.${key}`, null, { read: true, write: false, ...common });
    }
}

const RESULT_KEYS = ['overall', 'l1', 'l2', 'l3', 'storage_recommendation'];

function setStatus(key, value) {
    setState(`${CONFIG.statusPrefix}.${key}`, value, true);
}

// Failed or skipped attempt: log, record the reason and clear the result,
// so no previous traffic light or recommendation stays visible
function reportFailure(reason, httpStatus = null) {
    log(`${LOG_PREFIX} ${reason}`, 'warn');
    if (!CONFIG.statusPrefix) {
        return;
    }
    setStatus('http_status', httpStatus);
    setStatus('last_error', reason);
    for (const key of RESULT_KEYS) {
        setStatus(key, null);
    }
}

// Accepted upload: write every result field, missing fields become null
function reportSuccess(body) {
    if (!CONFIG.statusPrefix) {
        return;
    }
    const status = (body && body.status) || {};
    setStatus('http_status', 202);
    setStatus('last_error', '');
    setStatus('last_upload', Date.now());
    for (const key of ['overall', 'l1', 'l2', 'l3']) {
        setStatus(key, status[key] !== undefined ? String(status[key]) : null);
    }
    setStatus(
        'storage_recommendation',
        body && body.storage_recommendation !== undefined ? String(body.storage_recommendation) : null,
    );
}

// Collect every voltage update for min/max/avg
on({ id: [IDS.l1, IDS.l2, IDS.l3], change: 'any', ack: true }, (obj) => {
    const phase = PHASES.find((p) => IDS[p] === obj.id);
    const v = Number(obj.state.val);
    if (phase && isValidVoltage(v)) {
        samples[phase].push(v);
    }
});

async function uploadMeasurement() {
    // Take over the collected samples and start a fresh interval
    const interval = samples;
    samples = { l1: [], l2: [], l3: [] };

    if (!Number.isFinite(CONFIG.latitude) || !Number.isFinite(CONFIG.longitude)) {
        reportFailure('latitude/longitude nicht konfiguriert; Upload übersprungen');
        return;
    }
    if (CONFIG.meterBase.includes('SERIENNUMMER')) {
        reportFailure('Seriennummer in meterBase nicht eingetragen; Upload übersprungen');
        return;
    }

    try {
        const current = {};
        for (const p of PHASES) {
            const { value, ageSec } = await readState(IDS[p]);
            if (ageSec > CONFIG.maxAgeSeconds) {
                reportFailure(`${p.toUpperCase()} veraltet (${Math.round(ageSec)} s); Upload übersprungen`);
                return;
            }
            current[p] = value;
        }

        // Do not report missing or implausible measurements
        if (!PHASES.every((p) => isValidVoltage(current[p]))) {
            reportFailure(`ungültige Spannung (${PHASES.map((p) => current[p]).join(' / ')}); Upload übersprungen`);
            return;
        }

        const payload = {
            observed_at: new Date().toISOString(),
            latitude: CONFIG.latitude,
            longitude: CONFIG.longitude,
            l1_v: current.l1,
            l2_v: current.l2,
            l3_v: current.l3,
            integration_version: VERSION,
        };

        // min/max/avg per phase; without updates in the interval use the current value
        for (const p of PHASES) {
            const values = interval[p].length ? interval[p] : [current[p]];
            payload[`${p}_v_min`] = round(Math.min(...values));
            payload[`${p}_v_max`] = round(Math.max(...values));
            payload[`${p}_v_avg`] = round(values.reduce((a, b) => a + b, 0) / values.length);
        }

        if (CONFIG.sendGridPower) {
            try {
                const { value, ageSec } = await readState(IDS.power);
                if (Number.isFinite(value) && ageSec <= CONFIG.maxAgeSeconds) {
                    payload.grid_power_w = CONFIG.invertGridPower ? -value : value;
                }
            } catch (e) {
                log(`${LOG_PREFIX} totalPower nicht lesbar: ${e}`, 'warn');
            }
        }

        if (!staticSent) {
            payload.smartmeter_model = CONFIG.smartmeterModel;
            if (Number.isFinite(CONFIG.plantCapacityKwp) && CONFIG.plantCapacityKwp > 0 && CONFIG.plantCapacityKwp <= 1000) {
                payload.plant_capacity_kwp = CONFIG.plantCapacityKwp;
            }
        }

        if (CONFIG.debug) {
            log(`${LOG_PREFIX} Payload: ${JSON.stringify(payload)}`, 'info');
        }

        httpPost(API_URL, payload, { timeout: 10000, headers: { 'Content-Type': 'application/json' } }, (error, response) => {
            if (error) {
                // Timeout, DNS or connection error: no HTTP status available
                reportFailure(`Upload fehlgeschlagen: ${error}`);
                return;
            }

            let body = null;
            try {
                body = typeof response.data === 'string' ? JSON.parse(response.data) : response.data;
            } catch (e) {
                // Response without JSON body; the status code is sufficient
            }

            if (response.statusCode === 202) {
                staticSent = true;
                reportSuccess(body);
                if (CONFIG.debug) {
                    log(`${LOG_PREFIX} OK: ${JSON.stringify(body)}`, 'info');
                }
            } else {
                reportFailure(`unerwarteter HTTP-Status ${response.statusCode}: ${JSON.stringify(body)}`, response.statusCode);
            }
        });
    } catch (error) {
        reportFailure(`Datenpunkt nicht lesbar: ${error}`);
    }
}

initStatusStates()
    .catch((e) => log(`${LOG_PREFIX} Status-Datenpunkte nicht angelegt: ${e}`, 'warn'))
    .finally(() => {
        // Every five minutes at minute 0, 5, 10, ... plus once at start
        schedule('*/5 * * * *', uploadMeasurement);
        uploadMeasurement();
    });
