// Stage 4 - build-up tests: one shut-in at a time, four standard plots, adjustable radial-flow window.
export async function render(root, ctx) {
  const { S, api, charts } = ctx;
  const P = charts.palette(), fmt = charts.fmt;
  const { events } = await api.get('/api/pta/events', { fresh: true });
  const ok = events.filter((e) => e.status === 'ok');
  if (!events.length) {
    root.innerHTML = `<div class="stage-head"><div><h1>Build-up tests</h1></div></div>
      <div class="empty"><h2>No shut-ins in this data</h2><p>A build-up needs the well to be shut in. None was found in the choke file or in the gas-lift record for the loaded period.</p></div>`;
    return;
  }
  if (!S.event || !ok.find((e) => e.event_id === S.event)) S.event = (ok.find((e) => e.well_name === S.well) || ok[0] || {}).event_id;

  root.innerHTML = `
  <div class="stage-head">
    <div><h1>Build-up tests</h1>
      <p>${events.length} shut-in${events.length > 1 ? 's' : ''} found. Each is read as a single-phase oil build-up, using the flow meter's oil rate for the day before the well was closed.</p></div>
  </div>
  <div class="cols side">
    <div class="events" id="evs">${events.map((e) => evCard(e)).join('')}</div>
    <div id="ev"></div>
  </div>`;
  root.querySelectorAll('.ev[data-id]').forEach((b) => b.addEventListener('click', () => {
    S.event = b.dataset.id; const w = b.dataset.w;
    root.querySelectorAll('.ev').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    ctx.quietWell(w);
    show(S.event);
  }));

  function evCard(e) {
    const d = new Date(charts.ms(e.shut_in_start));
    const date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
    if (e.status !== 'ok') return `<div class="ev skip"><span class="ew">${e.well_name}</span><span class="ed">${date}, ${e.duration_h.toFixed(1)} h</span><span class="er">Skipped: ${e.reason}</span></div>`;
    return `<button class="ev" data-id="${e.event_id}" data-w="${e.well_name}" aria-pressed="${e.event_id === S.event}">
      <span class="ew">${e.well_name}</span><svg viewBox="0 0 64 30" preserveAspectRatio="none" aria-hidden="true"><path d="${charts.sparkPath(e.spark, 64, 30, 3)}"/></svg>
      <span class="ed">${date}, ${e.duration_h.toFixed(1)} h shut in${e.source && e.source !== 'choke file' ? ' <span class="src">found from gas lift</span>' : ''}</span>
      <span class="er">k <b>${fmt(e.k, 1)}</b> md   skin <b>${charts.fmtSigned(e.skin, 2)}</b>   ΔP<sub>skin</sub> <b>${fmt(e.dps, 0)}</b> psi</span></button>`;
  }

  const box = root.querySelector('#ev');
  let poll = null;

  async function show(eid, data) {
    const d = data || await api.get(`/api/pta/event/${eid}`, { fresh: true });
    if (eid !== S.event) return;
    const H = d.H, R = d.R;
    const rep = repVals(d);
    const date = new Date(charts.ms(d.start)).toLocaleString('en-GB', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
    box.innerHTML = `
      <div class="chart-cap" style="margin-bottom:10px"><h2>${d.well}, shut in ${date}</h2>
        <a class="btn ghost" href="/api/pta/plot/${eid}.png" download><svg viewBox="0 0 16 16"><path d="M8 2v8m-3.5-3.5L8 10l3.5-3.5M3 13h10"/></svg>Download plot</a></div>
      <div class="results">
        ${res('Horner slope', fmt(rep.m, 2), 'psi/cycle', `${rep.src} · straight line ${fmt(H.m, 2)}`)}
        ${res('Permeability', fmt(rep.k, 1), 'md', `kh ${fmt(rep.k * d.pv.h)} md·ft · straight line ${fmt(H.k, 1)}`)}
        ${res('Skin', charts.fmtSigned(rep.skin, 2), '', `straight line ${charts.fmtSigned(H.skin, 2)}`)}
        ${res('Skin pressure drop', fmt(rep.dps, 1), 'psi', `straight line ${fmt(H.dps, 1)} · p* ${fmt(H.p_star)} psia`)}
      </div>
      <div class="inputs-line">
        <span>Oil rate <b>${fmt(H.q, 1)} stb/d</b> (flow meter, ${d.qday})</span><span>Producing time <b>${fmt(H.tp)} h</b></span>
        <span>p<sub>wf</sub> at shut-in <b>${fmt(d.pwf, 1)} psia</b></span><span>p<sub>1h</sub> <b>${fmt(H.p1hr, 1)} psia</b></span>
        <span>Radius of investigation <b>${fmt(H.rinv)} ft</b></span>
      </div>
      <div class="plots4">
        <div><div class="plot-title">Pressure and rate history</div><div class="plot-sub">Downhole pressure, and the flow meter's daily oil rate below it</div><div id="p-hist" class="chart" style="height:330px"></div></div>
        <div><div class="plot-title">Horner plot</div><div class="plot-sub">Straight line through the radial-flow points gives m and p*</div><div id="p-horner" class="chart" style="height:330px"></div></div>
        <div><div class="plot-title">Log-log diagnostic</div><div class="plot-sub">Unit slope = wellbore storage; flat derivative = radial flow</div><div id="p-log" class="chart" style="height:330px"></div></div>
        <div><div class="plot-title">MDH plot</div><div class="plot-sub">Pressure against log shut-in time, slope ${fmt(H.mdh_slope, 2)} psi/cycle</div><div id="p-mdh" class="chart" style="height:330px"></div></div>
      </div>
      <div class="mtr">
        <div class="lab">Radial-flow window<br><b id="win">${fmt(H.t1, 2)} to ${fmt(H.t2, 2)} h</b><br><span class="muted" id="win-src">${d.manual ? 'set by you' : 'picked automatically'}</span></div>
        <div class="range2" id="rng"><div class="track"></div><div class="sel"></div><input type="range" min="0" max="1000" id="r1" aria-label="Window start"><input type="range" min="0" max="1000" id="r2" aria-label="Window end"><div class="ticks"></div></div>
        <button class="btn" id="auto" ${d.manual ? '' : 'disabled'}>Back to automatic</button>
      </div>
      <div class="inset" style="margin-top:16px" id="reg">${regText(d)}</div>`;
    drawPlots(d);
    wireRange(d);
    box.querySelector('#auto').addEventListener('click', async () => apply(await api.post(`/api/pta/event/${eid}/window`, { reset: true })));
    clearInterval(poll);
    if (!R) poll = setInterval(async () => {
      const x = await api.get(`/api/pta/event/${eid}`, { fresh: true });
      if (x.R && eid === S.event) { clearInterval(poll); show(eid, x); }
    }, 2500);
  }

  function apply(d) {
    api.clearCache('/api/pta'); api.clearCache('/api/reservoir'); api.clearCache('/api/export');
    show(d.event_id, d);
    const card = root.querySelector(`.ev[data-id="${d.event_id}"] .er`);
    const rep = repVals(d);
    if (card) card.innerHTML = `k <b>${fmt(rep.k, 1)}</b> md   skin <b>${charts.fmtSigned(rep.skin, 2)}</b>   ΔP<sub>skin</sub> <b>${fmt(rep.dps, 0)}</b> psi`;
  }

  // Reported values = full model regression (what the Phase 2 files contain); Horner straight line is the check.
  function repVals(d) {
    const R = d.R;
    if (R && !R.error && R.k != null) return { m: R.m, k: R.k, skin: R.skin, dps: R.dps, src: 'model regression' };
    return { m: d.H.m, k: d.H.k, skin: d.H.skin, dps: d.H.dps, src: 'straight line (regression running)' };
  }

  function regText(d) {
    const R = d.R;
    if (!R) return '<b>Model cross-check running.</b> <span class="muted">A full model (radial flow, wellbore storage, skin, boundary) is being fitted to every build-up point.</span>';
    if (R.error) return `Model cross-check failed: ${R.error}`;
    const dk = (d.H.k / R.k - 1) * 100;
    const b = R.boundary === 'inf' ? 'no boundary seen' : R.boundary === 'closed' ? `no-flow boundary at ${fmt(R.re)} ft` : `constant-pressure boundary at ${fmt(R.re)} ft`;
    return `<b>Reported values: model regression</b> <span class="muted">(purple curves)</span>, fitted to every build-up point: k <b>${fmt(R.k, 1)} md</b>, skin <b>${charts.fmtSigned(R.skin, 2)}</b>, ${b},
      wellbore storage ${R.C.toFixed(4)} bbl/psi, fit error ${R.rms.toFixed(3)} psi RMS. The Horner straight line through the window below is the check
      (k ${charts.fmtSigned(dk, 0)}% from the regression); dragging the window changes only the check, not the exported results.`;
  }

  function wireRange(d) {
    const lo = Math.log10(Math.max(d.tb[0], 1e-3)), hi = Math.log10(d.tb[d.tb.length - 1]);
    const toV = (t) => Math.round((Math.log10(t) - lo) / (hi - lo) * 1000), toT = (v) => Math.pow(10, lo + (v / 1000) * (hi - lo));
    const r1 = box.querySelector('#r1'), r2 = box.querySelector('#r2'), sel = box.querySelector('#rng .sel'), win = box.querySelector('#win');
    r1.value = toV(d.H.t1); r2.value = toV(d.H.t2);
    const ticks = box.querySelector('#rng .ticks');
    for (let e = Math.ceil(lo); e <= Math.floor(hi); e++) ticks.insertAdjacentHTML('beforeend', `<span style="left:${(e - lo) / (hi - lo) * 100}%">${e < 0 ? Math.pow(10, e) : fmt(Math.pow(10, e))} h</span>`);
    const paint = () => {
      const a = Math.min(+r1.value, +r2.value), b = Math.max(+r1.value, +r2.value);
      sel.style.left = a / 10 + '%'; sel.style.width = (b - a) / 10 + '%';
      win.textContent = `${fmt(toT(a), 2)} to ${fmt(toT(b), 2)} h`;
    };
    paint();
    let t;
    const commit = () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const a = toT(Math.min(+r1.value, +r2.value)), b = toT(Math.max(+r1.value, +r2.value));
        try { apply(await api.post(`/api/pta/event/${d.event_id}/window`, { t1: a, t2: b })); }
        catch (e) { ctx.toast(e.message, true); }
      }, 120);
    };
    [r1, r2].forEach((r) => { r.addEventListener('input', paint); r.addEventListener('change', commit); });
  }

  function drawPlots(d) {
    const H = d.H, inW = d.dt.map((t) => t >= H.t1 && t <= H.t2);
    const tp = H.tp, HT = d.dt.map((t) => (tp + t) / t);
    const pick = (arr, m) => arr.filter((_, i) => m[i]);
    const base = (extra) => charts.layout({ margin: { l: 62, r: 14, t: 8, b: 44 }, hovermode: 'closest', ...extra });
    const showLegend = { showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom', font: { size: 11, color: P.ink2 } } };
    // history: two stacked panels (no dual axis)
    const hx = charts.timeAxis(d.history.start, d.history.step_min, d.history.p.length);
    charts.draw(box.querySelector('#p-hist'), [
      { x: hx, y: d.history.p, type: 'scatter', mode: 'lines', line: { color: P.water, width: 1.3 }, hovertemplate: '%{y:,.1f} psia<extra>Downhole pressure</extra>' },
      { x: d.history.dates.map((x) => x + 'T12:00:00'), y: d.history.oil, xaxis: 'x', yaxis: 'y2', type: 'scatter', mode: 'lines', line: { color: P.oil, width: 1.8, shape: 'hvh' }, hovertemplate: '%{y:,.0f} stb/d<extra>Oil, flow meter</extra>' },
    ], base({ xaxis: charts.axis({ type: 'date', anchor: 'y2' }), yaxis: charts.axis({ domain: [0.42, 1], title: 'psia', nticks: 5 }),
      yaxis2: charts.axis({ domain: [0, 0.3], title: 'stb/d', nticks: 3, rangemode: 'tozero' }),
      shapes: [{ type: 'rect', xref: 'x', yref: 'paper', x0: d.start, x1: d.end, y0: 0, y1: 1, fillcolor: charts.rgba(P.lineStrong, .45), line: { width: 0 }, layer: 'below' }] }));
    // Horner
    const hmax = Math.max(...HT), xx = [1, hmax];
    const hor = [
      { x: HT, y: d.p, type: 'scattergl', mode: 'markers', marker: { color: P.muted, size: 3 }, name: 'build-up data', hovertemplate: 'Horner time %{x:,.0f}<br>%{y:,.1f} psia<extra></extra>' },
      { x: pick(HT, inW), y: pick(d.p, inW), type: 'scattergl', mode: 'markers', marker: { color: P.accent, size: 4 }, name: 'radial flow', hoverinfo: 'skip' },
      { x: xx, y: xx.map((h) => H.p_star - H.m * Math.log10(h)), type: 'scatter', mode: 'lines', line: { color: P.ink, width: 1.2, dash: 'dash' }, name: `m ${H.m.toFixed(2)} psi/cycle`, hoverinfo: 'skip' },
      { x: [1], y: [H.p_star], type: 'scatter', mode: 'markers+text', marker: { color: P.ink, size: 8 }, text: [`p* ${fmt(H.p_star)}`], textposition: 'bottom left', textfont: { size: 11, color: P.ink2 }, hoverinfo: 'skip', showlegend: false },
    ];
    if (d.model) hor.push({ x: d.model.dt.map((t) => (tp + t) / t), y: d.model.p, type: 'scatter', mode: 'lines', line: { color: P.model, width: 1.4 }, name: 'model', hoverinfo: 'skip' });
    charts.draw(box.querySelector('#p-horner'), hor, base({ ...showLegend, xaxis: charts.axis({ type: 'log', autorange: 'reversed', title: 'Horner time (tp + Δt) / Δt', exponentformat: 'power' }),
      yaxis: charts.axis({ title: 'psia' }) }));
    // log-log with derivative
    const ok = d.der.map((v) => v !== null && v > 0);
    const dmin = Math.min(...d.dp_b.filter((v) => v > 0), ...d.der.filter((v) => v > 0)) * 0.7, dmax = Math.max(...d.dp_b) * 1.4;
    const lg = [
      { x: [H.t1, H.t2, H.t2, H.t1], y: [dmin, dmin, dmax, dmax], type: 'scatter', fill: 'toself', fillcolor: charts.rgba(P.accent, .14), line: { width: 0 }, mode: 'lines', name: 'radial flow window', hoverinfo: 'skip' },
      { x: [d.tb[0], d.tb[d.tb.length - 1]], y: [H.m / 2.303, H.m / 2.303], type: 'scatter', mode: 'lines', line: { color: P.ink, width: 1, dash: 'dash' }, name: 'm / 2.303', hoverinfo: 'skip' },
      { x: d.tb, y: d.dp_b, type: 'scatter', mode: 'markers', marker: { color: P.water, size: 6 }, name: 'Δp', hovertemplate: 'Δt %{x:.3f} h<br>Δp %{y:,.1f} psi<extra></extra>' },
      { x: pick(d.tb, ok), y: pick(d.der, ok), type: 'scatter', mode: 'markers', marker: { color: P.der, size: 6, symbol: 'square' }, name: "derivative Δp'", hovertemplate: 'Δt %{x:.3f} h<br>Δp′ %{y:,.1f} psi<extra></extra>' },
    ];
    if (d.model) {
      const mt = d.model.dt, mp = d.model.p, lx = mt.map((t) => Math.log(tp * t / (tp + t)));
      const md = mp.map((_, i) => (i === 0 || i === mp.length - 1) ? null : (mp[i + 1] - mp[i - 1]) / (lx[i + 1] - lx[i - 1]));
      lg.push({ x: mt, y: mp.map((v) => v - d.pwf), type: 'scatter', mode: 'lines', line: { color: P.model, width: 1.3 }, name: 'model', hoverinfo: 'skip' });
      lg.push({ x: mt, y: md, type: 'scatter', mode: 'lines', line: { color: P.model, width: 1.3, dash: 'dot' }, hoverinfo: 'skip', showlegend: false });
    }
    charts.draw(box.querySelector('#p-log'), lg, base({ ...showLegend, xaxis: charts.axis({ type: 'log', title: 'Δt, hours', exponentformat: 'power' }),
      yaxis: charts.axis({ type: 'log', title: 'psi', range: [Math.log10(dmin), Math.log10(dmax)], exponentformat: 'power' }) }));
    // MDH
    const mdh = [
      { x: d.dt, y: d.p, type: 'scattergl', mode: 'markers', marker: { color: P.muted, size: 3 }, name: 'build-up data', hovertemplate: 'Δt %{x:.3f} h<br>%{y:,.1f} psia<extra></extra>' },
      { x: pick(d.dt, inW), y: pick(d.p, inW), type: 'scattergl', mode: 'markers', marker: { color: P.accent, size: 4 }, name: 'radial flow', hoverinfo: 'skip' },
      { x: [d.dt[0], d.dt[d.dt.length - 1]], y: [H.p1hr, H.p1hr], type: 'scatter', mode: 'lines', line: { color: P.der, width: 1, dash: 'dot' }, name: `p1h ${fmt(H.p1hr, 1)}`, hoverinfo: 'skip' },
      { x: [d.dt[0], d.dt[d.dt.length - 1]], y: [d.pwf, d.pwf], type: 'scatter', mode: 'lines', line: { color: P.water, width: 1, dash: 'dot' }, name: `pwf ${fmt(d.pwf, 1)}`, hoverinfo: 'skip' },
    ];
    if (d.model) mdh.push({ x: d.model.dt, y: d.model.p, type: 'scatter', mode: 'lines', line: { color: P.model, width: 1.3 }, name: 'model', hoverinfo: 'skip' });
    charts.draw(box.querySelector('#p-mdh'), mdh, base({ ...showLegend, xaxis: charts.axis({ type: 'log', title: 'Δt, hours', exponentformat: 'power' }), yaxis: charts.axis({ title: 'psia' }) }));
  }

  if (S.event) await show(S.event);
  return () => { clearInterval(poll); root.querySelectorAll('.js-plotly-plot').forEach((p) => { try { Plotly.purge(p); } catch (e) {} }); };
}

function res(k, v, u, s) {
  return `<div class="res"><div class="rk">${k}</div><div class="rv">${v}<span class="ru">${u}</span></div><div class="rs">${s}</div></div>`;
}
