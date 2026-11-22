// Plotly theming from the CSS tokens, so day / night charts are stepped from the same palette.
export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function rgba(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// naive ISO (no zone) -> epoch ms treated as UTC, which is how Plotly reads date axes
export const ms = (iso) => Date.parse(iso.length <= 10 ? iso : (/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z'));
export const timeAxis = (startIso, stepMin, n) => { const t0 = ms(startIso); return Array.from({ length: n }, (_, i) => t0 + i * stepMin * 60000); };

export function palette() {
  const night = document.documentElement.dataset.theme === 'night';
  return {
    ink: css('--ink'), ink2: css('--ink-2'), muted: css('--muted'), line: css('--line'), lineStrong: css('--line-strong'),
    surface: css('--surface'), surface2: css('--surface-2'), accent: css('--accent-fill'),
    oil: css('--oil'), water: css('--water'), gas: css('--gas'), der: css('--der'), model: css('--model'),
    // sensor identities (one per small-multiple panel, categorical slots)
    s: night
      ? { pdh: '#3987e5', tdh: '#d95926', whp: '#9085e9', whpd: '#199e70', ann: '#d55181', gl: '#c98500' }
      : { pdh: '#2a78d6', tdh: '#eb6834', whp: '#6250d6', whpd: '#1baf7a', ann: '#e87ba4', gl: '#eda100' },
  };
}

export function axis(extra = {}) {
  const P = palette();
  return {
    gridcolor: P.line, linecolor: P.lineStrong, zeroline: false, ticks: 'outside', tickcolor: P.lineStrong, ticklen: 4,
    tickfont: { size: 11, color: P.muted }, title: { font: { size: 12, color: P.ink2 }, standoff: 8 }, automargin: true,
    showspikes: false, ...extra,
    ...(extra.title && typeof extra.title === 'string' ? { title: { text: extra.title, font: { size: 12, color: P.ink2 }, standoff: 8 } } : {}),
  };
}

export function layout(extra = {}) {
  const P = palette();
  return {
    font: { family: 'Archivo, system-ui, sans-serif', size: 12, color: P.ink },
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    margin: { l: 64, r: 16, t: 10, b: 40 },
    hoverlabel: { bgcolor: P.surface, bordercolor: P.lineStrong, font: { family: 'Archivo, system-ui, sans-serif', color: P.ink, size: 12 } },
    showlegend: false, dragmode: 'zoom',
    ...extra,
  };
}

export const config = {
  displaylogo: false, responsive: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'toggleSpikelines', 'hoverCompareCartesian', 'hoverClosestCartesian'],
  toImageButtonOptions: { format: 'png', scale: 2 },
};

export function draw(el, data, lay) {
  if (!el) return;
  return Plotly.react(el, data, lay, config);
}

// tiny inline sparkline path for chips and lists
export function sparkPath(vals, w = 60, h = 16, pad = 1.5) {
  const v = vals.filter((x) => x !== null && Number.isFinite(x));
  if (v.length < 2) return '';
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  return vals.map((x, i) => {
    const X = (i / (vals.length - 1)) * w, Y = x === null ? h - pad : h - pad - ((x - lo) / span) * (h - 2 * pad);
    return `${i ? 'L' : 'M'}${X.toFixed(1)},${Y.toFixed(1)}`;
  }).join('');
}

export const fmt = (x, d = 0) => (x === null || x === undefined || !Number.isFinite(x)) ? '–' : x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
export const fmtSigned = (x, d = 2) => (!Number.isFinite(x) ? '–' : (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d));

// 1-2-5 tick values for a log axis between lo and hi
export function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++)
    for (const m of [1, 2, 5]) { const v = m * Math.pow(10, e); if (v >= lo && v <= hi) out.push(v); }
  return out;
}
