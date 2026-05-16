/* Pitwall admin panel — vanilla JS SPA */

'use strict';

const state = {
  status:        {},
  system:        {},
  modules:       [],
  activeSection: 'overview',
  previewOpen:   false,
  sliderDragging: false,
};

// ── API helpers ──────────────────────────────────────────────────────────

async function apiFetch(url, options = {}) {
  try {
    const r = await fetch(url, options);
    if (!r.ok) { console.warn('API', r.status, url); return null; }
    return await r.json();
  } catch (e) {
    console.error('fetch error', url, e);
    return null;
  }
}

async function apiPost(url, body = {}) {
  return apiFetch(url, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });
}

// ── Polling ──────────────────────────────────────────────────────────────

async function pollStatus() {
  const s = await apiFetch('/api/status');
  if (!s) return;
  state.status = s;

  document.getElementById('tb-mode').textContent = s.mode.toUpperCase();
  document.getElementById('tb-fps').textContent  = s.fps + ' FPS';

  document.getElementById('power-btn').classList.toggle('active', !s.power);
  document.getElementById('preview-btn').hidden = !s.stub;
  document.getElementById('preview-meta').textContent =
    s.mode.toUpperCase() + ' · ' + s.fps + ' FPS';

  if (!state.sliderDragging) {
    document.getElementById('brightness-slider').value = s.brightness;
    document.getElementById('brightness-val').textContent = s.brightness;
  }

  if (state.activeSection === 'overview')        updateOverviewStats();
  if (state.activeSection === 'modules')         updateModuleGrid();
}

async function pollSystem() {
  const sys = await apiFetch('/api/system');
  if (!sys) return;
  state.system = sys;
  if (state.activeSection === 'overview') updateOverviewStats();
}

async function loadModules() {
  const modules = await apiFetch('/api/modules');
  if (!modules) return;
  state.modules = modules;

  // Refresh module grid if visible
  if (state.activeSection === 'modules') updateModuleGrid();

  // Populate module-settings select
  const sel = document.getElementById('mod-cfg-select');
  const prev = sel.value;
  sel.innerHTML = '';
  modules.forEach(m => {
    const opt = document.createElement('option');
    opt.value       = m.name;
    opt.textContent = m.name + (m.is_active ? ' (active)' : '');
    sel.appendChild(opt);
  });
  if (prev && modules.find(m => m.name === prev)) sel.value = prev;
}

// ── Overview ─────────────────────────────────────────────────────────────

function updateOverviewStats() {
  const s   = state.status;
  const sys = state.system;

  const cpuTemp = sys.cpu_temp_c;
  const cpuCls  = cpuTemp === null || cpuTemp === undefined
    ? 'dim' : cpuTemp > 80 ? 'err' : cpuTemp > 65 ? 'warn' : 'ok';
  const cpuPct  = cpuTemp != null ? Math.min(Math.round(cpuTemp), 100) : 0;

  const memPct = sys.mem_pct;
  const memCls = memPct == null ? 'dim' : memPct > 85 ? 'err' : memPct > 70 ? 'warn' : 'ok';

  document.getElementById('stats-grid').innerHTML = [
    statCard('CPU TEMP',
      cpuTemp != null ? cpuTemp + '°C' : '—', cpuCls,
      cpuTemp != null ? cpuPct : null, cpuCls),
    statCard('MEMORY',
      sys.mem_used_mb != null ? sys.mem_used_mb + ' MB' : '—', memCls,
      memPct != null ? memPct : null, memCls,
      sys.mem_total_mb ? sys.mem_used_mb + ' / ' + sys.mem_total_mb + ' MB' : null),
    statCard('UPTIME',   sys.uptime || '—', 'dim'),
    statCard('LAN IP',   sys.ip || '—', 'dim'),
    statCard('MODE',
      s.mode ? s.mode.toUpperCase() : '—',
      s.power === false ? 'warn' : 'ok', null, null,
      s.power === false ? 'display off' : 'display on'),
    statCard('FPS', s.fps != null ? String(s.fps) : '—', 'dim'),
  ].join('');
}

