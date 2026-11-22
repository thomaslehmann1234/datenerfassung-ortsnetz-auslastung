'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../lib/measure');

const NOW = Date.parse('2026-11-04T12:00:00Z');
const st = (val, minAgo) => ({ val, ts: NOW - minAgo * 60000 });

test('firstFresh takes the first fresh and plausible value in list order', () => {
    const states = { a: st(231, 30), b: st(12, 1), c: st(229.456, 2), d: st(230, 1) };
    assert.deepEqual(M.firstFresh(['a', 'b', 'c', 'd'], states, 'l1', 15, NOW), { value: 229.46, id: 'c', ageMin: 2 });
});

test('firstFresh returns null when nothing fits and ignores missing ids', () => {
    assert.equal(M.firstFresh(['x', 'a'], { a: st(231, 30) }, 'l1', 15, NOW), null);
    assert.equal(M.firstFresh(['a'], { a: st('', 1) }, 'l1', 15, NOW), null);
    assert.equal(M.firstFresh(['a'], { a: st(true, 1) }, 'l1', 15, NOW), null);
});

test('frequency range 45-55 Hz', () => {
    assert.equal(M.firstFresh(['f'], { f: st(60, 1) }, 'frequency', 15, NOW), null);
    assert.equal(M.firstFresh(['f'], { f: st(49.98, 1) }, 'frequency', 15, NOW).value, 49.98);
});

test('intervalStats includes the current value and keeps min <= avg <= max', () => {
    assert.deepEqual(M.intervalStats([230, 232], 231), { min: 230, max: 232, avg: 231, count: 3 });
    assert.deepEqual(M.intervalStats([], 230), { min: 230, max: 230, avg: 230, count: 1 });
    const s = M.intervalStats([230.004, 230.006, 230.004], 230.005);
    assert.ok(s.min <= s.avg && s.avg <= s.max);
});

const site = { latitude: 52.51628, longitude: 13.37770, smartmeterModel: 'Shelly Pro 3EM', plantCapacityKwp: 10, batteryCapacity: '' };

test('single phase: unconfigured phases are -1, coordinates rounded', () => {
    const { payload, error } = M.buildPayload(site, { l1: { value: 231.2, stats: { min: 230, max: 232, avg: 231, count: 3 } } }, { includeStatic: false, sendStatistics: true, version: 'v', now: NOW });
    assert.equal(error, undefined);
    assert.equal(payload.latitude, 52.516);
    assert.equal(payload.longitude, 13.378);
    assert.equal(payload.l1_v, 231.2);
    assert.equal(payload.l2_v, -1);
    assert.equal(payload.l3_v, -1);
    assert.equal(payload.l1_v_min, 230);
    assert.equal(payload.l1_v_avg, 231);
    assert.equal(payload.smartmeter_model, undefined);
    assert.equal(payload.observed_at, '2026-11-04T12:00:00.000Z');
});

test('configured but stale phase blocks the upload', () => {
    const r = M.buildPayload(site, { l1: { value: 231 }, l2: null }, { now: NOW });
    assert.match(r.error, /L2/);
});

test('no voltage at all is an error', () => {
    assert.ok(M.buildPayload(site, { frequency: { value: 50 } }, { now: NOW }).error);
});

test('invalid coordinates are an error', () => {
    assert.ok(M.buildPayload({ latitude: '', longitude: '' }, { l1: { value: 231 } }, { now: NOW }).error);
    assert.ok(M.buildPayload({ latitude: 0, longitude: 0 }, { l1: { value: 231 } }, { now: NOW }).error);
});

test('static fields only with includeStatic, forecast limited to 10 kWh/kWp', () => {
    const picked = { l1: { value: 231 }, l2: { value: 232 }, l3: { value: 233 }, pvForecast: { value: 150 }, frequency: { value: 50.01 } };
    const { payload } = M.buildPayload(site, picked, { includeStatic: true, now: NOW });
    assert.equal(payload.smartmeter_model, 'Shelly Pro 3EM');
    assert.equal(payload.plant_capacity_kwp, 10);
    assert.equal(payload.battery_capacity, undefined);
    assert.equal(payload.pv_forecast_kwh, undefined); // 150 > 10 kWp * 10
    assert.equal(payload.grid_frequency_hz, 50.01);
});

test('statistics need at least two samples', () => {
    const { payload } = M.buildPayload(site, { l1: { value: 231, stats: { min: 231, max: 231, avg: 231, count: 1 } } }, { sendStatistics: true, now: NOW });
    assert.equal(payload.l1_v_min, undefined);
});

test('band follows the public scale', () => {
    assert.equal(M.band(200).key, 'low-critical');
    assert.equal(M.band(210).key, 'low-warning');
    assert.equal(M.band(230).key, 'normal');
    assert.equal(M.band(245).key, 'high-warning');
    assert.equal(M.band(260).key, 'high-critical');
    assert.equal(M.band(-1), null);
    assert.equal(M.worstBand([230, -1, 246]).key, 'high-warning');
});

test('neighbourStats excludes the own and stale points', () => {
    const pts = [
        { latitude: 52.516, longitude: 13.378, l1_v: 240, l2_v: -1, l3_v: -1, public_id: 'own', stale: false },
        { latitude: 52.523, longitude: 13.388, l1_v: 230, l2_v: 232, l3_v: 234, public_id: 'a', stale: false },
        { latitude: 52.6, longitude: 13.4, l1_v: 220, l2_v: -1, l3_v: -1, public_id: 'b', stale: true },
        { latitude: 48.1, longitude: 11.5, l1_v: 250, l2_v: 250, l3_v: 250, public_id: 'far', stale: false },
    ];
    const own = M.findOwnPoint(pts, 52.51628, 13.37770);
    assert.equal(own.public_id, 'own');
    const n = M.neighbourStats(pts, 52.516, 13.378, 25, own.public_id);
    assert.equal(n.count, 1);
    assert.equal(n.avg, 232);
    assert.equal(n.min, 230);
    assert.ok(n.nearestKm > 0 && n.nearestKm < 2);
});

test('distanceKm Berlin-Munich is about 504 km', () => {
    const d = M.distanceKm(52.52, 13.405, 48.137, 11.575);
    assert.ok(d > 495 && d < 510, String(d));
});

test('siteId removes forbidden characters', () => {
    assert.equal(M.siteId('Haus Musterstadt'), 'Haus_Musterstadt');
    assert.equal(M.siteId('a.b*c'), 'a_b_c');
    assert.equal(M.siteId(''), 'site');
});
