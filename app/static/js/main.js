import * as api from './api.js';
import * as charts from './charts.js';
import { Spine, STAGES } from './spine.js';

const loaders = {
  load: () => import('./stages/load.js'),
  field: () => import('./stages/field.js'),
  vfm: () => import('./stages/vfm.js'),
  pta: () => import('./stages/pta.js'),
  reservoir: () => import('./stages/reservoir.js'),
  export: () => import('./stages/export.js'),
};

const S = { state: null, stage: 'load', well: null, event: null, job: null, jobListeners: new Set(), sparks: {}, cleanup: null, renderId: 0 };
const $ = (sel) => document.querySelector(sel);
const stageEl = $('#stage');
const spine = new Spine($('#spine'), (id) => go(id));

// ------------------------------------------------------------------ helpers shared with stages
let toastTimer;
function toast(msg, bad = false) {
  const t = $('#toast'); t.textContent = msg; t.className = 'toast on' + (bad ? ' bad' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = 'toast'), bad ? 6000 : 3200);
}

const done = () => new Set(S.state ? S.state.done : []);
function unlocked() {
  const d = done(), u = new Set(['load']);
  if (d.has('clean')) u.add('field');
  if (d.has('vfm')) u.add('vfm');
  if (d.has('pta')) { u.add('pta'); u.add('reservoir'); u.add('export'); }
  return u;
}

const LEVEL = { read: [0, 0.08], clean: [0.08, 0.3], vfm: [0.3, 0.6], pta: [0.6, 0.8], regression: [0.8, 1], done: [1, 1] };
function staticLevel() {
  const d = done();
  return d.has('regression') ? 1 : d.has('pta') ? 0.8 : d.has('vfm') ? 0.6 : d.has('clean') ? 0.3 : 0;
}

function completionFor(well) {
  const m = S.state && S.state.model;
  return (m && m.completion && m.completion[well]) || null;
}

function spineSubs() {
  const st = S.state || {}, info = st.info || {}, d = done();
  const nFiles = (st.files || []).length;
  return {
    load: nFiles ? `${nFiles} file${nFiles > 1 ? 's' : ''} loaded` : 'Drop raw well files',
    field: d.has('clean') ? `${st.wells.length} wells, ${info.days} days` : 'Sensors, choke, gaps',
    vfm: d.has('vfm') ? 'Daily oil, water, gas' : 'Virtual flow meter',
    pta: d.has('pta') ? 'Horner, log-log, MDH' : 'Shut-in analysis',
    reservoir: d.has('pta') ? 'k, skin, boundaries' : 'Interpretation',
    export: d.has('pta') ? 'Excel, CSV, PDF, plots' : 'Results and reports',
  };
}

function syncSpine() {
  const d = done(), dn = new Set();
  if (d.has('clean')) { dn.add('load'); dn.add('field'); }
  if (d.has('vfm')) dn.add('vfm');
  if (d.has('pta')) dn.add('pta');
  if (d.has('regression')) dn.add('reservoir');
  const j = S.job;
  const comp = { ...(completionFor(S.well) || {}), ...(S.pvtCache[S.well] || {}) };
  spine.set({ well: S.well, comp, active: S.stage, unlocked: unlocked(), done: dn,
              busy: j && j.running ? ({ read: 'load', clean: 'field', vfm: 'vfm', pta: 'pta', regression: 'reservoir' }[j.stage] || null) : null,
              subs: spineSubs() });
  if (!(j && j.running)) spine.setLevel(staticLevel());
}

// ------------------------------------------------------------------ header
function drawHeader() {
  const st = S.state; const m = st && st.model;
  $('#model-pill').innerHTML = m ? `Model <b>${m.source || 'vfm_model.pkl'}</b>` : 'No model loaded';
  const wells = (st && st.wells && st.wells.length ? st.wells : (m ? m.wells : []));
  const strip = $('#wellstrip'); strip.innerHTML = '';
  for (const w of wells) {
    const b = document.createElement('button');
    b.className = 'well-chip' + (m && !m.wells.includes(w) ? ' off' : '') + (S.sparks[w] ? '' : ' nospark');
    b.setAttribute('aria-pressed', String(w === S.well));
    const sp = S.sparks[w];
    b.innerHTML = `<span class="wn">${w}</span><svg viewBox="0 0 60 16" preserveAspectRatio="none" aria-hidden="true">${sp ? `<path d="${charts.sparkPath(sp)}"/>` : ''}</svg>`;
    b.title = sp ? `${w}: predicted daily oil rate` : w;
    b.addEventListener('click', () => setWell(w));
    strip.appendChild(b);
  }
}

