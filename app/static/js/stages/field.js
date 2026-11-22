// Stage 2 - field measurements: six aligned panels, min-max envelopes, zoom down to single minutes.
const PANELS = [
  { key: 'dh_pressure_psia', title: 'Downhole pressure', unit: 'psia', c: 'pdh' },
  { key: 'dh_temperature_degf', title: 'Downhole temperature', unit: '°F', c: 'tdh' },
  { key: 'whp_psia', title: 'Wellhead pressure', unit: 'psia', c: 'whp', extra: { key: 'whp_downstream_psia', c: 'whpd', title: 'downstream of choke' } },
  { key: 'annulus_pressure_psia', title: 'Annulus pressure', unit: 'psia', c: 'ann' },
  { key: 'gas_lift_rate_mscfd', title: 'Gas-lift injection', unit: 'Mscf/d', c: 'gl' },
  { key: 'choke_pct', title: 'Choke opening', unit: '%', c: 'ink', step: true },
];

export async function render(root, ctx) {
  const { S, api, charts } = ctx;
  const well = S.well;
  const P = charts.palette();
  S.fieldRaw = S.fieldRaw || false;
  const q = await api.get('/api/quality');
  root.innerHTML = `
  <div class="stage-head">
    <div><h1>Field measurements</h1>
      <p>${well}: every sensor on one time axis. The line is the average over each plotted interval and the band shows its range, so short events stay visible. Zoom in to reach single minutes.</p></div>
    <div class="tools">
      <label class="switch"><input type="checkbox" id="raw" ${S.fieldRaw ? 'checked' : ''}> Show raw readings</label>
      <button class="btn" id="reset">Whole period</button>
    </div>
  </div>
  <div class="toolbar" id="jumps"></div>
  <div class="chart-cap"><span class="legend-inline">
      <span><i class="band" style="background:${P.muted}"></i>range in interval</span>
      <span id="raw-leg" ${S.fieldRaw ? '' : 'hidden'}><i class="band" style="background:${P.gas}"></i>raw readings, before spike removal</span>
      <span><i class="band" style="background:${P.lineStrong};opacity:.8"></i>shut-in</span>
      <span><i style="background:${P.ink}"></i>well test</span></span>
    <span class="note" id="res-note"></span></div>
  <div id="fig" class="chart" style="height:820px"></div>

  <section class="block">
    <h2>Data quality</h2>
    <p class="lede">${fmtN(q.info.raw_rows)} rows read, ${fmtN(q.info.duplicates_removed)} exact duplicates dropped, ${q.info.days} days on a one-minute grid.
      Sentinel values (−999.25) and spikes are removed and the short gaps interpolated before any modelling.</p>
    <div class="tbl-wrap"><table class="data" id="qt"><thead><tr>
      <th>Well</th><th>Missing minutes</th><th>Sentinels, downhole P</th><th>Spikes, downhole P</th><th>Spikes, downhole T</th><th>Spikes, wellhead P</th><th>Spikes, annulus P</th><th>Spikes, gas lift</th>
    </tr></thead><tbody>${q.wells.map((r) => `<tr class="click ${r.well === well ? 'sel' : ''}" data-w="${r.well}"><td>${r.well}</td><td>${fmtN(r.missing)}</td>
      <td>${fmtN(r.sentinels.dh_pressure_psia)}</td><td>${fmtN(r.spikes.dh_pressure_psia)}</td><td>${fmtN(r.spikes.dh_temperature_degf)}</td>
      <td>${fmtN(r.spikes.whp_psia)}</td><td>${fmtN(r.spikes.annulus_pressure_psia)}</td><td>${fmtN(r.spikes.gas_lift_rate_mscfd)}</td></tr>`).join('')}</tbody></table></div>
    ${q.label_fixes.length ? `<h3 style="margin-top:22px">Well-test corrections</h3><p class="lede">${q.label_fixes.length} values in the well-test file were corrected before training:
      negative rates sign-flipped, and GL-06 gas converted from Sm³/d to Mscf/d.</p>` : ''}
  </section>`;
  root.querySelectorAll('#qt tr[data-w]').forEach((tr) => tr.addEventListener('click', () => ctx.setWell(tr.dataset.w)));

  const fig = root.querySelector('#fig');
  let range = S.fieldRange && S.fieldRange.well === well ? S.fieldRange.r : null;
  let busy = false, pending = null;

  async function load(r) {
    const qs = new URLSearchParams({ well, n: 1300, raw: S.fieldRaw ? 1 : 0 });
    if (r) { qs.set('t0', r[0]); qs.set('t1', r[1]); }
    return api.get(`/api/series?${qs}`);
  }

  function build(d, r) {
    const x = charts.timeAxis(d.start, d.step_min, d.n);
    const n = PANELS.length, gap = 0.035, h = (1 - gap * (n - 1)) / n;
    const traces = [], ann = [], shapes = [];
    const lay = charts.layout({ height: 820, margin: { l: 70, r: 18, t: 46, b: 36 }, hovermode: 'x unified',
      xaxis: charts.axis({ type: 'date', anchor: `y${n}`, range: r || undefined, autorange: !r, showspikes: true, spikemode: 'across', spikethickness: 1, spikecolor: P.muted, spikedash: 'solid' }) });
    PANELS.forEach((p, i) => {
      const ya = i ? `y${i + 1}` : 'y', yk = i ? `yaxis${i + 1}` : 'yaxis';
      const top = 1 - i * (h + gap), dom = [top - h, top];
      lay[yk] = charts.axis({ domain: dom, title: p.unit, nticks: 4, fixedrange: false });
      ann.push({ text: `<b>${p.title}</b>${p.extra ? `  <span style="color:${P.s[p.extra.c]}">━</span> ${p.extra.title}` : ''}`, xref: 'paper', yref: 'paper', x: 0, y: top + 0.004,
                 xanchor: 'left', yanchor: 'bottom', showarrow: false, font: { size: 12, color: P.ink } });
      const color = p.c === 'ink' ? P.ink2 : P.s[p.c];
      const ch = d.channels[p.key];
      if (!p.step) {
        if (S.fieldRaw && ch.raw_lo) {
          traces.push({ x, y: ch.raw_lo, yaxis: ya, mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false, type: 'scatter' });
          traces.push({ x, y: ch.raw_hi, yaxis: ya, mode: 'lines', line: { width: 0 }, fill: 'tonexty', fillcolor: charts.rgba(P.gas, .35), hoverinfo: 'skip', type: 'scatter' });
        }
        traces.push({ x, y: ch.lo, yaxis: ya, mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', type: 'scatter' });
        traces.push({ x, y: ch.hi, yaxis: ya, mode: 'lines', line: { width: 0 }, fill: 'tonexty', fillcolor: charts.rgba(color, .18), hoverinfo: 'skip', type: 'scatter' });
      }
      traces.push({ x, y: ch.mean, yaxis: ya, mode: 'lines', type: 'scatter', name: p.title, line: { color, width: 1.4, shape: p.step ? 'hv' : 'linear' },
                    hovertemplate: `%{y:,.1f} ${p.unit}<extra>${p.title}</extra>` });
      if (p.extra) {
        const e = d.channels[p.extra.key];
        traces.push({ x, y: e.mean, yaxis: ya, mode: 'lines', type: 'scatter', name: p.extra.title, line: { color: P.s[p.extra.c], width: 1.2 },
                      hovertemplate: `%{y:,.1f} psia<extra>Downstream</extra>` });
      }
    });
    for (const s of d.shutins) shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: s.start, x1: s.end, y0: 0, y1: 1, fillcolor: charts.rgba(P.lineStrong, .45), line: { width: 0 }, layer: 'below' });
    for (const t of d.tests) shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: t.start, x1: t.end, y0: 1.034, y1: 1.05, fillcolor: P.ink, line: { width: 0 } });
    lay.annotations = ann; lay.shapes = shapes;
    return { traces, lay };
  }

  async function refresh(r) {
    if (busy) { pending = r; return; }
    busy = true;
    try {
      const d = await load(r);
      const { traces, lay } = build(d, r);
      await charts.draw(fig, traces, lay);
      const step = d.step_min;
      root.querySelector('#res-note').textContent = step <= 1 ? 'Showing every minute' : `Each point covers ${step >= 60 ? (step / 60).toFixed(step % 60 ? 1 : 0) + ' h' : step + ' min'}`;
      if (!root.querySelector('#jumps').childElementCount) jumps(d);
    } finally {
      busy = false;
      if (pending !== null) { const p = pending; pending = null; refresh(p); }
    }
  }

  function jumps(d) {
    const box = root.querySelector('#jumps');
    if (!d.shutins.length && !d.tests.length) return;
    const add = (label, a, b) => {
      const btn = document.createElement('button'); btn.className = 'btn ghost'; btn.textContent = label;
      btn.addEventListener('click', () => { range = [a, b]; S.fieldRange = { well, r: range }; refresh(range); });
      box.appendChild(btn);
    };
    const pad = (iso, h) => new Date(charts.ms(iso) + h * 3600e3).toISOString().slice(0, 19).replace('T', ' ');
    const lab = document.createElement('span'); lab.className = 'muted'; lab.textContent = 'Jump to'; box.appendChild(lab);
    d.shutins.forEach((s) => add(`Shut-in ${new Date(charts.ms(s.start)).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })}`, pad(s.start, -18), pad(s.end, 30)));
    if (d.tests.length) { const t = d.tests[d.tests.length - 1]; add('Last well test', pad(t.start, -12), pad(t.end, 12)); }
  }

  await refresh(range);
  let timer;
  fig.on('plotly_relayout', (ev) => {
    if (ev['xaxis.autorange']) { range = null; S.fieldRange = null; clearTimeout(timer); timer = setTimeout(() => refresh(null), 120); return; }
    if (ev['xaxis.range[0]'] || ev['xaxis.range']) {
      const r = ev['xaxis.range'] || [ev['xaxis.range[0]'], ev['xaxis.range[1]']];
      range = r; S.fieldRange = { well, r };
      clearTimeout(timer); timer = setTimeout(() => refresh(r), 250);
    }
  });
  root.querySelector('#reset').addEventListener('click', () => { range = null; S.fieldRange = null; refresh(null); });
  root.querySelector('#raw').addEventListener('change', (e) => { S.fieldRaw = e.target.checked; root.querySelector('#raw-leg').hidden = !S.fieldRaw; refresh(range); });
  return () => { try { Plotly.purge(fig); } catch (e) {} };
}

const fmtN = (x) => (x ?? 0).toLocaleString('en-US');
