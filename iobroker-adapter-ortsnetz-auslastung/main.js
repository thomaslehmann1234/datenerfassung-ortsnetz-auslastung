'use strict';
/**
 * ioBroker adapter "ortsnetz-auslastung"
 *
 * Sends the grid voltage of one or more sites every five minutes to
 * https://www.ortsnetz-auslastung.de (POST /v1/measurements) and stores the
 * answer (traffic light, storage recommendation, redispatch) in data points.
 * In addition it loads the public map so the admin tab can show it - the
 * public API does not send CORS headers, therefore the browser cannot fetch
 * it directly:
 *
 *   admin tab ──sendTo──► main.js ──HTTPS──► ortsnetz-auslastung.de
 *
 * No device ids, meter numbers or IP addresses are transmitted.
 */

const utils = require('@iobroker/adapter-core');
const M = require('./lib/measure');
const { SITE_CHANNELS, SITE_STATES, GLOBAL_STATES } = require('./lib/states');
const pkg = require('./package.json');

const API = 'https://www.ortsnetz-auslastung.de';
const VERSION = `iobroker-adapter-${pkg.version}`; // max. 32 characters (API)
const INTERVAL_MS = 5 * 60 * 1000; // API.md: one measurement per source every 300 s
const HISTORY_MS = 24 * 3600 * 1000;
const SAMPLE_KEEP_MS = 15 * 60 * 1000;
const MAP_CACHE_MS = 2 * 60 * 1000;
const ADMIN_TAB = { singleton: true, name: { de: 'Ortsnetz-Auslastung', en: 'Local grid load' }, 'fa-icon': 'bolt', order: 210 };

class OrtsnetzAuslastung extends utils.Adapter {
    constructor(options = {}) {
        super({ ...options, name: 'ortsnetz-auslastung' });
        this.sites = []; // normalised configuration
        this.samples = new Map(); // source id -> [{ts, v}]
        this.history = new Map(); // site id -> [{at,l1,l2,l3,f,st}]
        this.staticSent = new Set(); // site ids whose static fields were accepted since start
        this.counters = new Map(); // site id -> {ok, failed}
        this.publicIds = new Map(); // site id -> public id on the map
        this.mapCache = null; // {at, data, stats}
        this.mapLoading = null;
        this.publicHistory = new Map(); // public id -> {at, data}
        this.timers = [];
        this.on('ready', this.onReady.bind(this));
        this.on('stateChange', this.onStateChange.bind(this));
        this.on('message', this.onMessage.bind(this));
        this.on('unload', this.onUnload.bind(this));
    }

    /* ================================================================ */
    /* Start                                                             */
    /* ================================================================ */

    async onReady() {
        try {
            await this.start();
        } catch (e) {
            this.log.error(`Start fehlgeschlagen: ${e.message || e}`);
        }
    }