function statCard(label, value, valueCls, pct, pctCls, sub) {
  const bar = pct != null
    ? `<div class="progress-bar"><div class="progress-fill ${pctCls || ''}" style="width:${pct}%"></div></div>`
    : '';
  const subLine = sub ? `<div class="stat-sub">${sub}</div>` : '';
  return `<div class="stat-card">
    <div class="stat-label">${label}</div>
    <div class="stat-value ${valueCls || ''}">${value}</div>
    ${subLine}${bar}
  </div>`;
}

function buildDebugBar() {
  const ALERTS = [
    { kind: 'watch',       label: 'WATCH' },
    { kind: 'stsw',        label: 'STSW' },
    { kind: 'destructive', label: 'DESTRUCTIVE' },
    { kind: 'tornado',     label: 'TORNADO' },
    { kind: 'pds',         label: 'PDS TORNADO' },
    { kind: 'flood',       label: 'FLOOD' },
    { kind: 'clear',       label: 'CLEAR' },
  ];
  document.getElementById('debug-tools').innerHTML =
    '<div class="debug-row">' +
    ALERTS.map(a =>
      `<button class="btn-debug" data-kind="${a.kind}">${a.label}</button>`
    ).join('') +
    '</div>';

  document.querySelectorAll('.btn-debug').forEach(btn => {
    btn.addEventListener('click', () => apiPost('/api/debug/alert/' + btn.dataset.kind));
  });
}

// ── Modules ──────────────────────────────────────────────────────────────

function updateModuleGrid() {
  const active = state.status.mode;
  document.getElementById('module-grid').innerHTML = state.modules.map(m => `
    <div class="module-card ${m.name === active ? 'active' : ''}" data-name="${m.name}">
      <div class="module-name">
        ${m.name === active ? '<span class="module-dot"></span>' : ''}
        ${m.name.toUpperCase()}
      </div>
      <div class="module-desc">${m.description}</div>
      <div class="module-badge">${m.default_fps} FPS DEFAULT</div>
    </div>
  `).join('');

  document.querySelectorAll('.module-card').forEach(card => {
    card.addEventListener('click', async () => {
      await apiPost('/api/module/' + card.dataset.name + '/activate');
      await pollStatus();
      await loadModules();
    });
  });
}

// ── Module settings ───────────────────────────────────────────────────────

async function loadModuleConfig() {
  const sel  = document.getElementById('mod-cfg-select');
  const name = sel.value;
  if (!name) return;

  const cfg = await apiFetch('/api/module/' + name + '/config');
  if (!cfg) return;

  renderModuleConfigForm(name, cfg);
}

function renderModuleConfigForm(name, cfg) {
  const container = document.getElementById('mod-cfg-form');
  container.innerHTML = '';

  const schema = cfg.__schema__ || {};
  const form   = document.createElement('div');
  form.className = 'config-form';

  Object.entries(cfg).forEach(([key, val]) => {
    if (key === '__schema__') return;
    const fieldSchema = schema[key] || {};
    const group = document.createElement('div');
    group.className = 'form-group';

    const label = document.createElement('label');
    label.className   = 'form-label';
    label.textContent = (fieldSchema.label || key).toUpperCase().replace(/_/g, ' ');
    label.htmlFor     = 'mcfg-' + key;
    group.appendChild(label);

    if (fieldSchema.type === 'select') {
      const sel = document.createElement('select');
      sel.id        = 'mcfg-' + key;
      sel.className = 'form-select';
      (fieldSchema.options || []).forEach(opt => {
        const o = document.createElement('option');
        o.value       = opt.value;
        o.textContent = opt.label;
        if (opt.value === val) o.selected = true;
        sel.appendChild(o);
      });
      group.appendChild(sel);
    } else if (typeof val === 'boolean') {
      const wrap = document.createElement('label');
      wrap.className = 'form-toggle';
      const cb = document.createElement('input');
      cb.type    = 'checkbox';
      cb.checked = val;
      cb.id      = 'mcfg-' + key;
      const lbl = document.createElement('span');
      lbl.className   = 'form-toggle-lbl';
      lbl.textContent = val ? 'enabled' : 'disabled';
      cb.addEventListener('change', () => { lbl.textContent = cb.checked ? 'enabled' : 'disabled'; });
      wrap.appendChild(cb);
      wrap.appendChild(lbl);
      group.appendChild(wrap);
    } else {
      const input = document.createElement('input');
      input.id        = 'mcfg-' + key;
      input.className = 'form-input';
      if (typeof val === 'number') {
        input.type  = 'number';
        input.step  = Number.isInteger(val) ? '1' : 'any';
        input.value = val != null ? val : '';
      } else {
        input.type  = 'text';
        input.value = val != null ? val : '';
      }
      group.appendChild(input);
    }

    form.appendChild(group);
  });

  const btn = makeBtn('SAVE', async () => {
    const data = {};
    Object.entries(cfg).forEach(([key, orig]) => {
      if (key === '__schema__') return;
      const el = document.getElementById('mcfg-' + key);
      if (!el) return;
      const fieldSchema = schema[key] || {};
      if (fieldSchema.type === 'select') data[key] = el.value;
      else if (typeof orig === 'boolean')     data[key] = el.checked;
      else if (typeof orig === 'number')      data[key] = Number.isInteger(orig) ? parseInt(el.value) : parseFloat(el.value);
      else                                    data[key] = el.value;
    });
    await apiPost('/api/module/' + name + '/config', data);
    flashSaved(btn);
  });

  form.appendChild(btn);
  container.appendChild(form);
}