async function refreshState() {
  S.state = await api.get('/api/state', { fresh: true });
  const wells = S.state.wells.length ? S.state.wells : (S.state.model ? S.state.model.wells : []);
  if (!S.well || !wells.includes(S.well)) S.well = wells[0] || null;
  if (done().has('vfm') && !Object.keys(S.sparks).length) {
    try { const f = await api.get('/api/vfm/field'); for (const w of f.wells) S.sparks[w] = w.spark; } catch (e) {}
  }
  drawHeader(); syncSpine();
  return S.state;
}
S.pvtCache = {};

// ------------------------------------------------------------------ routing
async function go(id, { push = true } = {}) {
  if (!unlocked().has(id)) id = 'load';
  S.stage = id;
  if (push) history.replaceState(null, '', `#${id}`);
  syncSpine();
  await renderStage();
}

async function renderStage() {
  const id = S.stage, rid = ++S.renderId;
  if (S.cleanup) { try { S.cleanup(); } catch (e) {} S.cleanup = null; }
  const mod = await loaders[id]();
  if (rid !== S.renderId) return;
  stageEl.classList.add('loading');
  try {
    const c = await mod.render(stageEl, ctx);
    if (rid === S.renderId) S.cleanup = typeof c === 'function' ? c : null;
  } catch (e) {
    console.error(e);
    stageEl.innerHTML = `<div class="empty"><h2>This view could not load</h2><p>${e.message}</p><button class="btn" onclick="location.reload()">Reload</button></div>`;
  } finally {
    stageEl.classList.remove('loading');
  }
  $('#main').scrollTop = 0;
}

function setWell(w) {
  if (w === S.well) return;
  S.well = w; S.event = null; drawHeader(); syncSpine();
  renderStage();
}

// ------------------------------------------------------------------ analysis job
let polling = null;
function pollJob() {
  if (polling) return;
  polling = setInterval(async () => {
    try {
      const j = await api.get('/api/job', { fresh: true });
      S.job = j;
      const [a, b] = LEVEL[j.stage] || [0, 0];
      spine.setLevel(a + (b - a) * (j.fraction || 0));
      S.jobListeners.forEach((f) => f(j));
      if (!j.running) {
        clearInterval(polling); polling = null;
        api.clearCache(); S.sparks = {};
        await refreshState();
        S.jobListeners.forEach((f) => f(j, true));
        if (j.error) toast(j.error, true); else toast('Analysis complete. Field data, flow rates and build-up tests are ready.');
      } else if (['vfm', 'pta', 'regression'].includes(j.stage) && !done().has('clean')) {
        await refreshState();
      } else {
        syncSpine();
      }
    } catch (e) { /* server restarting - keep polling */ }
  }, 600);
}

const ctx = {
  S, api, charts, go, setWell, toast, refreshState, pollJob,
  rerender: () => renderStage(),
  quietWell(w) { if (w && w !== S.well) { S.well = w; drawHeader(); syncSpine(); } },
  onJob(cb) { S.jobListeners.add(cb); return () => S.jobListeners.delete(cb); },
  done, unlocked,
};

// ------------------------------------------------------------------ theme, keys, boot
$('#theme-btn').addEventListener('click', toggleTheme);
function toggleTheme() {
  const t = document.documentElement.dataset.theme === 'night' ? 'day' : 'night';
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('quyu-theme', t); } catch (e) {}
  spine.draw(); renderStage();
}

document.addEventListener('keydown', (e) => {
  if (e.target.closest('input, select, textarea') || e.metaKey || e.ctrlKey || e.altKey) return;
  const i = '123456'.indexOf(e.key);
  if (i >= 0 && unlocked().has(STAGES[i].id)) { go(STAGES[i].id); return; }
  if (e.key === 't') toggleTheme();
  if (e.key === '[' || e.key === ']') {
    const ws = S.state && (S.state.wells.length ? S.state.wells : S.state.model ? S.state.model.wells : []);
    if (!ws || !ws.length) return;
    const k = ws.indexOf(S.well); setWell(ws[(k + (e.key === ']' ? 1 : ws.length - 1)) % ws.length]);
  }
});

window.addEventListener('hashchange', () => { const h = location.hash.replace('#', ''); if (loaders[h] && h !== S.stage) go(h, { push: false }); });

(async function boot() {
  try {
    await refreshState();
    try { S.pvtCache = await api.get('/api/model/pvt'); syncSpine(); } catch (e) {}   // datum depth + net pay for the drawing
  } catch (e) {
    stageEl.innerHTML = `<div class="empty"><h2>Cannot reach the Quyu server</h2><p>Start it with <b>python run.py</b> and reload this page.</p></div>`;
    return;
  }
  const h = location.hash.replace('#', '');
  if (S.state.job && S.state.job.running) pollJob();
  go(loaders[h] ? h : 'load', { push: false });
})();
