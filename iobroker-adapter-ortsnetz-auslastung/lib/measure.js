'use strict';
/**
 * Pure functions without any ioBroker dependency, so that they can be tested
 * with `node --test` and reused by the admin tab logic if needed.
 *
 * Ranges follow API.md of the project:
 *   voltage   150–300 V are accepted as plausible (API allows 0–500, but values
 *             outside 150–300 V are almost always a wrong data point)
 *   frequency 45–55 Hz
 *   pv forecast 0–100000 kWh, battery SOC 0–100 %
 */

/** Source kinds that can be configured in the "sources" table. */
const KINDS = {
    l1: { lo: 150, hi: 300, field: 'l1_v', voltage: true },
    l2: { lo: 150, hi: 300, field: 'l2_v', voltage: true },
    l3: { lo: 150, hi: 300, field: 'l3_v', voltage: true },
    frequency: { lo: 45, hi: 55, field: 'grid_frequency_hz' },
    pvForecast: { lo: 0, hi: 100000, field: 'pv_forecast_kwh' },
    batterySoc: { lo: 0, hi: 100, field: 'battery_soc_percent' },
    gridPower: { lo: -1e7, hi: 1e7, field: 'grid_power_w' },
};

const round2 = v => Math.round(v * 100) / 100;

/**
 * Turns a site name into a valid ioBroker id part.
 * "Haus Süd" -> "Haus_Süd"; forbidden characters are those of js-controller's FORBIDDEN_CHARS plus dot/space.
 */
