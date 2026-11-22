// The workflow drawn as the selected well: to scale from the completion file.
// Each stage is tied to the part of the well it reads: wellhead, surface gauges, gas-lift valve,
// downhole gauge, perforations. Fluid rises in the tubing as the analysis completes.

export const STAGES = [
  { id: 'load',      n: 1, label: 'Load data',        anchor: 'tree' },
  { id: 'field',     n: 2, label: 'Field data',       anchor: 'surface' },
  { id: 'vfm',       n: 3, label: 'Flow rates',       anchor: 'glv' },
  { id: 'pta',       n: 4, label: 'Build-up tests',   anchor: 'gauge' },
  { id: 'reservoir', n: 5, label: 'Reservoir',        anchor: 'perf' },
  { id: 'export',    n: 6, label: 'Export',           anchor: null },
];

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
};

export class Spine {
  constructor(host, onGo) {
    this.host = host; this.onGo = onGo;
    this.state = { well: null, comp: null, active: 'load', unlocked: new Set(['load']), done: new Set(), busy: null, level: 0, subs: {} };
    new ResizeObserver(() => this.draw()).observe(host);
  }

  set(patch) { Object.assign(this.state, patch); this.draw(); }

  setLevel(level) {           // 0..1, animates the fluid column without a full redraw
    this.state.level = level;
    if (this.fluid) this._placeFluid();
  }

  _placeFluid() {
    const { y0, yb } = this.geo; const top = yb - (yb - y0) * this.state.level;
    this.fluid.setAttribute('y', top.toFixed(1)); this.fluid.setAttribute('height', Math.max(0, yb - top).toFixed(1));
  }

