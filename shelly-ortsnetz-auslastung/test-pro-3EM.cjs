const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'pro-3EM-ortsnetz-auslastung.js'), 'utf8');

function device(options = {}) {
  const requests = [], logs = [], timers = [];
  let status = {
    a_voltage: 230.1, b_voltage: 230.1, c_voltage: 230.1,
    a_current: 1, b_current: 2, c_current: 3,
    a_freq: 50, b_freq: 50, c_freq: 50,
    total_act_power: -123, total_aprt_power: 150
  };
  const configuredSource = options.unconfigured ? source : source
    .replace('latitude: null', 'latitude: 52.52')
    .replace('longitude: null', 'longitude: 13.4');
  const context = vm.createContext({
    console: { log: (...args) => logs.push(args.join(' ')) },
    Shelly: {
      getComponentStatus: () => status,
      call: (method, params, callback) => {
        requests.push({ method, params, payload: JSON.parse(params.body), callback });
        if (!options.deferred) callback(options.result || { code: 202, body: '{"accepted":true}' }, options.error || 0, 'test error');
      }
    },
    Timer: { set: (interval, repeat, callback) => timers.push({ interval, repeat, callback }) }
  });
  vm.runInContext(configuredSource, context);
  return {
    requests, logs, timers,
    set: value => { status = value; },
    update: value => { status = { ...status, ...value }; },
    tick: (count = 1) => { for (let i = 0; i < count; i++) timers[0].callback(); },
    configure: expression => vm.runInContext(expression, context)
  };
}

test('one upload per 300 seconds, version 0.1.3, ten-second HTTP timeout', () => {
  const d = device();
  assert.equal(d.timers[0].interval, 15000);
  d.tick(19);
  assert.equal(d.requests.length, 0);
  d.tick();
  assert.equal(d.requests.length, 1);
  assert.equal(d.requests[0].payload.integration_version, 'shelly-0.1.3');
  assert.equal(d.requests[0].params.timeout, 10);
  d.tick(20);
  assert.equal(d.requests.length, 2);
});

test('constant decimal readings always satisfy API min/avg/max ordering', () => {
  for (const voltage of [230.1, 230.4, 229.9, 150, 300]) {
    const d = device();
    d.update({ a_voltage: voltage });
    d.tick(40);
    for (const { payload: p } of d.requests) {
      assert.equal(p.l1_v_min, voltage);
      assert.equal(p.l1_v_avg, voltage);
      assert.equal(p.l1_v_max, voltage);
    }
  }
});

test('extrema are measured values, including below 220 V and above 250 V', () => {
  for (const voltage of [210, 255]) {
    const d = device();
    d.update({ a_voltage: voltage });
    d.tick(20);
    assert.equal(d.requests[0].payload.l1_v_min, voltage);
    assert.equal(d.requests[0].payload.l1_v_max, voltage);
  }
});

test('average uses every sample and the next interval starts fresh', () => {
  const d = device();
  for (let i = 0; i < 20; i++) {
    d.update({ a_voltage: i % 2 === 0 ? 210 : 250 });
    d.tick();
  }
  assert.equal(d.requests[0].payload.l1_v_avg, 230);
  d.update({ a_voltage: 240 });
  d.tick(20);
  const p = d.requests[1].payload;
  assert.equal(p.l1_v_min, 240);
  assert.equal(p.l1_v_max, 240);
  assert.equal(p.l1_v_avg, 240);
});

test('each single measured phase is supported with missing phases marked -1', () => {
  for (const phase of ['a', 'b', 'c']) {
    const d = device();
    d.set({ [phase + '_voltage']: 231, [phase + '_freq']: 49.99 });
    d.tick(20);
    const p = d.requests[0].payload;
    for (const [i, name] of ['a', 'b', 'c'].entries()) assert.equal(p['l' + (i + 1) + '_v'], name === phase ? 231 : -1);
    assert.equal(p.grid_frequency_hz, 49.99);
  }
});

test('missing, negative or excessive currents never suppress voltages', () => {
  for (const current of [null, undefined, -2, NaN, Infinity, 121]) {
    const d = device();
    d.update({ a_current: current });
    d.tick(20);
    assert.equal(d.requests.length, 1);
    assert.equal(d.requests[0].payload.l1_a, undefined);
    assert.equal(d.requests[0].payload.l2_a, 2);
  }
});

test('invalid samples neither pollute statistics nor stop interval timing', () => {
  const d = device();
  d.set(null);
  d.tick(10);
  d.set({ c_voltage: 240 });
  d.tick(10);
  assert.equal(d.requests.length, 1);
  assert.equal(d.requests[0].payload.l3_v_avg, 240);
});

test('no upload without any currently valid phase', () => {
  const d = device();
  d.tick(19);
  d.set(null);
  d.tick();
  assert.equal(d.requests.length, 0);
});

test('HTTP and RPC failures or invalid bodies never log success or retry early', () => {
  for (const options of [
    { result: { code: 403 } }, { result: { code: 422 } }, { result: { code: 500 } },
    { result: { code: 200, body: '{"accepted":true}' } },
    { result: { code: 202, body: 'invalid json' } },
    { result: { code: 202, body: '{"accepted":false}' } },
    { result: { code: 202, body: '{}' } }, { error: -104 }
  ]) {
    const d = device(options);
    d.tick(39);
    assert.equal(d.requests.length, 1);
    assert.equal(d.logs.some(line => line.includes('measurement accepted')), false);
    d.tick();
    assert.equal(d.requests.length, 2);
  }
  const d = device();
  d.tick(20);
  assert.ok(d.logs.some(line => line.includes('measurement accepted')));
});

test('late callbacks cannot erase samples of the next interval', () => {
  const d = device({ deferred: true });
  d.tick(20);
  d.update({ a_voltage: 260 });
  d.tick();
  d.requests[0].callback({ code: 202, body: '{"accepted":true}' }, 0, '');
  d.update({ a_voltage: 240 });
  d.tick(19);
  assert.equal(d.requests[1].payload.l1_v_max, 260);
  assert.equal(d.requests[1].payload.l1_v_avg, 241);
});

test('optional capacities default to omitted and accept numeric 0 kWh battery', () => {
  const d = device();
  d.tick(20);
  assert.equal(d.requests[0].payload.battery_capacity, undefined);
  assert.equal(d.requests[0].payload.plant_capacity_kwp, undefined);
  d.configure('CONFIG.capacity = 10; CONFIG.battery = 0');
  d.tick(20);
  assert.equal(d.requests[1].payload.battery_capacity, 0);
  assert.equal(d.requests[1].payload.plant_capacity_kwp, 10);
});

test('unconfigured coordinates do not start the timer', () => {
  const d = device({ unconfigured: true });
  assert.equal(d.timers.length, 0);
  assert.equal(d.requests.length, 0);
});
