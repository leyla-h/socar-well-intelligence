// Stage 6 - export: the two deliverables, the plots, the report, the model.
const GROUPS = [
  { title: 'Phase 1: flow rates', items: [
    { k: 'phase1.xlsx', ico: 'xlsx', name: 'Daily rates workbook', desc: 'date, well_name, oil_rate_stbd, water_rate_stbd, gas_rate_mscfd for every well and day. Also model parameters, accuracy against well tests and the data-cleaning log.' },
    { k: 'phase1.csv', ico: 'csv', name: 'Daily rates, CSV', desc: 'The same five prediction columns as plain CSV.' },
  ] },
  { title: 'Phase 2: build-up tests', items: [
    { k: 'phase2.xlsx', ico: 'xlsx', name: 'Reservoir properties workbook', desc: 'Horner plot slope, skin, permeability (md) and ΔP skin (psi) for each shut-in. Also the calculation inputs, the model cross-check and the written interpretation.' },
    { k: 'phase2.csv', ico: 'csv', name: 'Reservoir properties, CSV', desc: 'well_name, shut_in_start, horner_plot_slope, permeability_md, skin, delta_p_skin_psi.' },
    { k: 'plots.zip', ico: 'zip', name: 'All plots', desc: 'History, Horner, log-log and MDH for every shut-in, plus daily rate charts for every well, as PNG.' },
  ] },
  { title: 'Report and model', items: [
    { k: 'report.pdf', ico: 'pdf', name: 'Well performance report', desc: 'Summary, field and per-well production, a reservoir-property table, then each build-up with its plots and interpretation.' },
    { k: 'model.pkl', ico: 'pkl', name: 'Trained flow meter', desc: 'The model used for these predictions. Drop it into Quyu on another machine to reproduce them.' },
    { k: 'all.zip', ico: 'zip', name: 'Everything', desc: 'All of the above in one archive.' },
  ] },
];

export async function render(root, ctx) {
  const { api } = ctx;
  const ev = await api.get('/api/pta/events', { fresh: true });
  const manual = ev.events.filter((e) => e.manual);
  root.innerHTML = `
  <div class="stage-head"><div><h1>Export results</h1>
    <p>Everything is generated from the current analysis${manual.length ? `, including the radial-flow window you set for ${manual.map((e) => e.event_id).join(', ')}` : ''}.</p></div></div>
  ${GROUPS.map((g) => `<div class="exp-group"><h2>${g.title}</h2><div class="exports">${g.items.map((it) => `
    <div class="exp"><span class="ico ${it.ico}">${it.ico.toUpperCase()}</span><div><h3>${it.name}</h3><p>${it.desc}</p></div>
      <a class="btn ${it.k === 'all.zip' ? 'primary' : ''}" href="/api/export/${it.k}" data-k="${it.k}" download>
        <svg viewBox="0 0 16 16"><path d="M8 2v8m-3.5-3.5L8 10l3.5-3.5M3 13h10"/></svg>Download</a></div>`).join('')}</div></div>`).join('')}`;
  root.querySelectorAll('a[data-k]').forEach((a) => a.addEventListener('click', () => {
    if (['report.pdf', 'all.zip', 'plots.zip'].includes(a.dataset.k)) ctx.toast('Building the file. The download starts in a few seconds.');
  }));
}
