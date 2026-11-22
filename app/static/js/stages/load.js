// Stage 1 - load raw files, check the trained model, run the analysis.
const ICON_CHECK = '<svg viewBox="0 0 12 12"><path d="M2.5 6.2l2.3 2.3 4.7-5"/></svg>';
const PIPE = [
  ['read', 'Read files'], ['clean', 'Clean sensors'], ['vfm', 'Flow rates'], ['pta', 'Build-up tests'], ['regression', 'Model cross-check'],
];

export async function render(root, ctx) {
  const { S, api, charts } = ctx;
  const st = await ctx.refreshState();
  const m = st.model;
  const byKind = {};
  for (const f of st.files) (byKind[f.kind] = byKind[f.kind] || []).push(f);
  const fmtSize = (b) => b > 1e6 ? `${(b / 1e6).toFixed(0)} MB` : `${Math.max(1, (b / 1e3)).toFixed(0)} KB`;
  const rows = [
    { kind: 'hf', label: 'Sensor data', note: 'Per-minute pressures, temperature, gas lift', need: 'Required' },
    { kind: 'choke', label: 'Choke events', note: 'Shut-ins and choke changes', need: 'Recommended - missing shut-ins are found from gas-lift data' },
    { kind: 'tests', label: 'Well tests', note: 'Measured oil, water, gas', need: m ? 'Optional - used to check the predictions and to retrain' : 'Required to train a model' },
    { kind: 'pvt', label: 'Reservoir and PVT', note: 'Net pay, porosity, viscosity, ct', need: m ? 'Optional - the model carries these' : 'Required' },
    { kind: 'completion', label: 'Well completion', note: 'Depths, cumulative oil', need: m ? 'Optional - the model carries these' : 'Required' },
  ];
  const job = S.job || st.job || {};
  const v = m && m.validation;

  root.innerHTML = `
  <div class="stage-head">
    <div>
      <h1>Load well data</h1>
      <p>Drop the raw files from the field. Quyu recognises each file from its columns, so names do not matter. Several sensor files are joined into one record.</p>
    </div>
  </div>
  <div class="cols two">
    <div>
      <label class="drop" id="drop" tabindex="0">
        <svg class="core" viewBox="0 0 74 74" aria-hidden="true">
          <rect x="22" y="6" width="30" height="62" rx="15"/><rect class="band2" x="23" y="30" width="28" height="12"/>
          <rect class="band" x="23" y="44" width="28" height="9"/>
          <path d="M37 22V2M30 9l7-7 7 7"/>
        </svg>
        <div><strong>Drop CSV or Excel files here</strong><span>or click to browse. A trained model (.pkl) can be dropped here too.</span></div>
        <input type="file" id="file" multiple accept=".csv,.xlsx,.xls,.pkl" hidden>
      </label>
      <div id="upl" class="fine"></div>
      <div class="datasets">
        ${rows.map((r) => {
          const fl = byKind[r.kind] || [];
          const fromModel = !fl.length && m && (r.kind === 'pvt' || r.kind === 'completion');
          return `<div class="ds ${fl.length ? 'ok' : ''} ${fromModel ? 'model' : ''}">
            <span class="st">${fl.length || fromModel ? ICON_CHECK : ''}</span>
            <span class="dl">${r.label}<small>${r.note}</small></span>
            <span class="df">${fl.length ? fl.map((f) => `<span class="fn">${f.name} <span class="muted">${fmtSize(f.size)}</span><button data-del="${f.id}" aria-label="Remove ${f.name}" title="Remove">×</button></span>`).join('') : `<span class="muted">${fromModel ? 'From the trained model' : r.need}</span>`}</span>
            <span class="meta">${fl.length ? r.need.split(' - ')[0] : ''}</span>
          </div>`;
        }).join('')}
      </div>
      ${st.data_folder.length && st.data_folder.some((f) => !st.files.find((x) => x.name === f)) ? `<div class="toolbar" style="margin-top:14px">
        <button class="btn" id="use-folder"><svg viewBox="0 0 16 16"><path d="M2 4.5h4l1.5 1.5H14v6.5H2z"/></svg>Use the ${st.data_folder.length} files in the data folder</button>
        ${st.files.length ? '<button class="btn ghost" id="clear">Clear all files</button>' : ''}
      </div>` : (st.files.length ? '<div class="toolbar" style="margin-top:14px"><button class="btn ghost" id="clear">Clear all files</button></div>' : '')}
    </div>

    <aside class="sheet model-card">
      ${m ? `
        <h2>Trained flow meter</h2>
        <div class="file">${m.source}, created ${m.created.slice(0, 10)}</div>
        <dl class="kv">
          <dt>Method</dt><dd style="font-weight:500">Joule-Thomson drawdown + inflow</dd>
          <dt>Trained on</dt><dd>${m.n_tests} well tests</dd>
          <dt>Training period</dt><dd>${m.train_start} to ${m.train_end}</dd>
          <dt>Wells</dt><dd>${m.wells.length}</dd>
        </dl>
        ${v && v.walk_forward_mape ? `
        <div class="acc">
          ${[['oil', 'Oil'], ['water', 'Water'], ['gas', 'Gas']].map(([k, l]) => `<div><div class="k"><i style="background:var(--${k})"></i>${l}</div>
            <div class="v num">${v.walk_forward_mape[k].toFixed(1)}%</div><div class="s">${v.loo_mape[k].toFixed(1)}% in-sample</div></div>`).join('')}
        </div>
        <p class="fine">Mean error against well tests from later months the model never saw (walk-forward validation, 4 cut-off dates).</p>` : ''}
        <div class="opts">
          <div class="row"><span>Water trend</span>
            <div class="seg" id="wmode"><button data-v="team" aria-pressed="${st.water_mode === 'team'}">Exponential</button><button data-v="ensemble" aria-pressed="${st.water_mode === 'ensemble'}">Ensemble</button></div></div>
          <label class="switch"><input type="checkbox" id="retrain" ${byKind.tests ? '' : 'disabled'}> Retrain on the uploaded well tests</label>
        </div>` : `
        <h2>No trained model</h2>
        <p class="lede">Put <b>vfm_model.pkl</b> in the models folder, or drop it here. Without one, Quyu trains a new model from well tests, PVT and completion files.</p>`}
    </aside>
  </div>

  <div class="run-bar">
    <button class="btn primary big" id="run" ${byKind.hf ? '' : 'disabled'}>
      <svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z" fill="currentColor" stroke="none"/></svg>Run analysis</button>
    <span class="hint" id="hint">${byKind.hf ? (ctx.done().has('pta') ? 'Results are ready. Running again replaces them.' : 'Cleans the sensors, predicts daily rates with the trained model and analyses every shut-in. About a minute for nine months of data.') : 'Add the sensor data file to start.'}</span>
    ${ctx.done().has('clean') ? '<button class="btn" id="next">Open field data</button>' : ''}
  </div>
  <div id="prog"></div>
  ${st.messages.length ? st.messages.map((x) => `<div class="notice">${x}</div>`).join('') : ''}`;

  // ---------------------------------------------------------------- events
  const drop = root.querySelector('#drop'), input = root.querySelector('#file'), upl = root.querySelector('#upl');
  const send = async (files) => {
    if (!files.length) return;
    upl.textContent = `Uploading ${files.length} file${files.length > 1 ? 's' : ''}…`;
    try {
      const r = await api.upload(files, (f) => (upl.textContent = `Uploading… ${Math.round(f * 100)}%`));
      const bad = r.files.filter((f) => f.error);
      if (bad.length) ctx.toast(`${bad[0].name}: ${bad[0].error}`, true);
      else ctx.toast(`${r.files.length} file${r.files.length > 1 ? 's' : ''} recognised: ${[...new Set(r.files.map((f) => f.label))].join(', ')}`);
      ctx.rerender();
    } catch (e) { upl.textContent = ''; ctx.toast(e.message, true); }
  };
  drop.addEventListener('click', (e) => { if (e.target !== input) { e.preventDefault(); input.click(); } });
  drop.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => send([...input.files]));
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => send([...e.dataTransfer.files]));
  root.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', async () => { await api.del(`/api/files/${b.dataset.del}`); ctx.rerender(); }));
  const uf = root.querySelector('#use-folder');
  if (uf) uf.addEventListener('click', async () => { const r = await api.post('/api/use-folder'); ctx.toast(r.files.length ? `Added ${r.files.length} files from the data folder` : 'Those files are already loaded'); ctx.rerender(); });
  const cl = root.querySelector('#clear');
  if (cl) cl.addEventListener('click', async () => { await api.post('/api/reset'); api.clearCache(); S.sparks = {}; ctx.rerender(); });
  root.querySelectorAll('#wmode button').forEach((b) => b.addEventListener('click', async () => {
    root.querySelectorAll('#wmode button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    if (ctx.done().has('vfm')) { await api.post('/api/settings', { water_mode: b.dataset.v }); api.clearCache('/api/vfm'); ctx.toast('Water rates updated. Oil, gas and build-up results are unchanged.'); }
    else S.waterMode = b.dataset.v;
  }));
  const nx = root.querySelector('#next'); if (nx) nx.addEventListener('click', () => ctx.go('field'));

  const prog = root.querySelector('#prog');
  const drawProg = (j) => {
    if (!j || (!j.running && !j.log?.length && !j.error)) { prog.innerHTML = ''; return; }
    const order = PIPE.map((p) => p[0]); const cur = order.indexOf(j.stage);
    prog.innerHTML = `<div class="pipeline">${PIPE.map(([id, label], i) => {
      const isDone = j.stage === 'done' || (cur > i && j.stage !== 'error');
      const now = i === cur && j.running;
      return `<div class="pstep ${isDone ? 'done' : ''}"><div class="pn">Step ${i + 1}</div><div class="pl">${label}</div>
        <div class="pm">${now ? j.message : ''}</div><div class="bar" style="width:${isDone ? 100 : now ? Math.round((j.fraction || 0) * 100) : 0}%"></div></div>`;
    }).join('')}</div>
    <ul class="log">${(j.log || []).map((l) => `<li><span>${l.t.toFixed(1)} s</span>${l.msg.startsWith('Error') ? `<b class="err">${l.msg}</b>` : l.msg}</li>`).join('')}</ul>`;
  };
  if (job.running || (job.stage && job.stage !== null)) { try { drawProg(await api.get('/api/job', { fresh: true })); } catch (e) {} }
  const off = ctx.onJob((j, finished) => { drawProg(j); if (finished) setTimeout(() => ctx.rerender(), 50); });

  const run = root.querySelector('#run');
  run.addEventListener('click', async () => {
    run.disabled = true;
    const wm = root.querySelector('#wmode button[aria-pressed="true"]');
    try {
      await api.post('/api/run', { retrain: !!root.querySelector('#retrain')?.checked, water_mode: wm ? wm.dataset.v : undefined });
      root.querySelector('#hint').textContent = 'Running. You can watch the well come on line on the left.';
      ctx.pollJob();
    } catch (e) { ctx.toast(e.message, true); run.disabled = false; }
  });
  return off;
}
