/*
 * Ortsnetz-Auslastung für Siemens PAC / Energiemessgeräte
 *
 * Liest L1-, L2-, L3-Spannung und Netzfrequenz über die lokale REST API
 * eines Siemens-Messgeräts und überträgt sie alle fünf Minuten an die
 * Ortsnetz-Auslastung-API. Erforderlich ist nur Node.js >= 18 (fetch).
 *
 * Es wird nur die IP-Adresse des Geräts gesetzt; das API-Format und das
 * Modell werden automatisch erkannt.
 *
 * Konfiguration über Umgebungsvariablen (oder defaults unten):
 *   ORTSNETZ_DEVICE_IP          IP-Adresse des Messgeräts (Pflicht)
 *   ORTSNETZ_LATITUDE           Breitengrad des Messorts (Pflicht)
 *   ORTSNETZ_LONGITUDE          Längengrad des Messorts (Pflicht)
 *   ORTSNETZ_PLANT_CAPACITY_KWP installierte PV-Leistung in kWp (optional)
 *   ORTSNETZ_INTERVAL_S         Upload-Intervall in Sekunden (Standard 300)
 */

const API_URL = 'https://www.ortsnetz-auslastung.de/v1/measurements';
const VERSION = 'siemens-sentron-pac-0.1.0';

const CONFIG = {
	deviceIp: process.env.ORTSNETZ_DEVICE_IP || '',
	latitude: process.env.ORTSNETZ_LATITUDE ? Number(process.env.ORTSNETZ_LATITUDE) : NaN,
	longitude: process.env.ORTSNETZ_LONGITUDE ? Number(process.env.ORTSNETZ_LONGITUDE) : NaN,
	plantCapacityKwp: Number(process.env.ORTSNETZ_PLANT_CAPACITY_KWP || NaN),
	intervalMs: (Number(process.env.ORTSNETZ_INTERVAL_S || 300)) * 1000,
};

let FORMAT = null; // 'inst' (data.json) oder 'base' (api-webserver)
let MODEL = null; // z.B. 'SIEMENS SENTRON PAC4220'

function isValue(node) {
	return node && typeof node.value === 'number' && Number.isFinite(node.value);
}

function isBaseValue(node) {
	return node && node.status === 'valid' && node.value
		&& typeof node.value.Mean === 'number' && Number.isFinite(node.value.Mean);
}

// Liefert [l1, l2, l3, freq] aus dem JSON-Antwortobjekt.
// Fehlende oder ungültige Phasen sind null; die Upload-Funktion mappt sie auf -1.
function parseMeasurements(data) {
	const inst = data?.INST_VALUES;
	if (inst) {
		const pick = (key) => (isValue(inst[key]) ? inst[key].value : null);
		return [pick('V_L1'), pick('V_L2'), pick('V_L3'), pick('FREQ')];
	}

	const base = data?.base_values?.metering_values;
	if (base) {
		const pick = (key) => (isBaseValue(base[key]) ? base[key].value.Mean : null);
		return [pick('V_L1'), pick('V_L2'), pick('V_L3'), pick('FREQ')];
	}

	return [null, null, null, null];
}

async function fetchJson(url) {
	const response = await fetch(url, { signal: AbortSignal.timeout(10000) });
	if (!response.ok) {
		throw new Error(`HTTP ${response.status}`);
	}
	return response.json();
}

// Probiert die beiden bekannten Formate nacheinander und merkt sich das passende.
async function detectFormat() {
	if (FORMAT) {
		return;
	}
	if (!CONFIG.deviceIp) {
		console.error('Ortsnetz-Auslastung: ORTSNETZ_DEVICE_IP muss gesetzt sein');
		process.exit(1);
	}
	const instUrl = `http://${CONFIG.deviceIp}/data.json?type=INST_VALUES`;
	const baseUrl = `http://${CONFIG.deviceIp}/api-webserver/values/base`;

	try {
		if ((await fetchJson(instUrl))?.INST_VALUES) {
			FORMAT = 'inst';
			return;
		}
	} catch {
		// "data.json" nicht verfügbar; nächstes Format probieren
	}

	try {
		if ((await fetchJson(baseUrl))?.base_values) {
			FORMAT = 'base';
			return;
		}
	} catch {
		// "api-webserver" nicht verfügbar
	}

	console.error('Ortsnetz-Auslastung: API-Format des Geräts konnte nicht ermittelt werden. Gerät wird nicht unterstützt.');
	process.exit(1);
}

function measurementUrl() {
	if (FORMAT === 'inst') {
		return `http://${CONFIG.deviceIp}/data.json?type=INST_VALUES`;
	}
	if (FORMAT === 'base') {
		return `http://${CONFIG.deviceIp}/api-webserver/values/base`;
	}
	return null;
}

function productUrl() {
	if (FORMAT === 'inst') {
		return `http://${CONFIG.deviceIp}/data.json?type=PRODUCT_INFO`;
	}
	if (FORMAT === 'base') {
		return `http://${CONFIG.deviceIp}/api-webserver/about/device_info`;
	}
	return null;
}