    async start() {
        this.sites = this.normaliseConfig(this.config);
        // changing the instance object makes js-controller restart the adapter - nothing more to do now
        if (await this.syncInstanceObject()) return;
        await this.createObjects();

        for (const site of this.sites) {
            this.counters.set(site.id, { ok: 0, failed: 0 });
            // counters are "since start"
            await this.setStateAsync(`${this.sid(site)}upload.uploadsOk`, 0, true);
            await this.setStateAsync(`${this.sid(site)}upload.uploadsFailed`, 0, true);
            const hist = await this.getStateAsync(`${this.sid(site)}upload.history`);
            try {
                const arr = hist && hist.val ? JSON.parse(String(hist.val)) : [];
                this.history.set(site.id, Array.isArray(arr) ? arr : []);
            } catch {
                this.history.set(site.id, []);
            }
            const pid = await this.getStateAsync(`${this.sid(site)}neighbours.publicId`);
            if (pid && pid.val) this.publicIds.set(site.id, String(pid.val));
        }

        const ids = [...new Set(this.sites.flatMap(s => Object.values(s.sources).flat()))];
        for (const id of ids) await this.subscribeForeignStatesAsync(id);

        if (!this.sites.length) {
            this.log.warn('Keine Spannungs-Datenpunkte konfiguriert - bitte in den Instanzeinstellungen Position und Datenpunkte eintragen.');
        } else {
            for (const s of this.sites) {
                const list = Object.entries(s.sources).map(([k, v]) => `${k}=${v.length}`).join(', ');
                this.log.info(`${s.name} (${s.latitude}, ${s.longitude}): ${list}${this.config.dryRun ? ' – Testbetrieb, es wird nichts gesendet' : ''}`);
            }
            // first run shortly after start, then aligned to minute 0, 5, 10, ...
            if (INTERVAL_MS - (Date.now() % INTERVAL_MS) > 75000) this.timers.push(setTimeout(() => this.uploadAll(), 15000));
            this.scheduleAligned();
        }

        if (this.config.mapEnabled) {
            const every = Math.max(5, Number(this.config.mapRefreshMin) || 15) * 60000;
            this.timers.push(setTimeout(() => this.refreshMap().catch(() => {}), 30000));
            this.timers.push(setInterval(() => this.refreshMap().catch(() => {}), every));
        }
    }

    /** prefix of the state ids of a site ('' = directly below the instance) */
    sid(site) {
        return site.id ? `${site.id}.` : '';
    }

    scheduleAligned() {
        const delay = INTERVAL_MS - (Date.now() % INTERVAL_MS) + 500;
        const t = setTimeout(() => {
            this.uploadAll();
            this.scheduleAligned();
        }, delay);
        this.timers.push(t);
        if (this.timers.length > 20) this.timers = this.timers.slice(-10); // drop handles of finished timeouts
    }

    /**
     * One instance = one site. Returns an array with zero or one site so that the
     * rest of the code (and later perhaps several sites) stays independent of that decision.
     */
    normaliseConfig(cfg) {
        const name = String(cfg.instanceName || '').trim() || this.namespace;
        const site = {
            id: '', // states live directly below the instance
            name,
            latitude: Number(cfg.latitude),
            longitude: Number(cfg.longitude),
            smartmeterModel: cfg.smartmeterModel || '',
            plantCapacityKwp: cfg.plantCapacityKwp === '' || cfg.plantCapacityKwp === null ? null : Number(cfg.plantCapacityKwp),
            batteryCapacity: cfg.batteryCapacity === '' || cfg.batteryCapacity === null ? null : Number(cfg.batteryCapacity),
            maxAgeMin: Number(cfg.maxAgeMin) > 0 ? Number(cfg.maxAgeMin) : 15,
            maxAgeFreqMin: Number(cfg.maxAgeFreqMin) > 0 ? Number(cfg.maxAgeFreqMin) : 15,
            sources: {},
        };
        for (const src of Array.isArray(cfg.sources) ? cfg.sources : []) {
            if (!src || src.enabled === false || !src.id || !M.KINDS[src.kind]) continue;
            (site.sources[src.kind] = site.sources[src.kind] || []).push(String(src.id).trim());
        }
        return Object.keys(site.sources).length ? [site] : [];
    }

    /**
     * Shows or hides the menu entry in the admin (the admin builds its menu from the
     * instance objects) and uses the configured name as title of the instance.
     * Writing the instance object restarts the adapter once; afterwards nothing differs any more.
     */
    async syncInstanceObject() {
        const id = `system.adapter.${this.namespace}`;
        const obj = await this.getForeignObjectAsync(id);
        if (!obj) return false;
        let changed = false;
        const want = this.config.showAdminTab !== false;
        if (want !== !!obj.common.adminTab) {
            if (want) {
                obj.common.adminTab = ADMIN_TAB;
                obj.common.adminUI = { ...(obj.common.adminUI || {}), tab: 'html' };
            } else {
                delete obj.common.adminTab;
                if (obj.common.adminUI) delete obj.common.adminUI.tab;
            }
            this.log.info(`Menüpunkt im Admin ${want ? 'eingeblendet' : 'ausgeblendet'} (Admin im Browser neu laden)`);
            changed = true;
        }
        const name = String(this.config.instanceName || '').trim();
        if (name && (obj.common.titleLang?.de !== name || obj.common.titleLang?.en !== name)) {
            obj.common.titleLang = { ...(obj.common.titleLang || {}), de: name, en: name };
            changed = true;
        }
        if (changed) await this.setForeignObjectAsync(id, obj);
        return changed;
    }

