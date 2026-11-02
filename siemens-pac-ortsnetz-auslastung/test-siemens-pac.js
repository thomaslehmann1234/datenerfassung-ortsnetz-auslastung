const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, 'ortsnetz-siemens-pac.js'), 'utf8');

function harness({ interval, phases = [230.1, 229.9, 230.4], format = 'inst' } = {}) {
	const requests = [];
	const timers = [];
	const context = {
		module: { exports: {} },
		require: { main: null },
		console: { log() {}, info() {}, warn() {}, error() {} },
		AbortSignal,
		process: {
			env: {
				ORTSNETZ_DEVICE_IP: '192.0.2.1',
				ORTSNETZ_LATITUDE: '52.520008',
				ORTSNETZ_LONGITUDE: '13.404954',
				...(interval === undefined ? {} : { ORTSNETZ_INTERVAL_S: String(interval) }),
			},
			exit(code) { throw new Error(`exit:${code}`); },
		},
		setInterval(callback, delay) { timers.push(delay); },
		async fetch(url, options = {}) {
			requests.push({ url, options });
			if (options.method === 'POST') {
				return { status: 202, text: async () => '{"status":{"overall":"green"}}' };
			}
			if (url.includes('PRODUCT_INFO') || url.includes('device_info')) {
				return { ok: true, json: async () => ({ PRODUCT_INFO: { name: 'PAC4220' } }) };
			}
			const values = Object.fromEntries(['V_L1', 'V_L2', 'V_L3'].map((key, i) => [key,
				format === 'inst' ? { value: phases[i] } : { status: 'valid', value: { Mean: phases[i] } },
			]));
			if (format === 'base' && url.includes('data.json')) {
				return { ok: false, status: 404 };
			}
			return { ok: true, json: async () => format === 'inst'
				? { INST_VALUES: values } : { base_values: { metering_values: values } } };
		},
	};
	vm.runInNewContext(source, context);
	return { run: context.module.exports.main, requests, timers };
}

test('mixed valid and invalid phases are normalized in both device API formats', async () => {
	for (const format of ['inst', 'base']) {
		for (const phases of [[230, 400, null], [230, 0, 149], [230, NaN, Infinity]]) {
			const h = harness({ phases, format });
			await h.run();
			const post = h.requests.filter((r) => r.options.method === 'POST');
			assert.equal(post.length, 1);
			const payload = JSON.parse(post[0].options.body);
			assert.deepEqual([payload.l1_v, payload.l2_v, payload.l3_v], [230, -1, -1]);
		}
	}
});

test('valid boundary values are retained', async () => {
	const h = harness({ phases: [150, 230, 300] });
	await h.run();
	const payload = JSON.parse(h.requests.find((r) => r.options.method === 'POST').options.body);
	assert.deepEqual([payload.l1_v, payload.l2_v, payload.l3_v], [150, 230, 300]);
});

test('all invalid phases skip the upload', async () => {
	const h = harness({ phases: [149, 301, null] });
	await h.run();
	assert.equal(h.requests.filter((r) => r.options.method === 'POST').length, 0);
});

test('unsafe intervals stop before network access or timer creation', async () => {
	for (const interval of [0, -1, 1, 299, 'invalid', NaN, Infinity, 2147484, '0.0001']) {
		const h = harness({ interval });
		await assert.rejects(h.run(), /exit:1/);
		assert.equal(h.requests.length, 0, String(interval));
		assert.equal(h.timers.length, 0, String(interval));
	}
});

test('default and longer valid intervals schedule uploads correctly', async () => {
	for (const interval of [undefined, 300, 600, 2147483.647]) {
		const h = harness({ interval });
		await h.run();
		assert.deepEqual(h.timers, [(interval ?? 300) * 1000]);
	}
});