async function updateModel() {
	if (MODEL || !CONFIG.deviceIp) {
		return;
	}
	if (!FORMAT) {
		await detectFormat();
	}
	const url = productUrl();
	if (!url) {
		return;
	}
	try {
		const data = await fetchJson(url);
		const name = data?.PRODUCT_INFO?.name || data?.device_info?.device_name;
		if (typeof name === 'string' && name.length > 0) {
			const deviceType = name.trim().split(' ')[0];
			MODEL = `SIEMENS SENTRON ${deviceType}`;
			console.info(`Ortsnetz-Auslastung: Gerät erkannt: ${MODEL}`);
		}
	} catch (error) {
		console.warn(`Ortsnetz-Auslastung: Modell konnte nicht ermittelt werden: ${error}`);
	}
}

async function uploadMeasurement() {
	if (!CONFIG.deviceIp) {
		console.warn('Ortsnetz-Auslastung: ORTSNETZ_DEVICE_IP nicht gesetzt; Upload übersprungen');
		return;
	}
	if (!FORMAT) {
		await detectFormat();
	}
	const url = measurementUrl();
	if (!url) {
		console.warn('Ortsnetz-Auslastung: kein API-Format erkannt; Upload übersprungen');
		return;
	}

	let data;
	try {
		data = await fetchJson(url);
	} catch (error) {
		console.warn(`Ortsnetz-Auslastung: Messwerte konnten nicht gelesen werden: ${error}`);
		return;
	}

	const [l1, l2, l3, frequency] = parseMeasurements(data);
	const phases = [l1, l2, l3].map((value) => (
		Number.isFinite(value) && value >= 150 && value <= 300 ? value : -1
	));

	// Do not report missing or implausible measurements.
	if (phases.every((value) => value === -1)) {
		console.warn(`Ortsnetz-Auslastung: ungültige Spannung (L1=${l1}, L2=${l2}, L3=${l3}); Upload übersprungen`);
		return;
	}

	const payload = {
		observed_at: new Date().toISOString(),
		latitude: CONFIG.latitude,
		longitude: CONFIG.longitude,
		l1_v: phases[0],
		l2_v: phases[1],
		l3_v: phases[2],
		integration_version: VERSION,
	};

	if (Number.isFinite(frequency) && frequency >= 45 && frequency <= 55) {
		payload.grid_frequency_hz = frequency;
	}
	if (MODEL) {
		payload.smartmeter_model = MODEL;
	}
	if (Number.isFinite(CONFIG.plantCapacityKwp) && CONFIG.plantCapacityKwp > 0) {
		payload.plant_capacity_kwp = CONFIG.plantCapacityKwp;
	}

	if (process.env.ORTSNETZ_DRY_RUN) {
		console.log(`Ortsnetz-Auslastung (dry-run): ${JSON.stringify(payload)}`);
		return;
	}

	try {
		const response = await fetch(API_URL, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
			signal: AbortSignal.timeout(10_000),
		});

		const body = await response.text();

		if (response.status === 202) {
			console.log(`Ortsnetz-Auslastung: Upload angenommen: ${body}`);
			try {
				if (JSON.parse(body)?.status?.overall === 'yellow') {
					console.warn('Ortsnetz-Auslastung: Ampelstatus gelb');
				}
			} catch {
				// Antwort ohne JSON; nichts zu tun
			}
		} else {
			console.warn(`Ortsnetz-Auslastung: unerwarteter HTTP-Status ${response.status}: ${body}`);
		}
	} catch (error) {
		console.warn(`Ortsnetz-Auslastung: Upload fehlgeschlagen: ${error}`);
	}
}

async function main() {
	// Node timers above this limit wrap to 1 ms; reject them as well.
	if (!Number.isInteger(CONFIG.intervalMs) || CONFIG.intervalMs < 300_000
		|| CONFIG.intervalMs > 2_147_483_647) {
		console.error('Ortsnetz-Auslastung: ORTSNETZ_INTERVAL_S muss mindestens 300 sein und darf 2147483.647 nicht überschreiten');
		process.exit(1);
	}
	if (!CONFIG.deviceIp) {
		console.error('Ortsnetz-Auslastung: ORTSNETZ_DEVICE_IP muss gesetzt sein');
		process.exit(1);
	}
	if (!Number.isFinite(CONFIG.latitude) || !Number.isFinite(CONFIG.longitude)) {
		console.error('Ortsnetz-Auslastung: ORTSNETZ_LATITUDE und ORTSNETZ_LONGITUDE müssen gesetzt und Zahlen sein');
		process.exit(1);
	}
	await detectFormat();
	await updateModel();
	await uploadMeasurement();
	if (!process.env.ORTSNETZ_DRY_RUN) {
		setInterval(uploadMeasurement, CONFIG.intervalMs);
	}
}

if (require.main === module) {
	main().catch((error) => {
		console.error(`Ortsnetz-Auslastung: unerwarteter Fehler: ${error}`);
		process.exit(1);
	});
}

module.exports = { main };