    async createObjects() {
        for (const [id, common] of Object.entries(GLOBAL_STATES)) {
            await this.extendObjectAsync(id, { type: 'state', common, native: {} });
        }
        await this.extendObjectAsync('map', { type: 'channel', common: { name: { de: 'Öffentliche Karte', en: 'Public map' } }, native: {} });
        for (const [ch, name] of Object.entries(SITE_CHANNELS)) {
            await this.extendObjectAsync(ch, { type: 'channel', common: { name }, native: {} });
        }
        for (const [id, common] of Object.entries(SITE_STATES)) {
            await this.extendObjectAsync(id, { type: 'state', common, native: {} });
        }
    }

    /* ================================================================ */
    /* Measuring and sending                                             */
    /* ================================================================ */

    onStateChange(id, state) {
        if (!state || state.val === null || state.val === undefined) return;
        const v = Number(state.val);
        if (!Number.isFinite(v)) return;
        const arr = this.samples.get(id) || [];
        arr.push({ ts: state.ts || Date.now(), v });
        const limit = Date.now() - SAMPLE_KEEP_MS;
        while (arr.length && arr[0].ts < limit) arr.shift();
        this.samples.set(id, arr);
    }

    /** Reads all sources of a site and picks the first fresh value per kind. */
    async pick(site, now = Date.now()) {
        const picked = {};
        for (const [kind, ids] of Object.entries(site.sources)) {
            const states = {};
            for (const id of ids) {
                try {
                    states[id] = await this.getForeignStateAsync(id);
                } catch {
                    /* missing data point: next candidate */
                }
            }
            const maxAge = ['frequency', 'batterySoc', 'gridPower'].includes(kind) ? site.maxAgeFreqMin : kind === 'pvForecast' ? 24 * 60 : site.maxAgeMin;
            const hit = M.firstFresh(ids, states, kind, maxAge, now);
            if (hit) {
                const from = now - INTERVAL_MS;
                const own = (this.samples.get(hit.id) || []).filter(s => s.ts > from && s.ts <= now);
                const current = states[hit.id];
                // the current value is already a sample if it arrived through the subscription
                const seen = own.some(s => s.ts === current.ts);
                hit.stats = M.intervalStats(own.map(s => s.v), seen ? NaN : hit.value);
            }
            picked[kind] = hit; // null = configured but nothing fresh
        }
        return picked;
    }

    async uploadAll() {
        for (const site of this.sites) {
            try {
                await this.uploadSite(site);
            } catch (e) {
                this.fail(site, `Fehler: ${e.message || e}`);
            }
        }
    }

    fail(site, msg) {
        const c = this.counters.get(site.id);
        c.failed++;
        this.setState(`${this.sid(site)}upload.uploadsFailed`, c.failed, true);
        this.setState(`${this.sid(site)}upload.lastError`, msg, true);
        this.setState('info.connection', false, true);
        this.log.warn(`${site.name}: ${msg}`);
    }