  draw() {
    const W = this.host.clientWidth, H = this.host.clientHeight;
    if (!W || !H) return;
    this.host.innerHTML = '';
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true' }, this.host);
    const defs = el('defs', {}, svg);
    const g = el('linearGradient', { id: 'fluidGrad', x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
    el('stop', { offset: '0%', style: 'stop-color:var(--accent-fill);stop-opacity:.95' }, g);
    el('stop', { offset: '100%', style: 'stop-color:var(--accent);stop-opacity:1' }, g);

    const c = this.state.comp || {};
    const datum = c.datum_tvd_ft || 9000, gauge = c.gauge_tvd_ft || datum - 300, glv = c.gl_valve_tvd_ft || datum * 0.45;
    const pay = c.net_pay_thickness_ft || 80;
    const cx = 48, cas = 12, tub = 4.5;
    const y0 = 86, yb = H - 64;                                 // ground, total depth of drawing
    const maxD = datum + Math.max(300, pay * 2.5);
    const Y = (d) => y0 + (d / maxD) * (yb - y0);
    this.geo = { y0, yb: Y(datum) };

    // earth and depth scale
    el('rect', { class: 'earth', x: 0, y: y0, width: 92, height: H - y0 }, svg);
    const dg = el('g', { class: 'depth' }, svg);
    const step = maxD > 8000 ? 2000 : 1000;
    for (let d = step; d < maxD - step * 0.4; d += step) {
      el('line', { x1: 22, x2: 30, y1: Y(d), y2: Y(d) }, dg);
      const t = el('text', { x: 20, y: Y(d) + 3, 'text-anchor': 'end' }, dg); t.textContent = (d / 1000).toFixed(0) + 'k';
    }
    const lab = el('text', { x: 20, y: y0 + 12, 'text-anchor': 'end' }, dg); lab.textContent = 'ft';

    // reservoir layer
    const payPx = Math.max(26, (pay / maxD) * (yb - y0) * 4);
    const ry = Y(datum) - payPx / 2;
    el('rect', { class: 'rock', x: 0, y: ry, width: 92, height: payPx }, svg);
    const hatch = el('g', { class: 'rock-hatch' }, svg);
    for (let x = -payPx; x < 92; x += 7) el('line', { x1: x, y1: ry + payPx, x2: x + payPx, y2: ry }, hatch);
    const clip = el('clipPath', { id: 'rockClip' }, defs); el('rect', { x: 0, y: ry, width: 92, height: payPx }, clip);
    hatch.setAttribute('clip-path', 'url(#rockClip)');

    // cement sheath, casing, tubing, fluid
    el('rect', { class: 'cement', x: cx - cas - 4, y: y0, width: 2 * cas + 8, height: Y(datum) + payPx / 2 - y0 }, svg);
    el('rect', { x: cx - cas, y: y0, width: 2 * cas, height: Y(datum) + payPx / 2 - y0, style: 'fill:var(--surface)' }, svg);
    this.fluid = el('rect', { class: 'fluid', x: cx - tub + 0.6, width: 2 * tub - 1.2, y: Y(datum), height: 0, rx: 1 }, svg);
    this._placeFluid();
    for (const s of [-1, 1]) {
      el('line', { class: 'casing', x1: cx + s * cas, x2: cx + s * cas, y1: y0, y2: Y(datum) + payPx / 2 }, svg);
      el('line', { class: 'tubing', x1: cx + s * tub, x2: cx + s * tub, y1: y0 - 6, y2: Y(gauge) + 10 }, svg);
    }
    // perforations
    for (let i = 0; i < 5; i++) {
      const y = ry + 5 + i * (payPx - 10) / 4;
      el('line', { class: 'perf', x1: cx - cas - 9, x2: cx - cas + 3, y1: y, y2: y }, svg);
      el('line', { class: 'perf', x1: cx + cas - 3, x2: cx + cas + 9, y1: y, y2: y }, svg);
    }
    // gas-lift valve (diamond on the tubing) and downhole gauge
    const gy = Y(glv);
    el('path', { class: 'comp', d: `M${cx + tub} ${gy - 6} l6 6 l-6 6 l-6 -6 z` }, svg);
    const ay = Y(gauge);
    el('rect', { class: 'comp-gauge', x: cx - 3, y: ay - 7, width: 6, height: 14, rx: 2 }, svg);
    // wellhead / christmas tree + ground
    el('line', { class: 'ground', x1: 0, x2: 92, y1: y0, y2: y0 }, svg);
    const tree = el('g', { class: 'tree' }, svg);
    el('rect', { x: cx - 14, y: y0 - 10, width: 28, height: 10, rx: 1.5 }, tree);
    el('rect', { x: cx - 4, y: y0 - 46, width: 8, height: 36 }, tree);
    el('rect', { class: 'valve', x: cx - 9, y: y0 - 34, width: 18, height: 7, rx: 1.5 }, tree);
    el('rect', { class: 'valve', x: cx - 9, y: y0 - 22, width: 18, height: 7, rx: 1.5 }, tree);
    el('rect', { x: cx + 4, y: y0 - 31, width: 26, height: 4 }, tree);          // flowline
    el('rect', { x: cx - 7, y: y0 - 52, width: 14, height: 6, rx: 1.5 }, tree);
    // surface gauge on the annulus
    el('circle', { class: 'comp', cx: cx - cas - 9, cy: y0 + 14, r: 4.5 }, svg);
    el('line', { class: 'tubing', x1: cx - cas - 4.5, x2: cx - cas, y1: y0 + 14, y2: y0 + 14 }, svg);
    if (this.state.well) { const t = el('text', { class: 'wellname', x: 6, y: y0 - 64 }, svg); t.textContent = this.state.well; }

    const anchors = { tree: [cx + 30, y0 - 29], surface: [cx - cas - 4, y0 + 14], glv: [cx + tub + 6, gy], gauge: [cx + 3, ay], perf: [cx + cas + 9, Y(datum)] };

    // nodes, spaced evenly, joined to their component by a leader
    const nodes = document.createElement('div'); nodes.className = 'spine-nodes'; this.host.appendChild(nodes);
    const top = 44, bottom = H - 34, gap = (bottom - top) / STAGES.length;
    const { active, unlocked, done, busy, subs } = this.state;
    STAGES.forEach((s, i) => {
      const y = top + gap * (i + 0.5);
      const on = unlocked.has(s.id);
      if (s.anchor) {
        const [ax, ay2] = anchors[s.anchor];
        const x1 = 100, mx = 84;
        el('path', { class: 'leader' + (active === s.id ? ' on' : ''), d: `M${x1} ${y} C${mx} ${y} ${mx + 4} ${ay2} ${ax} ${ay2}` }, svg);
      }
      const b = document.createElement('button');
      b.className = 'node' + (active === s.id ? ' active' : '') + (done.has(s.id) ? ' done' : '') + (busy === s.id ? ' busy' : '');
      b.style.top = `${y}px`; b.disabled = !on;
      b.setAttribute('aria-current', active === s.id ? 'step' : 'false');
      b.innerHTML = `<span class="dot">${done.has(s.id) && active !== s.id ? '<svg viewBox="0 0 12 12" width="11" height="11"><path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' : s.n}</span>
        <span class="nl">${s.label}</span><span class="ns">${subs[s.id] || ''}</span>`;
      b.title = `${s.label} (${s.n})`;
      b.addEventListener('click', () => on && this.onGo(s.id));
      nodes.appendChild(b);
    });
  }
}