function siteId(name) {
    const id = String(name || '')
        .trim()
        .replace(/[\]\[*,;'"`<>\\?.\s]+/g, '_')
        .replace(/^_+|_+$/g, '');
    return id || 'site';
}

function toNumber(val) {
    if (val === null || val === undefined || val === '' || typeof val === 'boolean') return NaN;
    return Number(val);
}

/**
 * Picks the first source whose value is numeric, plausible and fresh.
 * `states` maps id -> {val, ts} (as returned by getForeignStatesAsync).
 * Event driven devices (HomeMatic, SMA) keep their last value forever, therefore the age counts.
 *
 * @returns {{value:number,id:string,ageMin:number}|null}
 */
function firstFresh(ids, states, kind, maxAgeMin, now = Date.now()) {
    const k = KINDS[kind];
    for (const id of ids) {
        const st = states[id];
        if (!st) continue;
        const v = toNumber(st.val);
        const ageMin = (now - (st.ts || 0)) / 60000;
        if (Number.isFinite(v) && v >= k.lo && v <= k.hi && ageMin <= maxAgeMin) {
            return { value: round2(v), id, ageMin: Math.round(ageMin * 10) / 10 };
        }
    }
    return null;
}

/**
 * min/max/avg over the samples of one source collected during the interval.
 * The current value is always part of it: an unchanged event-driven value held during the whole interval.
 */
function intervalStats(samples, current) {
    const values = samples.filter(Number.isFinite);
    if (Number.isFinite(current)) values.push(current);
    if (!values.length) return null;
    const sum = values.reduce((a, b) => a + b, 0);
    return {
        min: round2(Math.min(...values)),
        max: round2(Math.max(...values)),
        // rounding may break min <= avg <= max by 0.005 - clamp it, the API checks the order
        avg: Math.min(round2(Math.max(...values)), Math.max(round2(Math.min(...values)), round2(sum / values.length))),
        count: values.length,
    };
}

/**
 * Builds the API payload of one site.
 *
 * @param {object} site      configured site (latitude, longitude, smartmeterModel, ...)
 * @param {object} picked    kind -> {value, id, stats?} | null  (result of firstFresh per kind)
 * @param {object} opts      {includeStatic, sendStatistics, version, now, coordDecimals}
 * @returns {{payload?:object, error?:string}}
 */
function buildPayload(site, picked, opts) {
    const dec = Number.isInteger(opts.coordDecimals) ? opts.coordDecimals : 3;
    const lat = Number(site.latitude);
    const lon = Number(site.longitude);
    if (!Number.isFinite(lat) || lat < -90 || lat > 90 || !Number.isFinite(lon) || lon < -180 || lon > 180 || (lat === 0 && lon === 0)) {
        return { error: 'Koordinaten fehlen oder sind ungültig' };
    }
    const f = 10 ** dec;
    const payload = {
        observed_at: new Date(opts.now || Date.now()).toISOString(),
        latitude: Math.round(lat * f) / f,
        longitude: Math.round(lon * f) / f,
    };
    // A phase without configured source is "not measured" (-1); a configured but stale phase is an error,
    // otherwise a dead three-phase meter would quietly turn into a one-phase report.
    for (const ph of ['l1', 'l2', 'l3']) {
        const p = picked[ph];
        if (p === undefined) payload[KINDS[ph].field] = -1;
        else if (p === null) return { error: `keine frische, plausible Spannung für ${ph.toUpperCase()} (150–300 V)` };
        else payload[KINDS[ph].field] = p.value;
    }
    if ([payload.l1_v, payload.l2_v, payload.l3_v].every(v => v === -1)) {
        return { error: 'keine Spannungsquelle konfiguriert' };
    }
    for (const kind of ['frequency', 'pvForecast', 'batterySoc', 'gridPower']) {
        const p = picked[kind];
        if (p) payload[KINDS[kind].field] = p.value;
    }
    if (opts.sendStatistics) {
        for (const kind of ['l1', 'l2', 'l3', 'frequency']) {
            const p = picked[kind];
            if (!p || !p.stats || p.stats.count < 2) continue;
            const base = KINDS[kind].field;
            payload[`${base}_min`] = p.stats.min;
            payload[`${base}_max`] = p.stats.max;
            payload[`${base}_avg`] = p.stats.avg;
        }
    }
    if (opts.includeStatic) {
        const kwp = Number(site.plantCapacityKwp);
        if (Number.isFinite(kwp) && kwp > 0 && kwp <= 1000) payload.plant_capacity_kwp = kwp;
        const bat = Number(site.batteryCapacity);
        if (Number.isFinite(bat) && bat > 0) payload.battery_capacity = bat;
        if (site.smartmeterModel) payload.smartmeter_model = String(site.smartmeterModel).slice(0, 120);
    }
    // API rule: forecast needs a known plant size and must not exceed 10 kWh/kWp/day.
    // The size is stored server side once sent, therefore only drop obviously impossible values.
    const kwp = Number(site.plantCapacityKwp);
    if (payload.pv_forecast_kwh !== undefined && Number.isFinite(kwp) && kwp > 0 && payload.pv_forecast_kwh > kwp * 10) {
        delete payload.pv_forecast_kwh;
    }
    if (opts.version) payload.integration_version = String(opts.version).slice(0, 32);
    return { payload };
}

/* ------------------------------------------------------------------ */
/* Map helpers                                                          */
/* ------------------------------------------------------------------ */

const DEFAULT_SCALE = { criticalLow: 207, warningLow: 218, warningHigh: 242, criticalHigh: 253 };

/** Same classification as the public map (app.js thresholdBand). */
function band(value, scale = DEFAULT_SCALE) {
    if (!Number.isFinite(value) || value === -1 || value <= 0) return null;
    if (value < scale.criticalLow) return { severity: 2, key: 'low-critical' };
    if (value < scale.warningLow) return { severity: 1, key: 'low-warning' };
    if (value > scale.criticalHigh) return { severity: 2, key: 'high-critical' };
    if (value > scale.warningHigh) return { severity: 1, key: 'high-warning' };
    return { severity: 0, key: 'normal' };
}

function worstBand(values, scale) {
    const bands = values.map(v => band(v, scale)).filter(Boolean);
    bands.sort((a, b) => b.severity - a.severity);
    return bands[0] || { severity: -1, key: 'unavailable' };
}

/** Great circle distance in km. */
function distanceKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const rad = d => (d * Math.PI) / 180;
    const dLat = rad(lat2 - lat1);
    const dLon = rad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

const validVoltages = p => [p.l1_v, p.l2_v, p.l3_v].filter(v => Number.isFinite(v) && v > 0);

/**
 * Statistics of the public points around a site; the own point (same rounded coordinates) is excluded.
 */
function neighbourStats(points, lat, lon, radiusKm, ownPublicId) {
    const near = [];
    for (const p of points) {
        if (p.stale || p.public_id === ownPublicId) continue;
        const d = distanceKm(lat, lon, p.latitude, p.longitude);
        if (d <= radiusKm) near.push({ p, d });
    }
    const volts = near.flatMap(n => validVoltages(n.p));
    if (!volts.length) return { count: near.length, avg: null, min: null, max: null, nearestKm: null };
    near.sort((a, b) => a.d - b.d);
    return {
        count: near.length,
        avg: round2(volts.reduce((a, b) => a + b, 0) / volts.length),
        min: round2(Math.min(...volts)),
        max: round2(Math.max(...volts)),
        nearestKm: Math.round(near[0].d * 10) / 10,
    };
}

/** Finds the public map point that belongs to a site: same coordinates after rounding to 3 decimals. */
function findOwnPoint(points, lat, lon) {
    const r = v => Math.round(Number(v) * 1000);
    return points.find(p => r(p.latitude) === r(lat) && r(p.longitude) === r(lon)) || null;
}

module.exports = {
    KINDS,
    siteId,
    firstFresh,
    intervalStats,
    buildPayload,
    band,
    worstBand,
    distanceKm,
    neighbourStats,
    findOwnPoint,
    validVoltages,
    DEFAULT_SCALE,
};
