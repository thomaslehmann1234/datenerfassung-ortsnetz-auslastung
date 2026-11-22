/* global io, L */
/**
 * Admin tab "Ortsnetz-Auslastung".
 *
 * Plain JavaScript without a build step. The tab never talks to
 * ortsnetz-auslastung.de itself (the public API sends no CORS headers):
 *
 *   tab ──sendTo──► ortsnetz-auslastung.<n> ──HTTPS──► ortsnetz-auslastung.de
 *
 * The map comes from the first running instance, the own measuring points
 * from every running instance (one instance = one site).
 */
(() => {
  'use strict';

  const ADAPTER = 'ortsnetz-auslastung';
  const $ = sel => document.querySelector(sel);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  const num = (v, d = 1) => (Number.isFinite(Number(v)) && v !== null && v !== '' && Number(v) !== -1 ? Number(v).toFixed(d).replace('.', ',') : '–');
  const fmtTime = iso => (iso ? new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '–');
  const ago = iso => {
    if (!iso) return '';
    const m = Math.round((Date.now() - Date.parse(iso)) / 60000);
    return m < 1 ? 'gerade eben' : m < 60 ? `vor ${m} min` : `vor ${Math.round(m / 6) / 10} h`;
  };

  /* ---------- theme (admin passes ?react=dark|light|blue|colored) ---------- */
  const qs = new URLSearchParams(location.search);
  const theme = qs.get('react') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = theme === 'dark' || theme === 'blue' ? 'dark' : 'light';

  /* ---------- classification, same as the public map ---------- */
  let SCALE = { criticalLow: 207, warningLow: 218, warningHigh: 242, criticalHigh: 253, colors: ['#1d4ed8', '#38bdf8', '#16a34a', '#f59e0b', '#b91c1c'] };
  const BANDS = {
    'low-critical': { i: 0, s: 2, label: 'Unterspannung kritisch' },
    'low-warning': { i: 1, s: 1, label: 'Unterspannung Warnung' },
    normal: { i: 2, s: 0, label: 'normal' },
    'high-warning': { i: 3, s: 1, label: 'Überspannung Warnung' },
    'high-critical': { i: 4, s: 2, label: 'Überspannung kritisch' },
  };
  function band(v) {
    if (!Number.isFinite(v) || v <= 0) return null;
    if (v < SCALE.criticalLow) return 'low-critical';
    if (v < SCALE.warningLow) return 'low-warning';
    if (v > SCALE.criticalHigh) return 'high-critical';
    if (v > SCALE.warningHigh) return 'high-warning';
    return 'normal';
  }
  function worst(values) {
    const b = values.map(band).filter(Boolean);
    b.sort((x, y) => BANDS[y].s - BANDS[x].s || BANDS[x].i - BANDS[y].i);
    return b[0] || null;
  }
  const colorOf = key => (key ? SCALE.colors[BANDS[key].i] : '#94a3b8');

  /* ---------- socket ---------- */
  let socket;
  const send = (instance, command, message = {}) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Zeitüberschreitung (${instance})`)), 45000);
      socket.emit('sendTo', instance, command, message, res => {
        clearTimeout(timer);
        if (res && res.error) reject(new Error(res.error));
        else resolve(res);
      });
    });
  const emit = (...args) => new Promise(resolve => socket.emit(...args, (err, res) => resolve(err ? null : res)));

  async function runningInstances() {
    const view = await emit('getObjectView', 'system', 'instance', { startkey: `system.adapter.${ADAPTER}.`, endkey: `system.adapter.${ADAPTER}.香` });
    const rows = (view && view.rows) || [];
    const out = [];
    for (const r of rows) {
      const id = r.id.replace('system.adapter.', '');
      const alive = await emit('getState', `${r.id}.alive`);
      out.push({ id, alive: !!(alive && alive.val), enabled: !!r.value?.common?.enabled, title: r.value?.common?.titleLang?.de || r.value?.common?.native?.instanceName || id });
    }
    return out;
  }

  function banner(html, cls = '') {
    $('#banner').innerHTML = html ? `<div class="b ${cls}">${html}</div>` : '';
  }

  /* ================================================================ */
  /* Map                                                               */
  /* ================================================================ */

  let map;
  let pointLayer;
  let ownLayer;
  let points = [];
  let sites = [];
  const hidden = new Set(['stale']);
  let fittedOnce = false;

  function initMap() {
    map = L.map('map', { preferCanvas: true, zoomControl: true, worldCopyJump: false }).setView([51.2, 10.4], 6);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>-Mitwirkende',
    }).addTo(map);
    pointLayer = L.layerGroup().addTo(map);
    ownLayer = L.layerGroup().addTo(map);
    document.querySelectorAll('.legend input[data-f]').forEach(cb => {
      cb.checked = !hidden.has(cb.dataset.f);
      cb.addEventListener('change', () => {
        cb.checked ? hidden.delete(cb.dataset.f) : hidden.add(cb.dataset.f);
        renderPoints();
      });
    });
  }

  const P = a => ({ lat: a[0], lon: a[1], l1: a[2], l2: a[3], l3: a[4], f: a[5], stale: !!a[6], id: a[7], at: a[8], pv: a[9], emergency: !!a[10] });

  function renderPoints() {
    pointLayer.clearLayers();
    const counts = { 'high-critical': 0, 'high-warning': 0, normal: 0, 'low-warning': 0, 'low-critical': 0, stale: 0 };
    const ownIds = new Set(sites.map(s => s.publicId).filter(Boolean));
    // draw normal first so that warnings stay on top
    const sorted = points.map(P).map(p => ({ p, key: worst([p.l1, p.l2, p.l3]) })).sort((a, b) => (a.key ? BANDS[a.key].s : -1) - (b.key ? BANDS[b.key].s : -1));
    for (const { p, key } of sorted) {
      if (p.stale) counts.stale++;
      else if (key) counts[key]++;
      if (ownIds.has(p.id)) continue; // drawn by the own layer
      if (p.stale ? hidden.has('stale') : key && hidden.has(key)) continue;
      const m = L.circleMarker([p.lat, p.lon], {
        radius: p.stale ? 4 : 6,
        color: '#fff',
        weight: 1,
        fillColor: p.stale ? '#94a3b8' : colorOf(key),
        fillOpacity: p.stale ? 0.5 : 0.9,
      });
      m.bindPopup(() => popupHtml(p, key), { maxWidth: 360 });
      m.on('popupopen', e => loadPointHistory(p, e.popup));
      m.addTo(pointLayer);
    }
    for (const [k, n] of Object.entries(counts)) {
      const el = $(`#n-${k}`);
      if (el) el.textContent = n.toLocaleString('de-DE');
    }
    $('#pointCount').textContent = `${points.length.toLocaleString('de-DE')} Punkte`;
  }

  function popupHtml(p, key, title) {
    return `<div class="pp">
      <h4>${esc(title || 'Messpunkt')} ${key ? `<span class="chip ${key}">${BANDS[key].label}</span>` : ''}</h4>
      <table>
        <tr><td>L1</td><td>${num(p.l1)} V</td></tr>
        <tr><td>L2</td><td>${num(p.l2)} V</td></tr>
        <tr><td>L3</td><td>${num(p.l3)} V</td></tr>
        <tr><td>Frequenz</td><td>${num(p.f, 2)} Hz</td></tr>
        ${Number.isFinite(p.pv) ? `<tr><td>PV-Prognose heute</td><td>${num(p.pv)} kWh</td></tr>` : ''}
      </table>
      <div class="muted">${p.stale ? '⚠️ veraltet · ' : ''}${fmtTime(p.at)} (${ago(p.at)})</div>
      <div class="hist muted">Verlauf wird geladen …</div>
    </div>`;
  }

  async function loadPointHistory(p, popup) {
    try {
      const data = await send(mapInstance, 'getPointHistory', { id: p.id });
      const el = popup.getElement()?.querySelector('.hist');
      if (el) {
        el.classList.remove('muted');
        el.innerHTML = chart(normSamples(data.samples, 'public'), { width: 320, height: 130 });
        popup.update();
      }
    } catch (e) {
      const el = popup.getElement()?.querySelector('.hist');
      if (el) el.textContent = `Verlauf nicht verfügbar (${e.message})`;
    }
  }

  function renderOwnOnMap() {
    ownLayer.clearLayers();
    const byId = new Map(points.map(P).map(p => [p.id, p]));
    const bounds = [];
    for (const s of sites) {
      if (!Number.isFinite(s.latitude) || !Number.isFinite(s.longitude)) continue;
      const pub = s.publicId && byId.get(s.publicId);
      const p = pub || { lat: s.latitude, lon: s.longitude, l1: s.l1, l2: s.l2, l3: s.l3, f: s.f, at: s.lastUpload, id: s.publicId };
      const key = worst([p.l1, p.l2, p.l3]);
      const m = L.circleMarker([s.latitude, s.longitude], { radius: 11, color: getComputedStyle(document.documentElement).getPropertyValue('--own').trim() || '#7c3aed', weight: 4, fillColor: colorOf(key), fillOpacity: 1 });
      m.bindTooltip(`🏠 ${esc(s.name)}`, { permanent: true, direction: 'top', offset: [0, -12] });
      m.bindPopup(() => popupHtml(p, key, `🏠 ${s.name}`), { maxWidth: 360 });
      m.on('popupopen', async e => {
        const el = e.popup.getElement()?.querySelector('.hist');
        try {
          const h = await send(s.instance, 'getHistory');
          if (el) {
            el.classList.remove('muted');
            el.innerHTML = chart(bestHistory(h), { width: 320, height: 130 });
            e.popup.update();
          }
        } catch (err) {
          if (el) el.textContent = err.message;
        }
      });
      m.addTo(ownLayer);
      bounds.push([s.latitude, s.longitude]);
    }
    if (!fittedOnce && bounds.length) {
      fittedOnce = true;
      if (bounds.length === 1) map.setView(bounds[0], 9);
      else map.fitBounds(bounds, { padding: [60, 60], maxZoom: 9 });
    }
  }

  /* ================================================================ */
  /* Chart (SVG, 24 h)                                                  */
  /* ================================================================ */

  function normSamples(samples, kind) {
    return (samples || []).map(s =>
      kind === 'public' ? { at: Date.parse(s.at), l1: s.l1_v, l2: s.l2_v, l3: s.l3_v, f: s.grid_frequency_hz } : { at: Date.parse(s.at), l1: s.l1, l2: s.l2, l3: s.l3, f: s.f },
    );
  }
  function bestHistory(h) {
    const local = normSamples(h && h.local, 'local');
    const pub = normSamples(h && h.public && h.public.samples, 'public');
    // the public history covers 24 h right after installation; the local one is complete afterwards
    return pub.length > local.length ? pub : local;
  }

  function chart(samples, { width = 560, height = 170 } = {}) {
    const end = Date.now();
    const start = end - 24 * 3600 * 1000;
    const data = samples.filter(s => s.at >= start);
    const vals = data.flatMap(s => [s.l1, s.l2, s.l3]).filter(v => Number.isFinite(v) && v > 0);
    if (data.length < 2 || !vals.length) return '<div class="muted">Noch kein Verlauf vorhanden.</div>';
    const lo = Math.min(SCALE.warningLow - 4, Math.floor(Math.min(...vals) - 2));
    const hi = Math.max(SCALE.warningHigh + 4, Math.ceil(Math.max(...vals) + 2));
    const L0 = 34, R = 6, T = 8, B = 18;
    const x = t => L0 + ((t - start) / (end - start)) * (width - L0 - R);
    const y = v => T + (1 - (v - lo) / (hi - lo)) * (height - T - B);
    const grid = [];
    const step = hi - lo > 40 ? 10 : 5;
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
      grid.push(`<line class="grid" x1="${L0}" x2="${width - R}" y1="${y(v)}" y2="${y(v)}"/><text class="lbl" x="${L0 - 4}" y="${y(v) + 3}" text-anchor="end">${v}</text>`);
    }
    for (let h = 0; h <= 24; h += 6) {
      const t = start + h * 3600 * 1000;
      const lbl = new Date(t).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
      grid.push(`<text class="lbl" x="${x(t)}" y="${height - 4}" text-anchor="${h === 0 ? 'start' : h === 24 ? 'end' : 'middle'}">${lbl}</text>`);
    }
    const bands = `<rect class="band-ok" x="${L0}" width="${width - L0 - R}" y="${y(SCALE.warningHigh)}" height="${y(SCALE.warningLow) - y(SCALE.warningHigh)}"/>`;
    const colors = { l1: '#2563eb', l2: '#db2777', l3: '#ea580c' };
    const lines = ['l1', 'l2', 'l3']
      .map(k => {
        const segs = [];
        let cur = [];
        for (const s of data) {
          if (Number.isFinite(s[k]) && s[k] > 0) cur.push(`${x(s.at).toFixed(1)},${y(s[k]).toFixed(1)}`);
          else if (cur.length) segs.push(cur), (cur = []);
        }
        if (cur.length) segs.push(cur);
        return segs.filter(sg => sg.length > 1).map(sg => `<polyline fill="none" stroke="${colors[k]}" stroke-width="2" stroke-linejoin="round" points="${sg.join(' ')}"/>`).join('');
      })
      .join('');
    const legend = ['l1', 'l2', 'l3']
      .filter(k => data.some(s => Number.isFinite(s[k]) && s[k] > 0))
      .map(k => `<tspan fill="${colors[k]}">● ${k.toUpperCase()} </tspan>`)
      .join('');
    return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Spannungsverlauf 24 Stunden">${bands}${grid.join('')}${lines}<text class="lbl" x="${width - R}" y="${T + 8}" text-anchor="end">${legend}</text></svg>`;
  }

  /* ================================================================ */
  /* Own sites                                                         */
  /* ================================================================ */

  const REC = { charge: '🔋 laden', discharge: '⚡ entladen', none: 'keine Aktion' };
  const STATUS = { green: 'grün', yellow: 'gelb', red: 'rot', unavailable: 'nicht gemessen' };

  function renderSites(instances) {
    const box = $('#sites');
    if (!instances.length) {
      box.innerHTML = '<div class="empty">Keine Instanz des Adapters gefunden.</div>';
      return;
    }
    const stopped = instances.filter(i => !i.alive);
    let html = sites
      .map(s => {
        const key = worst([s.l1, s.l2, s.l3]);
        const kpi = (lbl, v, unit, d = 1) => `<div class="kpi l" style="--c:${unit === 'V' ? colorOf(band(Number(v))) : 'var(--line)'}"><small>${lbl}</small><b>${num(v, d)} <span>${unit}</span></b></div>`;
        const n = s.neighbours || {};
        const dev = n.deviation === null || n.deviation === undefined ? NaN : Number(n.deviation);
        return `<div class="card" data-instance="${esc(s.instance)}">
          <h3>🏠 ${esc(s.name)} <span class="chip ${esc(s.statusOverall || key || '')}">${esc(STATUS[s.statusOverall] || (key ? BANDS[key].label : 'keine Bewertung'))}</span><span class="sp"></span>
            <button class="btn" data-upload="${esc(s.instance)}" title="Jetzt messen und senden">⬆️ Jetzt senden</button></h3>
          <div class="muted">${esc(s.instance)} · ${num(s.latitude, 3)}, ${num(s.longitude, 3)}${s.model ? ` · ${esc(s.model)}` : ''}${s.dryRun ? ' · <b>Testbetrieb</b>' : ''}</div>
          <div class="kpis">${kpi('L1', s.l1, 'V')}${kpi('L2', s.l2, 'V')}${kpi('L3', s.l3, 'V')}${kpi('Frequenz', s.f, 'Hz', 2)}</div>
          <dl class="rows">
            <dt>Ampel je Phase</dt><dd>${['L1', 'L2', 'L3'].map(p => `${p} ${esc(STATUS[s[`status${p}`]] || '–')}`).join(' · ')}</dd>
            <dt>Speicherempfehlung</dt><dd>${esc(REC[s.storageRecommendation] || '–')}</dd>
            <dt>Redispatch (50 km)</dt><dd>${s.redispatchActive === true ? '⚠️ aktiv' : s.redispatchActive === false ? 'nicht aktiv' : 'unbekannt'}${Number.isFinite(s.redispatchAffectedUnits) ? ` · ${s.redispatchAffectedUnits} Anlagen, ${s.redispatchActiveMeasures ?? '–'} Maßnahmen` : ''}</dd>
            <dt>Umgebung (${esc(s.radiusKm)} km)</dt><dd>${n.count === 0 ? 'keine weiteren Messpunkte im Umkreis' : Number.isFinite(n.count) ? `${n.count} Messpunkte · Ø ${num(n.avg)} V (${num(n.min)}–${num(n.max)} V)${Number.isFinite(dev) ? ` · eigene L1 ${dev >= 0 ? '+' : ''}${num(dev)} V` : ''}` : '–'}</dd>
            <dt>Quelle L1</dt><dd class="muted">${esc(s.sourceL1 || '–')}</dd>
            <dt>Quelle Frequenz</dt><dd class="muted">${esc(s.sourceFrequency || '–')}</dd>
            <dt>Letzter Upload</dt><dd>${fmtTime(s.lastUpload)} <span class="muted">${ago(s.lastUpload)} · ${s.uploadsOk ?? 0} ok / ${s.uploadsFailed ?? 0} fehlgeschlagen seit Start</span></dd>
            ${s.lastError ? `<dt>Meldung</dt><dd class="err">${esc(s.lastError)}</dd>` : ''}
            <dt>Auf der Karte</dt><dd>${s.publicId ? `<a href="#" data-goto="${esc(s.instance)}">anzeigen</a>` : '<span class="muted">noch nicht gefunden</span>'}</dd>
          </dl>
          <div class="hist" data-hist="${esc(s.instance)}"><div class="muted" style="margin-top:10px">Verlauf wird geladen …</div></div>
        </div>`;
      })
      .join('');
    if (stopped.length) {
      html += `<div class="card"><h3>⏸️ Nicht laufend</h3><div class="muted">${stopped.map(i => esc(i.id)).join(', ')} – Instanz starten, um Werte zu sehen.</div></div>`;
    }
    box.innerHTML = html || '<div class="empty">Keine laufende Instanz.</div>';

    box.querySelectorAll('[data-upload]').forEach(b =>
      b.addEventListener('click', async () => {
        b.disabled = true;
        b.textContent = '⏳ sende …';
        try {
          await send(b.dataset.upload, 'uploadNow');
        } catch (e) {
          banner(esc(e.message), 'err');
        }
        await loadSites(lastInstances);
      }),
    );
    box.querySelectorAll('[data-goto]').forEach(a =>
      a.addEventListener('click', ev => {
        ev.preventDefault();
        const s = sites.find(x => x.instance === a.dataset.goto);
        showView('map');
        map.setView([s.latitude, s.longitude], 12);
      }),
    );
    for (const s of sites) {
      send(s.instance, 'getHistory')
        .then(h => {
          const el = box.querySelector(`[data-hist="${CSS.escape(s.instance)}"]`);
          if (el) el.innerHTML = `<div class="muted" style="margin-top:10px">Spannung der letzten 24 Stunden</div>${chart(bestHistory(h))}`;
        })
        .catch(() => {});
    }
  }

  /* ================================================================ */
  /* Loading                                                           */
  /* ================================================================ */

  let mapInstance = null;
  let lastInstances = [];

  async function loadSites(instances) {
    const all = [];
    for (const i of instances.filter(x => x.alive)) {
      try {
        const r = await send(i.id, 'getSites');
        all.push(...(r.sites || []));
      } catch (e) {
        banner(`${esc(i.id)}: ${esc(e.message)}`, 'err');
      }
    }
    sites = all;
    renderSites(instances);
    if (map) renderOwnOnMap();
  }

  async function loadAll() {
    banner('');
    $('#sub').textContent = 'lade …';
    const instances = await runningInstances();
    lastInstances = instances;
    const alive = instances.filter(i => i.alive);
    if (!alive.length) {
      $('#sub').textContent = 'keine laufende Instanz';
      banner(instances.length ? 'Keine Instanz des Adapters läuft – bitte unter „Instanzen“ starten.' : 'Es ist noch keine Instanz angelegt.');
      renderSites(instances);
      return;
    }
    mapInstance = alive[0].id;
    await loadSites(instances);
    try {
      const r = await send(mapInstance, 'getMap');
      if (r.scale && Array.isArray(r.scale.colors)) {
        SCALE = r.scale;
        r.scale.colors.forEach((c, i) => document.documentElement.style.setProperty(`--c${i}`, c));
      }
      points = r.points || [];
      renderPoints();
      renderOwnOnMap();
      $('#loadedAt').textContent = `geladen ${fmtTime(r.loadedAt)}`;
      if (r.stats) {
        const total = (r.stats.normal_measurements || 0) + (r.stats.warning_measurements || 0) + (r.stats.critical_measurements || 0);
        const pct = v => (total ? `${((v / total) * 100).toFixed(1).replace('.', ',')} %` : '–');
        $('#stats24').textContent = `Letzte 24 h bundesweit: ${total.toLocaleString('de-DE')} Messungen · Warnung ${pct(r.stats.warning_measurements)} · kritisch ${pct(r.stats.critical_measurements)}`;
      }
      $('#sub').textContent = `${alive.length} Instanz${alive.length > 1 ? 'en' : ''} · ${sites.map(s => s.name).join(', ')}`;
    } catch (e) {
      banner(`Karte konnte nicht geladen werden: ${esc(e.message)}`, 'err');
      $('#sub').textContent = 'Fehler';
    }
  }

  function showView(v) {
    document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('on', b.dataset.view === v));
    document.querySelectorAll('.view').forEach(s => s.classList.toggle('active', s.id === `view-${v}`));
    if (v === 'map' && map) setTimeout(() => map.invalidateSize(), 0);
    try {
      localStorage.setItem('ortsnetz-tab-view', v);
    } catch {
      /* private mode */
    }
  }

  /* ================================================================ */
  /* Start                                                             */
  /* ================================================================ */

  function start() {
    if (typeof io === 'undefined') {
      banner('Der Socket-Client des Admin ließ sich nicht laden (<code>lib/js/socket.io.js</code>).', 'err');
      return;
    }
    if (typeof L === 'undefined') {
      banner('Leaflet ließ sich nicht laden.', 'err');
      return;
    }
    initMap();
    document.querySelectorAll('#nav button').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
    $('#reload').addEventListener('click', () => loadAll());
    let saved = 'map';
    try {
      saved = localStorage.getItem('ortsnetz-tab-view') || 'map';
    } catch {
      /* private mode */
    }
    showView(saved);

    socket = io.connect(`${location.protocol}//${location.host}/`, { name: 'ortsnetz-auslastung-tab', query: 'ws=true' });
    let first = true;
    const up = () => {
      if (first) {
        first = false;
        loadAll();
      }
    };
    socket.on('connect', up);
    socket.on('reconnect', up);
    // refresh every 5 minutes, like the uploads
    setInterval(() => !document.hidden && loadAll(), 5 * 60 * 1000);
  }

  start();
})();
