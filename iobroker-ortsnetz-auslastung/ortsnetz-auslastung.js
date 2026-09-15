/*
 * Ortsnetz-Auslastung for ioBroker JavaScript adapter
 * Version: 0.1.0
 *
 * Requires ioBroker.javascript >= 7.9.0 for httpPost().
 */

const CONFIG = {
    latitude: 52.520008,
    longitude: 13.404954,
    l1State: 'smartmeter.0.voltage_l1',
    l2State: 'smartmeter.0.voltage_l2',
    l3State: 'smartmeter.0.voltage_l3',
    frequencyState: 'smartmeter.0.frequency', // optional: set to '' when unavailable
};

const API_URL = 'https://www.ortsnetz-auslastung.de/v1/measurements';
const VERSION = 'iobroker-0.1.0';

function numberState(id) {
    if (!id) {
        return Promise.resolve(null);
    }

    return getStateAsync(id).then((state) => Number(state?.val));
}

async function uploadMeasurement() {
    try {
        const [l1, l2, l3, frequency] = await Promise.all([
            numberState(CONFIG.l1State),
            numberState(CONFIG.l2State),
            numberState(CONFIG.l3State),
            numberState(CONFIG.frequencyState),
        ]);

        // Do not report missing or implausible measurements.
        if (![l1, l2, l3].every((value) => Number.isFinite(value) && value >= 150 && value <= 300)) {
            log('Ortsnetz-Auslastung: ungültige Spannung; Upload übersprungen', 'warn');
            return;
        }

        const payload = {
            observed_at: new Date().toISOString(),
            latitude: CONFIG.latitude,
            longitude: CONFIG.longitude,
            l1_v: l1,
            l2_v: l2,
            l3_v: l3,
            integration_version: VERSION,
        };

        if (Number.isFinite(frequency) && frequency >= 45 && frequency <= 55) {
            payload.grid_frequency_hz = frequency;
        }

        httpPost(API_URL, payload, { timeout: 10000, headers: { 'Content-Type': 'application/json' } }, (error, response) => {
            if (error) {
                log(`Ortsnetz-Auslastung: Upload fehlgeschlagen: ${error}`, 'warn');
            } else if (response.statusCode !== 202) {
                log(`Ortsnetz-Auslastung: unerwarteter HTTP-Status ${response.statusCode}`, 'warn');
            }
        });
    } catch (error) {
        log(`Ortsnetz-Auslastung: Datenpunkt nicht lesbar: ${error}`, 'warn');
    }
}

// Alle fünf Minuten, zur Minute 0, 5, 10, …
schedule('*/5 * * * *', uploadMeasurement);
uploadMeasurement();