    async uploadSite(site) {
        const now = Date.now();
        await this.setStateAsync(`${this.sid(site)}upload.lastAttempt`, new Date(now).toISOString(), true);
        const picked = await this.pick(site, now);
        const { payload, error } = M.buildPayload(site, picked, {
            includeStatic: !this.staticSent.has(site.id),
            sendStatistics: this.config.sendStatistics !== false,
            version: VERSION,
            now,
            coordDecimals: Number.isInteger(Number(this.config.coordDecimals)) ? Number(this.config.coordDecimals) : 3,
        });
        if (error) return this.fail(site, `${error} - Upload übersprungen`);

        const put = (id, val) => this.setStateAsync(`${this.sid(site)}${id}`, val, true);
        await put('measurement.voltageL1', payload.l1_v);
        await put('measurement.voltageL2', payload.l2_v);
        await put('measurement.voltageL3', payload.l3_v);
        await put('measurement.frequency', payload.grid_frequency_hz ?? null);
        await put('measurement.sourceL1', picked.l1?.id || '');
        await put('measurement.sourceL2', picked.l2?.id || '');
        await put('measurement.sourceL3', picked.l3?.id || '');
        await put('measurement.sourceFrequency', picked.frequency?.id || '');
        await put('upload.lastPayload', JSON.stringify(payload));

        if (this.config.dryRun) {
            this.log.info(`${site.name}: Testbetrieb - würde senden: ${JSON.stringify(payload)}`);
            await put('upload.lastError', 'Testbetrieb (nichts gesendet)');
            await this.addHistory(site, payload, null);
            return;
        }

        let res;
        let body;
        try {
            res = await fetch(`${API}/v1/measurements`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'User-Agent': `ioBroker.ortsnetz-auslastung/${pkg.version}` },
                body: JSON.stringify(payload),
                signal: AbortSignal.timeout(10000),
            });
            const text = await res.text();
            try {
                body = JSON.parse(text);
            } catch {
                body = text;
            }
        } catch (e) {
            return this.fail(site, `Upload fehlgeschlagen: ${e.message || e}`);
        }
        await put('upload.lastHttpStatus', res.status);
        await put('upload.lastResponse', typeof body === 'string' ? body.slice(0, 2000) : JSON.stringify(body));
        if (res.status !== 202) {
            const detail = typeof body === 'string' ? body.slice(0, 300) : JSON.stringify(body).slice(0, 300);
            return this.fail(site, `HTTP ${res.status}: ${detail}`);
        }

        const c = this.counters.get(site.id);
        c.ok++;
        this.staticSent.add(site.id);
        const st = (body && body.status) || {};
        const rd = (body && body.redispatch) || {};
        await put('upload.uploadsOk', c.ok);
        await put('upload.lastUpload', payload.observed_at);
        await put('upload.lastError', '');
        await put('grid.statusOverall', st.overall || '');
        await put('grid.statusL1', st.l1 || '');
        await put('grid.statusL2', st.l2 || '');
        await put('grid.statusL3', st.l3 || '');
        await put('grid.storageRecommendation', body.storage_recommendation || '');
        await put('grid.redispatchActive', rd.active ?? null);
        await put('grid.redispatchAffectedUnits', rd.affected_units ?? null);
        await put('grid.redispatchActiveMeasures', rd.active_measures ?? null);
        await put('grid.redispatchUpdatedAt', rd.data_updated_at || '');
        await this.setStateAsync('info.connection', true, true);
        await this.addHistory(site, payload, st.overall || null);
        if (c.ok === 1) {
            this.log.info(`${site.name}: erster Upload angenommen (L1 ${payload.l1_v} V aus ${picked.l1?.id || '-'}, Ampel ${st.overall || '?'})`);
        }
    }

    async addHistory(site, p, status) {
        const arr = this.history.get(site.id) || [];
        arr.push({ at: p.observed_at, l1: p.l1_v, l2: p.l2_v, l3: p.l3_v, f: p.grid_frequency_hz ?? null, st: status });
        const limit = Date.now() - HISTORY_MS;
        while (arr.length && Date.parse(arr[0].at) < limit) arr.shift();
        this.history.set(site.id, arr);
        await this.setStateAsync(`${this.sid(site)}upload.history`, JSON.stringify(arr), true);
    }

    /* ================================================================ */
    /* Public map                                                        */
    /* ================================================================ */

    async getJson(path) {
        const res = await fetch(`${API}${path}`, {
            headers: { Accept: 'application/json', 'User-Agent': `ioBroker.ortsnetz-auslastung/${pkg.version}` },
            signal: AbortSignal.timeout(20000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status} für ${path}`);
        return res.json();
    }

    /** Loads the public map (about 0.7 MB), at most once per MAP_CACHE_MS, and updates the neighbourhood states. */
    async refreshMap(force = false) {
        if (!force && this.mapCache && Date.now() - this.mapCache.at < MAP_CACHE_MS) return this.mapCache;
        if (this.mapLoading) return this.mapLoading;
        this.mapLoading = (async () => {
            const [data, stats] = await Promise.all([
                this.getJson('/v1/map/points'),
                this.getJson('/v1/map/threshold-stats?phase=overall&period=24h').catch(() => null),
            ]);
            const points = Array.isArray(data.points) ? data.points : [];
            this.mapCache = { at: Date.now(), data, stats };
            await this.setStateAsync('map.pointCount', points.length, true);
            await this.setStateAsync('map.lastUpdate', new Date().toISOString(), true);
            if (stats) {
                await this.setStateAsync('map.normal24h', stats.normal_measurements ?? null, true);
                await this.setStateAsync('map.warning24h', stats.warning_measurements ?? null, true);
                await this.setStateAsync('map.critical24h', stats.critical_measurements ?? null, true);
            }
            const radius = Number(this.config.neighbourRadiusKm) > 0 ? Number(this.config.neighbourRadiusKm) : 25;
            for (const site of this.sites) {
                const own = M.findOwnPoint(points, site.latitude, site.longitude);
                if (own) {
                    this.publicIds.set(site.id, own.public_id);
                    await this.setStateAsync(`${this.sid(site)}neighbours.publicId`, own.public_id, true);
                }
                const n = M.neighbourStats(points, site.latitude, site.longitude, radius, own?.public_id);
                await this.setStateAsync(`${this.sid(site)}neighbours.count`, n.count, true);
                await this.setStateAsync(`${this.sid(site)}neighbours.avgVoltage`, n.avg, true);
                await this.setStateAsync(`${this.sid(site)}neighbours.minVoltage`, n.min, true);
                await this.setStateAsync(`${this.sid(site)}neighbours.maxVoltage`, n.max, true);
                await this.setStateAsync(`${this.sid(site)}neighbours.nearestKm`, n.nearestKm, true);
                const l1 = await this.getStateAsync(`${this.sid(site)}measurement.voltageL1`);
                const own1 = l1 && Number(l1.val);
                await this.setStateAsync(`${this.sid(site)}neighbours.deviation`, n.avg !== null && own1 > 0 ? Math.round((own1 - n.avg) * 100) / 100 : null, true);
            }
            return this.mapCache;
        })();
        try {
            return await this.mapLoading;
        } catch (e) {
            this.log.warn(`Karte konnte nicht geladen werden: ${e.message || e}`);
            throw e;
        } finally {
            this.mapLoading = null;
        }
    }

    /* ================================================================ */
    /* Messages from the admin tab and the settings dialog               */
    /* ================================================================ */

    async onMessage(obj) {
        if (!obj || !obj.command) return;
        let payload;
        try {
            const fn = this.commands()[obj.command];
            payload = fn ? await fn(obj.message || {}) : { error: `unbekanntes Kommando ${obj.command}` };
        } catch (e) {
            payload = { error: String(e.message || e) };
        }
        if (obj.callback && obj.from) this.sendTo(obj.from, obj.command, payload, obj.callback);
    }

    commands() {
        return {
            /** everything the map needs, points in compact arrays (~200 kB instead of 700 kB) */
            getMap: async () => {
                const cache = await this.refreshMap();
                const points = (cache.data.points || []).map(p => [
                    p.latitude,
                    p.longitude,
                    p.l1_v,
                    p.l2_v,
                    p.l3_v,
                    p.grid_frequency_hz,
                    p.stale ? 1 : 0,
                    p.public_id,
                    p.observed_at,
                    p.pv_forecast_kwh,
                    p.emergency_power_active ? 1 : 0,
                ]);
                return { loadedAt: new Date(cache.at).toISOString(), scale: cache.data.scale || M.DEFAULT_SCALE, stats: cache.stats, points, sites: await this.siteSummaries() };
            },
            getSites: async () => ({ sites: await this.siteSummaries(), dryRun: !!this.config.dryRun }),
            /** 24 h history of a site: local (what this adapter sent) and, if known, the public one */
            getHistory: async msg => {
                const site = this.sites[0];
                if (!site) return { local: [], public: null };
                const pid = this.publicIds.get(site.id);
                let pub = null;
                if (pid) {
                    const c = this.publicHistory.get(pid);
                    if (c && Date.now() - c.at < MAP_CACHE_MS) pub = c.data;
                    else {
                        pub = await this.getJson(`/v1/map/sources/${encodeURIComponent(pid)}/history`).catch(() => null);
                        if (pub) this.publicHistory.set(pid, { at: Date.now(), data: pub });
                    }
                }
                return { local: this.history.get(site.id) || [], public: pub };
            },
            /** history of any public point (popup in the map) */
            getPointHistory: async msg => {
                if (!/^[\w-]{4,64}$/.test(String(msg.id || ''))) return { error: 'ungültige Kennung' };
                return this.getJson(`/v1/map/sources/${encodeURIComponent(msg.id)}/history`);
            },
            uploadNow: async () => {
                await this.uploadAll();
                return { result: 'Upload ausgeführt', sites: await this.siteSummaries() };
            },
            /* --- settings dialog --- */
            findSources: async () => this.findSources(),
            testPayload: async msg => this.testPayload(msg),
            systemPosition: async () => this.systemPosition(),
        };
    }

    async siteSummaries() {
        const out = [];
        for (const site of this.sites) {
            const st = await this.getStatesAsync('*'); // all states of this instance (one site)
            const v = key => {
                const s = st[`${this.namespace}.${key}`];
                return s ? s.val : null;
            };
            out.push({
                instance: this.namespace,
                name: site.name,
                dryRun: !!this.config.dryRun,
                latitude: site.latitude,
                longitude: site.longitude,
                model: site.smartmeterModel,
                sources: site.sources,
                l1: v('measurement.voltageL1'),
                l2: v('measurement.voltageL2'),
                l3: v('measurement.voltageL3'),
                f: v('measurement.frequency'),
                sourceL1: v('measurement.sourceL1'),
                sourceFrequency: v('measurement.sourceFrequency'),
                statusOverall: v('grid.statusOverall'),
                statusL1: v('grid.statusL1'),
                statusL2: v('grid.statusL2'),
                statusL3: v('grid.statusL3'),
                storageRecommendation: v('grid.storageRecommendation'),
                redispatchActive: v('grid.redispatchActive'),
                redispatchAffectedUnits: v('grid.redispatchAffectedUnits'),
                redispatchActiveMeasures: v('grid.redispatchActiveMeasures'),
                lastUpload: v('upload.lastUpload'),
                lastAttempt: v('upload.lastAttempt'),
                lastError: v('upload.lastError'),
                uploadsOk: v('upload.uploadsOk'),
                uploadsFailed: v('upload.uploadsFailed'),
                publicId: v('neighbours.publicId'),
                neighbours: {
                    count: v('neighbours.count'),
                    avg: v('neighbours.avgVoltage'),
                    min: v('neighbours.minVoltage'),
                    max: v('neighbours.maxVoltage'),
                    deviation: v('neighbours.deviation'),
                    nearestKm: v('neighbours.nearestKm'),
                },
                radiusKm: Number(this.config.neighbourRadiusKm) || 25,
            });
        }
        return out;
    }

    /** Lists data points that look like voltage or frequency, with value and age - for the settings dialog. */
    async findSources() {
        const objs = await this.getForeignObjectsAsync('*', 'state');
        const rx = { voltage: /(^|[._])(voltage|uac\d?|spannung|u_?l?\d)$/i, frequency: /(^|[._])(frequency|frequenz|freq)$/i };
        const found = [];
        for (const [id, o] of Object.entries(objs)) {
            if (id.startsWith(`${this.namespace}.`) || id.startsWith('0_userdata.0.Ortsnetz')) continue;
            const role = String(o.common?.role || '');
            const unit = String(o.common?.unit || '');
            let kind = null;
            if (role === 'value.voltage' || unit === 'V' || rx.voltage.test(id)) kind = 'Spannung';
            else if (role === 'value.frequency' || unit === 'Hz' || rx.frequency.test(id)) kind = 'Frequenz';
            if (kind && (!unit || unit === 'V' || unit === 'Hz')) found.push({ id, kind });
        }
        const now = Date.now();
        const lines = [];
        for (const f of found.slice(0, 400)) {
            const st = await this.getForeignStateAsync(f.id).catch(() => null);
            const val = st ? Number(st.val) : NaN;
            if (!Number.isFinite(val)) continue;
            const ok = f.kind === 'Spannung' ? val >= 150 && val <= 300 : val >= 45 && val <= 55;
            if (!ok) continue;
            const age = Math.round((now - (st.ts || 0)) / 60000);
            lines.push({ age, text: `${f.kind.padEnd(9)} ${String(val).padStart(7)}  vor ${age} min  ${f.id}` });
        }
        lines.sort((a, b) => a.age - b.age);
        if (!lines.length) return { result: 'Keine passenden Datenpunkte mit plausiblem Wert gefunden.' };
        return { result: `Gefundene Datenpunkte (plausibler Wert, frischeste zuerst):\n\n${lines.slice(0, 60).map(l => l.text).join('\n')}` };
    }

    /** Builds the payload with the (possibly unsaved) configuration of the dialog without sending it. */
    async testPayload(msg) {
        let cfg = this.config;
        if (msg && typeof msg === 'object' && 'sources' in msg) {
            try {
                cfg = { ...this.config, ...msg, sources: typeof msg.sources === 'string' ? JSON.parse(msg.sources) : msg.sources };
            } catch {
                /* fall back to the saved configuration */
            }
        }
        const sites = this.normaliseConfig(cfg);
        if (!sites.length) return { error: 'Keine Datenpunkte konfiguriert' };
        const out = [];
        for (const site of sites) {
            const picked = await this.pick(site);
            const r = M.buildPayload(site, picked, { includeStatic: true, sendStatistics: this.config.sendStatistics !== false, version: VERSION });
            out.push(`■ ${site.name}`);
            for (const [k, p] of Object.entries(picked)) out.push(`  ${k.padEnd(11)} ${p ? `${p.value}  (${p.id}, vor ${p.ageMin} min)` : 'kein frischer Wert'}`);
            out.push(r.error ? `  ✖ ${r.error}` : `  ✔ Payload: ${JSON.stringify(r.payload)}`);
            out.push('');
        }
        return { result: out.join('\n') };
    }

    /** Takes over the position from the system settings (rounded to about 100 m). */
    async systemPosition() {
        const sys = await this.getForeignObjectAsync('system.config');
        const lat = Number(sys?.common?.latitude);
        const lon = Number(sys?.common?.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lon) || (!lat && !lon)) return { error: 'In den Systemeinstellungen ist keine Position eingetragen' };
        const r = v => Math.round(v * 1000) / 1000;
        return { native: { latitude: r(lat), longitude: r(lon) }, result: `Position ${r(lat)}, ${r(lon)} übernommen` };
    }

    onUnload(callback) {
        try {
            for (const t of this.timers) {
                clearTimeout(t);
                clearInterval(t);
            }
            this.setState('info.connection', false, true);
        } finally {
            callback();
        }
    }
}

if (require.main !== module) {
    module.exports = options => new OrtsnetzAuslastung(options);
} else {
    (() => new OrtsnetzAuslastung())();
}