// ── Global config ─────────────────────────────────────────────────────────

async function loadGlobalConfig() {
  const cfg = await apiFetch('/api/config');
  if (!cfg) return;
  renderGlobalConfigForm(cfg);
}

function renderGlobalConfigForm(cfg) {
  const FIELDS = [
    { key: 'multiviewer_host',         label: 'MULTIVIEWER HOST',        type: 'text' },
    { key: 'multiviewer_auto_switch',  label: 'MULTIVIEWER AUTO-SWITCH',  type: 'bool' },
    { key: 'multiviewer_hold_seconds', label: 'HOLD BEFORE SWITCH (S)',   type: 'int' },
    { key: 'gpio_slowdown',            label: 'GPIO SLOWDOWN',            type: 'int' },
    { key: 'brightness',               label: 'DEFAULT BRIGHTNESS (0-100)', type: 'int', min: 0, max: 100 },
  ];

  const container = document.getElementById('global-config-form');
  container.innerHTML = '';
  const form = document.createElement('div');
  form.className = 'config-form';

  FIELDS.forEach(f => {
    const val   = cfg[f.key];
    const group = document.createElement('div');
    group.className = 'form-group';

    const label = document.createElement('label');
    label.className   = 'form-label';
    label.textContent = f.label;
    group.appendChild(label);

    if (f.type === 'bool') {
      const wrap = document.createElement('label');
      wrap.className = 'form-toggle';
      const cb = document.createElement('input');
      cb.type    = 'checkbox';
      cb.id      = 'gcfg-' + f.key;
      cb.checked = !!val;
      const lbl = document.createElement('span');
      lbl.className   = 'form-toggle-lbl';
      lbl.textContent = val ? 'enabled' : 'disabled';
      cb.addEventListener('change', () => {
        lbl.textContent = cb.checked ? 'enabled' : 'disabled';
      });
      wrap.appendChild(cb);
      wrap.appendChild(lbl);
      group.appendChild(wrap);
    } else {
      const input = document.createElement('input');
      input.id        = 'gcfg-' + f.key;
      input.className = 'form-input';
      input.type      = f.type === 'int' ? 'number' : 'text';
      if (f.type === 'int') input.step = '1';
      if (f.min !== undefined) input.min = f.min;
      if (f.max !== undefined) input.max = f.max;
      input.value = val != null ? val : '';
      group.appendChild(input);
    }

    form.appendChild(group);
  });

  const btn = makeBtn('SAVE', async () => {
    const data = {};
    FIELDS.forEach(f => {
      const el = document.getElementById('gcfg-' + f.key);
      if (!el) return;
      if (f.type === 'bool') data[f.key] = el.checked;
      else if (f.type === 'int') data[f.key] = parseInt(el.value);
      else data[f.key] = el.value;
    });
    await apiPost('/api/config', data);
    flashSaved(btn);
  });

  form.appendChild(btn);
  container.appendChild(form);
}

// ── Network ───────────────────────────────────────────────────────────────

