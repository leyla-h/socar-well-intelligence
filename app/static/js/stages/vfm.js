// Stage 3 - VFM daily rates: field totals, one well in detail, the calculation behind any day, accuracy vs well tests.
const STREAMS = [
  { k: 'oil', label: 'Oil', unit: 'stb/d', tot: 'stb' },
  { k: 'water', label: 'Water', unit: 'stb/d', tot: 'stb' },
  { k: 'gas', label: 'Formation gas', unit: 'Mscf/d', tot: 'Mscf' },
];

export async function render(root, ctx) {
  const { S, api, charts } = ctx;
  const P = charts.palette(), fmt = charts.fmt;
  const [F, W] = await Promise.all([api.get('/api/vfm/field'), api.get(`/api/vfm/well?well=${encodeURIComponent(S.well)}`)]);
  const wc = F.totals.water / (F.totals.oil + F.totals.water) * 100;
  const perWellErr = {};
  for (const r of F.parity) { const e = perWellErr[r.well_name] = perWellErr[r.well_name] || []; e.push(Math.abs(r.oil_err_pct)); }

  root.innerHTML = `
  <div class="stage-head">
    <div><h1>Production rates</h1>
      <p>Daily oil, water and formation gas for every well, predicted by the trained flow meter from downhole pressure and temperature alone. No test separator needed.</p></div>
    <div class="tools"><span class="muted">Water trend</span>
      <div class="seg" id="wmode"><button data-v="team" aria-pressed="${F.water_mode === 'team'}">Exponential</button><button data-v="ensemble" aria-pressed="${F.water_mode === 'ensemble'}">Ensemble</button></div></div>
  </div>

  <section class="block">
    <div class="totals">
      ${STREAMS.map((s) => `<div class="total"><div class="tk"><i style="background:${P[s.k]}"></i>${s.label}, all wells</div>
        <div class="tv">${fmtBig(F.totals[s.k])}<span class="tu">${s.tot}</span></div></div>`).join('')}
      <div class="total"><div class="tk">Water cut, field</div><div class="tv">${wc.toFixed(1)}<span class="tu">%</span></div></div>
      ${F.test_mape ? `<div class="total"><div class="tk">Mean error vs ${F.parity.length} well tests</div><div class="tv">${F.test_mape.oil.toFixed(1)}<span class="tu">% oil</span></div></div>` : ''}
    </div>
    <div id="field" class="chart" style="height:380px"></div>
  </section>

  <section class="block">
    <div class="chart-cap"><h2>${S.well}</h2>
      <span class="legend-inline"><span><i style="background:${P.oil}"></i>predicted</span>${W.tests.length ? `<span><i class="dot" style="background:${P.ink}"></i>well test</span>` : ''}<span class="muted">Hover a day to see how it was calculated</span></span></div>
    <div id="well" class="chart" style="height:470px"></div>
    <div class="sheet" style="margin-top:14px">
      <div class="chart-cap"><h3 style="margin:0">How the rate is calculated</h3><span class="chain-day" id="chain-day"></span></div>
      <div id="chain"></div>
    </div>
    <div class="cols half" style="margin-top:22px">${W.findings.map((f) => `
      <div class="finding ${f.tone}" style="border:0;padding:4px 0"><span class="fi">${toneIcon(f.tone)}</span><div><h3>${f.title}</h3><p>${f.text}</p></div></div>`).join('')}</div>
  </section>

  ${F.parity.length ? `<section class="block">
    <h2>Predicted against measured</h2>
    <p class="lede">Each dot is one well test: the model's average over the test window against the separator measurement. The band marks ±5%.</p>
    <div id="parity" class="chart" style="height:340px"></div>
  </section>` : ''}

  <section class="block">
    <h2>All wells</h2>
    <div class="tbl-wrap"><table class="data"><thead><tr><th>Well</th><th>Oil, stb/d</th><th>Water, stb/d</th><th>Gas, Mscf/d</th><th>Water cut, start to end</th>
      <th>Reservoir pressure, psia</th><th>Pressure change, psi/month</th><th>Productivity, stb/d/psi</th>${F.parity.length ? '<th>Oil error vs tests</th>' : ''}</tr></thead>
    <tbody>${F.wells.map((r) => `<tr class="click ${r.well === S.well ? 'sel' : ''}" data-w="${r.well}"><td>${r.well}</td><td>${fmt(r.oil_avg)}</td><td>${fmt(r.water_avg)}</td><td>${fmt(r.gas_avg)}</td>
      <td>${r.wc_start.toFixed(1)}% to ${r.wc_end.toFixed(1)}%</td><td>${fmt(r.pr_last)}</td><td>${charts.fmtSigned(r.pr_slope_psi_per_day * 30, 0)}</td><td>${r.J.toFixed(2)}</td>
      ${F.parity.length ? `<td>${perWellErr[r.well] ? (perWellErr[r.well].reduce((a, b) => a + b, 0) / perWellErr[r.well].length).toFixed(1) + '%' : '–'}</td>` : ''}</tr>`).join('')}</tbody></table></div>
    <p class="fine">Averages over fully producing days. Reservoir pressure comes from the downhole temperature (Joule-Thomson heating), not from a build-up.</p>
  </section>`;

  root.querySelectorAll('tr[data-w]').forEach((tr) => tr.addEventListener('click', () => ctx.setWell(tr.dataset.w)));
  root.querySelectorAll('#wmode button').forEach((b) => b.addEventListener('click', async () => {
    await api.post('/api/settings', { water_mode: b.dataset.v }); api.clearCache('/api/vfm'); ctx.toast(b.dataset.v === 'team' ? 'Water: exponential trend (the submitted model)' : 'Water: ensemble of two trends'); ctx.rerender();
  }));

  // ---- small multiples helper: three stacked panels sharing x, one per stream
  const stacked = (el, x, ys, opts = {}) => {
    const n = 3, gap = 0.07, h = (1 - gap * 2) / 3;
    const lay = charts.layout({ height: opts.height, margin: { l: 66, r: 16, t: 24, b: 34 }, hovermode: 'x unified',
      xaxis: charts.axis({ type: 'date', anchor: 'y3', showspikes: true, spikemode: 'across', spikethickness: 1, spikecolor: P.muted, spikedash: 'solid' }) });
    const tr = [], ann = [];
    STREAMS.forEach((s, i) => {
      const yk = i ? `yaxis${i + 1}` : 'yaxis', ya = i ? `y${i + 1}` : 'y', top = 1 - i * (h + gap);
      lay[yk] = charts.axis({ domain: [top - h, top], title: s.unit, nticks: 4, rangemode: 'tozero' });
      ann.push({ text: `<b>${s.label}</b>`, xref: 'paper', yref: 'paper', x: 0, y: top + 0.01, xanchor: 'left', yanchor: 'bottom', showarrow: false, font: { size: 12, color: P.ink } });
      tr.push({ x, y: ys[s.k], yaxis: ya, type: 'scatter', mode: 'lines', line: { color: P[s.k], width: 1.6 }, name: s.label, hovertemplate: `%{y:,.0f} ${s.unit}<extra>${s.label}</extra>` });
      if (opts.tests) tr.push({ x: opts.tests.x, y: opts.tests[s.k], yaxis: ya, type: 'scatter', mode: 'markers', name: 'Well test',
        marker: { color: P.ink, size: 8, line: { color: P.surface, width: 2 } }, hovertemplate: `test %{y:,.0f} ${s.unit}<extra></extra>` });
    });
    lay.annotations = ann;
    return charts.draw(el, tr, lay);
  };

  await stacked(root.querySelector('#field'), F.dates, { oil: F.oil, water: F.water, gas: F.gas }, { height: 380 });
  const tests = W.tests.length ? {
    x: W.tests.map((t) => new Date((charts.ms(t.test_start) + charts.ms(t.test_end)) / 2).toISOString().slice(0, 19)),
    oil: W.tests.map((t) => t.oil_meas), water: W.tests.map((t) => t.water_meas), gas: W.tests.map((t) => t.gas_meas),
  } : null;
  const wel = root.querySelector('#well');
  await stacked(wel, W.dates, { oil: W.oil, water: W.water, gas: W.gas }, { height: 470, tests });

  // ---- calculation chain for one day
  const chainEl = root.querySelector('#chain'), dayEl = root.querySelector('#chain-day');
  let lastDay = null;
  async function explain(date) {
    if (date === lastDay) return; lastDay = date;
    const e = await api.get(`/api/vfm/explain?well=${encodeURIComponent(S.well)}&date=${date}`);
    dayEl.innerHTML = `<b>${new Date(date + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })}</b>, producing ${(e.producing * 100).toFixed(0)}% of the day`;
    if (!e.producing) { chainEl.innerHTML = '<p class="lede">The well was shut in all day, so every rate is zero.</p>'; return; }
    const off = e.offset ? ` + ${fmt(e.offset)} psi offset` : '';
    chainEl.innerHTML = `<div class="chain">
      ${link('Measured while flowing', fmt(e.T, 2), '°F downhole')}
      ${link(`minus reservoir ${fmt(e.T_res, 1)} °F`, fmt(e.dT, 3), '°F of heating')}
      ${link(`Pwf + heating ÷ η ${e.eta.toFixed(5)}`, fmt(e.Pr), 'psia reservoir pressure')}
      ${link(`minus Pwf ${fmt(e.pwf)} psia${off}`, fmt(e.D + e.offset), 'psi drawdown')}
      ${link('times productivity index', e.J.toFixed(3), 'stb/d per psi')}
      ${link(`times ${(e.producing * 100).toFixed(0)}% of the day on stream`, fmt(e.oil, 1), 'stb/d oil', true)}
    </div>
    <div class="subchain"><span>Water <b>${fmt(e.water, 1)} stb/d</b>${e.water_factor ? `: drawdown × ${e.water_factor.toFixed(3)} (water index rising ${e.water_mode === 'team' ? 'exponentially' : 'as an ensemble of two trends'} in time)` : ''}</span>
      <span>Gas <b>${fmt(e.gas, 1)} Mscf/d</b>: oil × ${fmt(e.GOR)} scf/stb solution GOR</span></div>`;
  }
  const full = W.dates.filter((d, i) => W.producing[i] > 0.99);
  await explain(full.length ? full[full.length - 1] : W.dates[W.dates.length - 1]);
  let ht;
  wel.on('plotly_hover', (ev) => {
    const x = ev.points && ev.points[0] && ev.points[0].x; if (!x) return;
    const d = String(x).slice(0, 10); clearTimeout(ht); ht = setTimeout(() => explain(d), 90);
  });

  // ---- parity
  const par = root.querySelector('#parity');
  if (par) {
    const tr = [], lay = charts.layout({ height: 340, margin: { l: 60, r: 16, t: 26, b: 46 }, hovermode: 'closest', annotations: [] });
    STREAMS.forEach((s, i) => {
      const xs = F.parity.map((r) => r[s.k + '_meas']), ys = F.parity.map((r) => r[s.k + '_pred']);
      const lo = Math.min(...xs, ...ys) * 0.9, hi = Math.max(...xs, ...ys) * 1.05;
      const xa = i ? `x${i + 1}` : 'x', ya = i ? `y${i + 1}` : 'y', dom = [i / 3 + (i ? 0.04 : 0), (i + 1) / 3 - (i < 2 ? 0.04 : 0)];
      lay[i ? `xaxis${i + 1}` : 'xaxis'] = charts.axis({ domain: dom, title: `measured, ${s.unit}`, anchor: ya, type: 'log', range: [Math.log10(lo), Math.log10(hi)], tickvals: charts.logTicks(lo, hi) });
      lay[i ? `yaxis${i + 1}` : 'yaxis'] = charts.axis({ title: i ? '' : 'predicted', anchor: xa, type: 'log', range: [Math.log10(lo), Math.log10(hi)], tickvals: charts.logTicks(lo, hi) });
      tr.push({ x: [lo, hi, hi, lo], y: [lo * 0.95, hi * 0.95, hi * 1.05, lo * 1.05], xaxis: xa, yaxis: ya, fill: 'toself', fillcolor: charts.rgba(P.muted, .14), line: { width: 0 }, hoverinfo: 'skip', type: 'scatter', mode: 'lines' });
      tr.push({ x: [lo, hi], y: [lo, hi], xaxis: xa, yaxis: ya, mode: 'lines', line: { color: P.muted, width: 1 }, hoverinfo: 'skip', type: 'scatter' });
      tr.push({ x: xs, y: ys, xaxis: xa, yaxis: ya, mode: 'markers', type: 'scatter', text: F.parity.map((r) => `${r.well_name}, ${String(r.test_start).slice(0, 10)}<br>error ${charts.fmtSigned(r[s.k + '_err_pct'], 1)}%`),
        marker: { color: F.parity.map((r) => r.well_name === S.well ? P.ink : P[s.k]), size: F.parity.map((r) => r.well_name === S.well ? 10 : 8), line: { color: P.surface, width: 1.5 } },
        hovertemplate: `%{text}<extra>${s.label}</extra>` });
      lay.annotations.push({ text: `<b>${s.label}</b>  ${F.test_mape[s.k].toFixed(1)}% mean error`, xref: 'paper', yref: 'paper', x: dom[0], y: 1.02, xanchor: 'left', yanchor: 'bottom', showarrow: false, font: { size: 12, color: P.ink } });
    });
    await charts.draw(par, tr, lay);
  }
  return () => root.querySelectorAll('.js-plotly-plot').forEach((p) => { try { Plotly.purge(p); } catch (e) {} });
}

function link(op, v, u, result = false) {
  return `<div class="link ${result ? 'result' : ''}"><div class="op">${op}</div><div class="lv num">${v}</div><div class="lu">${u}</div></div>`;
}
export function toneIcon(t) {
  if (t === 'good') return '<svg viewBox="0 0 12 12"><path d="M2.5 6.2l2.3 2.3 4.7-5"/></svg>';
  if (t === 'warn') return '<svg viewBox="0 0 12 12"><path d="M6 2.5v4.2M6 9.2v.1"/></svg>';
  return '<svg viewBox="0 0 12 12"><path d="M6 5.4v3.6M6 3v.1"/></svg>';
}
function fmtBig(x) {
  if (x >= 1e6) return (x / 1e6).toFixed(2) + ' M';
  if (x >= 1e4) return (x / 1e3).toFixed(0) + ' k';
  return x.toFixed(0);
}
