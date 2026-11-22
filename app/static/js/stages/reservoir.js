// Stage 5 - reservoir interpretation: plain-language findings per shut-in, and the wells side by side.
import { toneIcon } from './vfm.js';

export async function render(root, ctx) {
  const { S, api, charts } = ctx;
  const P = charts.palette(), fmt = charts.fmt;
  const Rv = await api.get('/api/reservoir', { fresh: true });
  const evs = Rv.events;
  if (!evs.length) {
    root.innerHTML = `<div class="stage-head"><div><h1>Reservoir interpretation</h1></div></div><div class="empty"><h2>Nothing to interpret yet</h2><p>Interpretation needs at least one analysed shut-in.</p></div>`;
    return;
  }
  if (!S.event || !evs.find((e) => e.event_id === S.event)) S.event = (evs.find((e) => e.well_name === S.well) || evs[0]).event_id;
  const dateOf = (iso) => new Date(charts.ms(iso)).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

  root.innerHTML = `
  <div class="stage-head">
    <div><h1>Reservoir interpretation</h1>
      <p>What each build-up says about the formation around the well, checked against the flow meter, which was calibrated separately on well tests.</p></div>
  </div>
  <div class="toolbar"><div class="seg" id="evsel">${evs.map((e) => `<button data-id="${e.event_id}" data-w="${e.well_name}" aria-pressed="${e.event_id === S.event}">${e.well_name}, ${dateOf(e.shut_in_start)}</button>`).join('')}</div></div>
  <div class="cols two">
    <div><h2 id="f-title"></h2><div class="findings" id="findings"></div></div>
    <aside class="sheet"><h2>Well behaviour</h2><p class="fine" style="margin:0 0 6px">From the flow meter over the whole loaded period.</p><div class="findings" id="wfind"></div></aside>
  </div>

  <section class="block">
    <div class="cols half">
      <div><h2>Permeability and skin</h2><p class="lede">Above the line the near-wellbore zone is damaged; below it, stimulated.</p><div id="ks" class="chart" style="height:340px"></div></div>
      <div><h2>Two measures of productivity</h2><p class="lede">The flow meter's productivity index next to the one implied by the build-up's k and skin over the drainage area.</p><div id="jj" class="chart" style="height:340px"></div></div>
    </div>
  </section>

  <section class="block">
    <h2>Reservoir pressure, all wells</h2>
    <p class="lede">Estimated every day from the downhole temperature. <b id="pr-well"></b> is highlighted; the other wells are shown in grey.</p>
    <div id="pr" class="chart" style="height:360px"></div>
  </section>

  <section class="block">
    <h2>All shut-ins</h2>
    <div class="tbl-wrap"><table class="data"><thead><tr><th>Shut-in</th><th>Duration, h</th><th>Horner slope, psi/cycle</th><th>k, md</th><th>Skin</th><th>ΔP skin, psi</th><th>Flow efficiency</th>
      <th>kh, md·ft</th><th>J flow meter</th><th>J from k and skin</th><th>Model check k, md</th><th>Model check skin</th><th>Boundary</th></tr></thead>
    <tbody>${evs.map((e) => `<tr class="click ${e.event_id === S.event ? 'sel' : ''}" data-id="${e.event_id}" data-w="${e.well_name}"><td>${e.well_name}, ${dateOf(e.shut_in_start)}</td>
      <td>${fmt(e.duration_h, 1)}</td><td>${fmt(e.horner_plot_slope, 2)}</td><td>${fmt(e.permeability_md, 1)}</td><td>${charts.fmtSigned(e.skin, 2)}</td><td>${fmt(e.delta_p_skin_psi, 1)}</td>
      <td>${fmt(e.flow_efficiency, 2)}</td><td>${fmt(e.kh)}</td><td>${fmt(e.J_vfm, 2)}</td><td>${fmt(e.J_pss, 2)}</td><td>${fmt(e.reg_k_md, 1)}</td><td>${e.reg_skin === null ? '–' : charts.fmtSigned(e.reg_skin, 2)}</td>
      <td>${e.reg_boundary ? ({ inf: 'none seen', closed: 'no-flow', const: 'constant pressure' })[e.reg_boundary] : '–'}</td></tr>`).join('')}</tbody></table></div>
  </section>`;

  const pick = async (eid, w) => {
    S.event = eid; ctx.quietWell(w);
    root.querySelectorAll('#evsel button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.id === eid)));
    root.querySelectorAll('tr[data-id]').forEach((r) => r.classList.toggle('sel', r.dataset.id === eid));
    await Promise.all([showFindings(eid), drawCross(), drawPr()]);
  };
  root.querySelectorAll('#evsel button, tr[data-id]').forEach((b) => b.addEventListener('click', () => pick(b.dataset.id, b.dataset.w)));

  async function showFindings(eid) {
    const e = evs.find((x) => x.event_id === eid);
    const [d, W] = await Promise.all([api.get(`/api/pta/event/${eid}`), api.get(`/api/vfm/well?well=${encodeURIComponent(e.well_name)}`)]);
    root.querySelector('#f-title').textContent = `${e.well_name}, build-up of ${dateOf(e.shut_in_start)}`;
    root.querySelector('#findings').innerHTML = d.findings.map(fHtml).join('');
    root.querySelector('#wfind').innerHTML = W.findings.map(fHtml).join('');
  }
  const fHtml = (f) => `<div class="finding ${f.tone}"><span class="fi">${toneIcon(f.tone)}</span><div><h3>${f.title}</h3><p>${f.text}</p></div></div>`;

  async function drawCross() {
    const sel = evs.map((e) => e.event_id === S.event);
    const lab = evs.map((e) => `${e.well_name}`);
    const xs = evs.map((e) => e.permeability_md), kmin = Math.min(...xs) * 0.6, kmax = Math.max(...xs) * 1.6;
    const smin = Math.min(-1, ...evs.map((e) => e.skin)) - 1, smax = Math.max(1, ...evs.map((e) => e.skin)) + 1;
    await charts.draw(root.querySelector('#ks'), [
      { x: [kmin, kmax], y: [0, 0], type: 'scatter', mode: 'lines', line: { color: P.lineStrong, width: 1 }, hoverinfo: 'skip' },
      { x: xs, y: evs.map((e) => e.skin), text: lab.map((l) => ` ${l} `), type: 'scatter', mode: 'markers+text',
        textposition: xs.map((x) => (Math.log(x / kmin) / Math.log(kmax / kmin) < 0.3 ? 'middle left' : 'middle right')), textfont: { size: 11, color: P.ink2 },
        marker: { size: evs.map((_, i) => (sel[i] ? 14 : 11)), color: evs.map((_, i) => (sel[i] ? P.accent : P.ink2)), line: { color: P.surface, width: 2 } },
        customdata: evs.map((e) => [e.delta_p_skin_psi, e.flow_efficiency]),
        hovertemplate: '<b>%{text}</b><br>k %{x:.1f} md<br>skin %{y:.2f}<br>ΔP skin %{customdata[0]:.0f} psi<extra></extra>' },
    ], charts.layout({ margin: { l: 56, r: 16, t: 10, b: 46 }, hovermode: 'closest',
      xaxis: charts.axis({ type: 'log', title: 'permeability, md', range: [Math.log10(kmin), Math.log10(kmax)], tickvals: charts.logTicks(kmin, kmax) }), yaxis: charts.axis({ title: 'skin', range: [smin, smax] }),
      annotations: [{ text: 'damaged', x: 1, xref: 'paper', y: smax * 0.92, yref: 'y', xanchor: 'right', showarrow: false, font: { size: 11, color: P.muted } },
                    { text: 'stimulated', x: 1, xref: 'paper', y: smin * 0.92, yref: 'y', xanchor: 'right', showarrow: false, font: { size: 11, color: P.muted } }] }));
    const ys = evs.map((e) => `${e.well_name} `);
    await charts.draw(root.querySelector('#jj'), [
      ...evs.map((e, i) => ({ x: [e.J_vfm, e.J_pss], y: [ys[i], ys[i]], type: 'scatter', mode: 'lines', line: { color: sel[i] ? P.accent : P.lineStrong, width: sel[i] ? 3 : 2 }, hoverinfo: 'skip', showlegend: false })),
      { x: evs.map((e) => e.J_vfm), y: ys, type: 'scatter', mode: 'markers', name: 'flow meter', marker: { color: P.oil, size: 11, line: { color: P.surface, width: 2 } }, hovertemplate: '%{y}flow meter %{x:.2f} stb/d/psi<extra></extra>' },
      { x: evs.map((e) => e.J_pss), y: ys, type: 'scatter', mode: 'markers', name: 'from k and skin', marker: { color: P.ink, size: 11, symbol: 'diamond', line: { color: P.surface, width: 2 } }, hovertemplate: '%{y}from build-up %{x:.2f} stb/d/psi<extra></extra>' },
    ], charts.layout({ margin: { l: 60, r: 16, t: 30, b: 46 }, hovermode: 'closest', showlegend: true,
      legend: { orientation: 'h', x: 0, y: 1.04, yanchor: 'bottom', font: { size: 11, color: P.ink2 } },
      xaxis: charts.axis({ type: 'log', title: 'productivity index, stb/d per psi', tickvals: charts.logTicks(0.1, 100) }), yaxis: charts.axis({ autorange: 'reversed', ticks: '' }) }));
  }

  async function drawPr() {
    const w = evs.find((e) => e.event_id === S.event).well_name;
    root.querySelector('#pr-well').textContent = w;
    const tr = [];
    for (const [k, s] of Object.entries(Rv.pressure)) {
      if (k === w) continue;
      tr.push({ x: s.dates, y: s.pr, type: 'scatter', mode: 'lines', line: { color: P.lineStrong, width: 1.2 }, name: k, hovertemplate: `${k} %{y:,.0f} psia<extra></extra>` });
    }
    const s = Rv.pressure[w];
    if (s) {
      tr.push({ x: s.dates, y: s.pr, type: 'scatter', mode: 'lines', line: { color: P.accent, width: 2.4 }, name: w, hovertemplate: `<b>${w}</b> %{y:,.0f} psia<extra></extra>` });
      tr.push({ x: [s.dates[s.dates.length - 1]], y: [s.pr[s.pr.length - 1]], type: 'scatter', mode: 'text', text: [`  ${w}`], textposition: 'middle right', textfont: { color: P.ink, size: 12 }, hoverinfo: 'skip' });
    }
    await charts.draw(root.querySelector('#pr'), tr, charts.layout({ margin: { l: 64, r: 60, t: 10, b: 40 }, hovermode: 'closest',
      xaxis: charts.axis({ type: 'date' }), yaxis: charts.axis({ title: 'psia' }) }));
  }

  await pick(S.event, evs.find((e) => e.event_id === S.event).well_name);
  return () => root.querySelectorAll('.js-plotly-plot').forEach((p) => { try { Plotly.purge(p); } catch (e) {} });
}