async function loadNetworkInfo() {
  const [status, sys, cfg] = await Promise.all([
    apiFetch('/api/status'),
    apiFetch('/api/system'),
    apiFetch('/api/config'),
  ]);

  const rows = [
    { key: 'LAN IP',        val: sys?.ip || '—' },
    { key: 'WIFI SSID',     val: cfg?.wifi_ssid || '(none)' },
    { key: 'PROVISIONED',   val: cfg?.provisioning_complete
        ? badge('YES', 'ok') : badge('NO', 'warn') },
    { key: 'STUB MODE',     val: status?.stub
        ? badge('YES — no LED hardware', 'warn')
        : badge('NO — hardware active', 'ok') },
    { key: 'UPTIME',        val: sys?.uptime || '—' },
    { key: 'API VERSION',   val: 'pitwall/1.0' },
  ];

  document.getElementById('network-info').innerHTML =
    rows.map(r =>
      `<div class="network-row">
         <span class="network-key">${r.key}</span>
         <span class="network-val">${r.val}</span>
       </div>`
    ).join('');
}

function badge(text, cls) {
  return `<span class="badge badge-${cls}">${text}</span>`;
}

// ── Navigation ────────────────────────────────────────────────────────────

function switchSection(name) {
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.section === name);
  });
  document.querySelectorAll('.section').forEach(el => {
    el.classList.toggle('active', el.id === 'section-' + name);
  });
  state.activeSection = name;

  switch (name) {
    case 'overview':        pollSystem(); updateOverviewStats(); break;
    case 'modules':         loadModules(); break;
    case 'module-settings': loadModules().then(loadModuleConfig); break;
    case 'config':          loadGlobalConfig(); break;
    case 'network':         loadNetworkInfo(); break;
  }
}

// ── Preview toggle ────────────────────────────────────────────────────────

function togglePreview() {
  state.previewOpen = !state.previewOpen;

  document.getElementById('layout').classList.toggle('preview-open', state.previewOpen);
  document.getElementById('preview-btn').classList.toggle('active', state.previewOpen);

  const img = document.getElementById('preview-img');
  img.src = state.previewOpen ? '/preview/stream' : '';
}

// ── Top-bar controls ──────────────────────────────────────────────────────

async function togglePower() {
  const newState = !state.status.power;
  await apiPost('/api/power', { on: newState });
  await pollStatus();
}

function initBrightnessSlider() {
  const slider = document.getElementById('brightness-slider');
  const label  = document.getElementById('brightness-val');

  slider.addEventListener('mousedown',  () => { state.sliderDragging = true; });
  slider.addEventListener('touchstart', () => { state.sliderDragging = true; });
  slider.addEventListener('input', () => { label.textContent = slider.value; });

  const commit = async () => {
    state.sliderDragging = false;
    const val = parseInt(slider.value);
    label.textContent = val;
    await apiPost('/api/brightness', { brightness: val });
  };
  slider.addEventListener('mouseup',  commit);
  slider.addEventListener('touchend', commit);
}

// ── Helpers ───────────────────────────────────────────────────────────────

function makeBtn(text, onClick) {
  const btn = document.createElement('button');
  btn.className   = 'btn-save';
  btn.textContent = text;
  btn.addEventListener('click', onClick);
  return btn;
}

function flashSaved(btn) {
  btn.classList.add('saved');
  btn.textContent = 'SAVED';
  setTimeout(() => {
    btn.classList.remove('saved');
    btn.textContent = 'SAVE';
  }, 2000);
}

// ── Init ──────────────────────────────────────────────────────────────────

function init() {
  // Sidebar navigation
  document.querySelectorAll('.nav-item').forEach(el => {
    el.addEventListener('click', () => switchSection(el.dataset.section));
  });

  // Top-bar controls
  document.getElementById('power-btn').addEventListener('click', togglePower);
  document.getElementById('preview-btn').addEventListener('click', togglePreview);
  initBrightnessSlider();

  // Module-settings select
  document.getElementById('mod-cfg-select').addEventListener('change', loadModuleConfig);

  // Initial load
  buildDebugBar();
  pollStatus();
  pollSystem();
  loadModules();

  // Polling
  setInterval(pollStatus, 2000);
  setInterval(pollSystem, 12000);
}

document.addEventListener('DOMContentLoaded', init);
