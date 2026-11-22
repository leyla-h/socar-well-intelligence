"""Exports: Phase 1 / Phase 2 Excel + CSV, PTA plot PNGs, PDF report, everything as one ZIP."""
from __future__ import annotations
import io as _io
import os
import textwrap
import zipfile
import datetime as _dt
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from . import pta as _pta, interpret

INK = '#14201B'; INK2 = '#4B5852'; MUTED = '#7C8781'; LINE = '#D3D9D2'; ACC = '#9A5A00'
OIL, WATER, GAS = '#008300', '#2a78d6', '#e34948'
DER, MODEL = '#eb6834', '#6250d6'
plt.rcParams.update({'font.size': 9, 'axes.edgecolor': LINE, 'axes.labelcolor': INK2, 'xtick.color': MUTED, 'ytick.color': MUTED,
                     'axes.titlesize': 10, 'axes.titleweight': 'bold', 'axes.titlecolor': INK, 'grid.color': '#E6EAE5', 'axes.grid': True,
                     'grid.linewidth': 0.6, 'legend.frameon': False, 'figure.facecolor': 'white'})


# ----------------------------------------------------------------------------- Excel helpers
F = Font(name='Arial', size=10); FB = Font(name='Arial', size=10, bold=True, color='FFFFFF'); HF = PatternFill('solid', fgColor='14201B')


def _sheet(ws, df, fmt=None):
    if len(df):
        num = df.select_dtypes('number').columns; df = df.copy(); df[num] = df[num].round(6)
    ws.append(list(df.columns))
    for cell in ws[1]: cell.font = FB; cell.fill = HF; cell.alignment = Alignment(wrap_text=True, vertical='center')
    for r in df.itertuples(index=False):
        ws.append([None if (isinstance(v, float) and np.isnan(v)) else (v.to_pydatetime() if isinstance(v, pd.Timestamp) else v) for v in r])
    for row in ws.iter_rows(min_row=2):
        for cl in row:
            cl.font = F
            if fmt and cl.column_letter in fmt: cl.number_format = fmt[cl.column_letter]
    for i, col in enumerate(df.columns, 1): ws.column_dimensions[get_column_letter(i)].width = max(12, min(34, len(str(col)) + 2))
    ws.freeze_panes = 'A2'


def _notes(ws, lines, width=150):
    for n in lines: ws.append([n])
    for row in ws.iter_rows():
        for c in row: c.font = F
    ws['A1'].font = Font(name='Arial', size=11, bold=True); ws.column_dimensions['A'].width = width


def phase1_excel(ws_) -> bytes:
    m = ws_.model; P = ws_.daily
    wb = Workbook(); sh = wb.active; sh.title = 'Predictions'
    _sheet(sh, ws_.phase1_table(), {'A': 'yyyy-mm-dd', 'C': '#,##0.00', 'D': '#,##0.00', 'E': '#,##0.00'})
    aux = P[['date', 'well_name', 'producing_fraction_of_day', 'reservoir_pressure_psia', 'dh_pressure_psia']].copy()
    aux[aux.columns[2:]] = aux[aux.columns[2:]].round(3)
    _sheet(wb.create_sheet('Daily_Diagnostics'), aux, {'A': 'yyyy-mm-dd'})
    rows = []
    for w, p in m['wells'].items():
        rows.append(dict(well_name=w, eta_degF_per_psi=p['eta_degF_per_psi'], T_res_degF=p['T_res_degF'], J_oil_stbd_per_psi=p['J_o'],
                         drawdown_offset_psi=p['D_offset'], water_model=ws_.water_mode, water_exp_a=p['water_coef'][0],
                         water_exp_b=p['water_coef'][1] if len(p['water_coef']) > 1 else None, GOR_scf_stb=p['GOR_mscf_stb'] * 1000,
                         **{k: v for k, v in m.get('loo_mape', {}).get(w, {}).items()}))
    _sheet(wb.create_sheet('Model_Parameters'), pd.DataFrame(rows))
    if ws_.validation is not None and len(ws_.validation):
        V = ws_.validation.copy(); num = V.select_dtypes('number').columns; V[num] = V[num].round(2)
        _sheet(wb.create_sheet('Test_Validation'), V, {'B': 'yyyy-mm-dd hh:mm', 'C': 'yyyy-mm-dd hh:mm'})
    _sheet(wb.create_sheet('Data_Cleaning_Log'), ws_.clean_log)
    if ws_.label_fixes is not None and len(ws_.label_fixes): _sheet(wb.create_sheet('Test_Label_Fixes'), ws_.label_fixes)
    v = m.get('validation', {})
    lines = ['Phase 1 - Virtual Flow Metering: method',
             '1. Cleaning: duplicates removed; -999.25 -> missing; spikes (|ln(x/median7)| > threshold) removed; gaps interpolated on a 1-min grid; shut-ins from choke events, cross-checked with gas-lift = 0.',
             '2. Physics: downhole temperature = T_res + eta*(P_res - Pwf) (Joule-Thomson heating) -> P_res(t) = Pwf + (T - T_res)/eta, robust local-linear smoothing (+-10 d).',
             '3. Rates per minute: oil = J*(drawdown + offset); water = exp(a+bt)*(drawdown + offset); gas (formation, excl. lift gas) = solution GOR * oil; 0 while shut in. Daily = mean of minutes.',
             f"4. Trained on {m['training']['n_tests']} well tests ({m['training']['start'][:10]} to {m['training']['end'][:10]}).",
             (f"5. Accuracy vs well tests - leave-one-out MAPE: oil {v['loo_mape']['oil']:.1f}%, water {v['loo_mape']['water']:.1f}%, gas {v['loo_mape']['gas']:.1f}%; "
              f"walk-forward (train before a cut-off, test after): oil {v['walk_forward_mape']['oil']:.1f}%, water {v['walk_forward_mape']['water']:.1f}%, gas {v['walk_forward_mape']['gas']:.1f}%.") if v else '']
    _notes(wb.create_sheet('Methodology'), lines)
    b = _io.BytesIO(); wb.save(b); return b.getvalue()


def phase2_excel(ws_) -> bytes:
    T = ws_.pta_table()
    wb = Workbook(); sh = wb.active; sh.title = 'Summary'
    S = ws_.phase2_csv_table() if len(T) else pd.DataFrame()
    if len(T): S.insert(0, 'event_id', T['event_id'].values); S['reported_from'] = T['reported_source'].values
    _sheet(sh, S, {'C': 'yyyy-mm-dd hh:mm', 'D': '0.000', 'E': '0.00', 'F': '0.000', 'G': '0.00'})
    calc = T.drop(columns=[c for c in T.columns if c.startswith('reg_')]) if len(T) else T
    sh2 = wb.create_sheet('PTA_Calculation'); _sheet(sh2, calc, {'C': 'yyyy-mm-dd hh:mm', 'D': 'yyyy-mm-dd hh:mm', 'F': 'yyyy-mm-dd'})
    n = len(calc) + 3
    for i, t in enumerate(['q = VFM daily oil rate of the last fully producing day before shut-in; tp = 24*Np/q, Np = cum. oil to 1-Jan-2025 + VFM cumulative.',
                           'MTR picked automatically where the Bourdet derivative is flat (+-10%); m = slope of pws vs log10((tp+dt)/dt).',
                           'k = 162.6 q Bo mu/(m h); s = 1.1513[(p1hr-pwf)/m - log10(k/(phi mu ct rw^2)) + 3.2275]; dPskin = 0.8686 m s.']):
        sh2.cell(n + i, 1, t).font = F
    reg = T[['event_id'] + [c for c in T.columns if c.startswith('reg_')] + ['permeability_md', 'skin']] if len(T) else T
    _sheet(wb.create_sheet('Regression_Check'), reg)
    rows = []
    for rec in ws_.events_pta:
        if rec['status'] != 'ok': continue
        C = ws_.pta_cache[rec['event_id']]
        for f in interpret.event_findings(C, ws_.model['wells'][rec['well_name']], (ws_.prs_daily or {}).get(rec['well_name'])):
            rows.append(dict(event_id=rec['event_id'], topic=f['title'], finding=f['text']))
    sh4 = wb.create_sheet('Interpretation'); _sheet(sh4, pd.DataFrame(rows)); sh4.column_dimensions['C'].width = 140
    b = _io.BytesIO(); wb.save(b); return b.getvalue()


# ----------------------------------------------------------------------------- plots
def pta_figure(ws_, eid):
    C = ws_.pta_cache[eid]; E, H, Dg, R = C['E'], C['H'], C['Dg'], C.get('R')
    w = E['well_name']; s, rs = E['shut_in_start'], E['shut_in_end']
    g = ws_.clean[ws_.clean.well_name == w].set_index('timestamp'); pw = ws_.daily[ws_.daily.well_name == w].set_index('date')
    dt, p = E['dt'], E['p']; tp = H['tp']; HT = (tp + dt) / dt; mm = (dt >= H['t1']) & (dt <= H['t2'])
    fig, ax = plt.subplots(2, 2, figsize=(15, 10))
    hh = g.loc[s - pd.Timedelta('3D'):rs + pd.Timedelta('2D')]
    a = ax[0, 0]; a.plot(hh.index, hh.dh_pressure_psia, lw=.7, color=WATER); a.set_ylabel('Downhole pressure, psia')
    a.axvspan(s, rs, color=LINE, alpha=.6, lw=0)
    a2 = a.twinx(); pr = pw.loc[(s - pd.Timedelta('3D')).normalize():(rs + pd.Timedelta('2D')).normalize()]
    a2.step(pr.index + pd.Timedelta('12h'), pr.oil_rate_stbd, where='mid', color=OIL, lw=1.6); a2.set_ylabel('VFM daily oil rate, stb/d'); a2.grid(False)
    a.set_title(f'{w} - pressure and predicted oil rate'); a.tick_params(axis='x', rotation=30)
    a = ax[0, 1]; a.semilogx(HT, p, '.', ms=2, color=MUTED, label='build-up data'); a.semilogx(HT[mm], p[mm], '.', ms=3, color=ACC, label=f"MTR {H['t1']:.2f}-{H['t2']:.2f} h")
    xx = np.logspace(0, np.log10(HT.max()), 50)
    a.semilogx(xx, H['p_star'] - H['m'] * np.log10(xx), '--', color=INK, lw=1, label=f"straight-line check m = {H['m']:.2f}, p* = {H['p_star']:.0f}")
    if R and 'k' in R:
        a.semilogx(HT, _pta.model_curve(E, R), '-', color=MODEL, lw=1, label='regression check')
    a.invert_xaxis(); a.set_xlabel('Horner time (tp+Δt)/Δt'); a.set_ylabel('pws, psia'); a.legend(loc='upper left')
    rep = R if (R and 'k' in R) else dict(k=H['k'], skin=H['skin'], dps=H['dps'])
    a.set_title(f"Horner plot   k = {rep['k']:.1f} md,  s = {rep['skin']:.2f},  ΔPskin = {rep['dps']:.0f} psi")
    a = ax[1, 0]; tb, yb, der, ok = Dg['tb'], Dg['yb'], Dg['der'], Dg['ok']
    a.loglog(tb, yb - E['pwf'], 'o', ms=3, color=WATER, label='Δp'); a.loglog(tb[ok], der[ok], 's', ms=3, color=DER, label="Bourdet derivative Δp'")
    a.axvspan(H['t1'], H['t2'], color=ACC, alpha=.10, lw=0, label='radial flow (MTR)'); a.axhline(H['m'] / 2.303, color=INK, ls='--', lw=1)
    a.set_xlabel('Δt, h'); a.set_ylabel('psi'); a.legend(loc='lower right'); a.set_title('Log-log diagnostic')
    a = ax[1, 1]; a.semilogx(dt, p, '.', ms=2, color=MUTED); a.semilogx(dt[mm], p[mm], '.', ms=3, color=ACC)
    a.axhline(H['p1hr'], color=DER, ls=':', label=f"p1hr = {H['p1hr']:.1f}"); a.axhline(E['pwf'], color=WATER, ls=':', label=f"pwf = {E['pwf']:.1f}")
    a.set_xlabel('Δt, h'); a.set_ylabel('pws, psia'); a.set_title(f"MDH plot (slope {H['mdh_slope']:.2f} psi/cycle)"); a.legend(loc='lower right')
    fig.suptitle(f"Build-up {w}  {s:%Y-%m-%d %H:%M} → {rs:%Y-%m-%d %H:%M}   q_oil = {H['q']:.0f} stb/d (VFM), tp = {tp:.0f} h", fontsize=13, color=INK, fontweight='bold')
    fig.tight_layout()
    return fig


def vfm_figure(ws_, w):
    d = ws_.daily[ws_.daily.well_name == w]; V = ws_.validation
    fig, ax = plt.subplots(3, 1, figsize=(14, 8.5), sharex=True)
    for a, col, mc, lab, colr in zip(ax, ['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd'], ['oil', 'water', 'gas'],
                                     ['Oil, stb/d', 'Water, stb/d', 'Gas, Mscf/d'], [OIL, WATER, GAS]):
        a.plot(d.date, d[col], lw=1.3, color=colr, label='VFM daily prediction'); a.set_ylabel(lab)
        if V is not None and len(V):
            v = V[V.well_name == w]; tm = v.test_start + (v.test_end - v.test_start) / 2
            a.scatter(tm, v[mc + '_meas'], color=INK, s=22, zorder=5, label='well test')
    ax[0].legend(loc='upper right'); ax[0].set_title(f'{w} - VFM daily rates')
    fig.tight_layout(); return fig


def fig_png(fig, dpi=90) -> bytes:
    b = _io.BytesIO(); fig.savefig(b, format='png', dpi=dpi); plt.close(fig); return b.getvalue()


def plots_zip(ws_) -> bytes:
    b = _io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        for eid in ws_.pta_cache:
            C = ws_.pta_cache[eid]
            z.writestr(f"pta_plots/{C['E']['well_name']}_{C['E']['shut_in_start']:%Y%m%d}_buildup.png", fig_png(pta_figure(ws_, eid)))
        for w in sorted(ws_.daily.well_name.unique()):
            z.writestr(f'vfm_plots/{w}_vfm.png', fig_png(vfm_figure(ws_, w), 80))
    return b.getvalue()


# ----------------------------------------------------------------------------- PDF report
def _text_page(pdf, title, blocks, sub=None):
    fig = plt.figure(figsize=(8.27, 11.69)); fig.text(0.08, 0.93, title, fontsize=18, fontweight='bold', color=INK)
    y = 0.89
    if sub: fig.text(0.08, y, sub, fontsize=10, color=INK2); y -= 0.04
    for head, body in blocks:
        if y < 0.08:
            pdf.savefig(fig); plt.close(fig); fig = plt.figure(figsize=(8.27, 11.69)); y = 0.93
        if head: fig.text(0.08, y, head, fontsize=11, fontweight='bold', color=INK); y -= 0.022
        for line in textwrap.wrap(body, 98):
            fig.text(0.08, y, line, fontsize=9, color=INK2); y -= 0.017
        y -= 0.012
    pdf.savefig(fig); plt.close(fig)


def _table_page(pdf, title, df, note=None):
    fig = plt.figure(figsize=(11.69, 8.27)); fig.text(0.05, 0.93, title, fontsize=16, fontweight='bold', color=INK)
    ax = fig.add_axes([0.05, 0.08, 0.9, 0.8]); ax.axis('off')
    tb = ax.table(cellText=df.values, colLabels=df.columns, loc='upper left', cellLoc='right', colLoc='right')
    tb.auto_set_font_size(False); tb.set_fontsize(8); tb.scale(1, 1.35)
    for (r, c), cell in tb.get_celld().items():
        cell.set_edgecolor(LINE)
        if r == 0: cell.set_facecolor(INK); cell.set_text_props(color='white', fontweight='bold')
    if note: fig.text(0.05, 0.04, note, fontsize=8, color=MUTED)
    pdf.savefig(fig); plt.close(fig)


def pdf_report(ws_) -> bytes:
    b = _io.BytesIO(); m = ws_.model; P = ws_.daily
    with PdfPages(b) as pdf:
        span = f"{P.date.min():%d %b %Y} – {P.date.max():%d %b %Y}"
        tot = P.groupby('well_name')[['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']].sum().sum()
        T = ws_.pta_table()
        v = m.get('validation', {})
        blocks = [('Data', f"{len(P.well_name.unique())} wells, {span}. {ws_.info.get('raw_rows', 0):,} sensor rows read, "
                           f"{ws_.info.get('duplicates_removed', 0):,} duplicates removed, sentinels and spikes cleaned on a 1-minute grid."),
                  ('Phase 1 - Virtual Flow Metering', f"Field production over the period: {tot.oil_rate_stbd:,.0f} stb oil, {tot.water_rate_stbd:,.0f} stb water, "
                           f"{tot.gas_rate_mscfd:,.0f} Mscf formation gas. Model: {m['name']}, trained on {m['training']['n_tests']} well tests."
                           + (f" Accuracy vs well tests on later, unseen months: oil {v['walk_forward_mape']['oil']:.1f}%, water {v['walk_forward_mape']['water']:.1f}%, gas {v['walk_forward_mape']['gas']:.1f}% MAPE." if v else '')),
                  ('Phase 2 - Build-up analysis', f"{len(T)} shut-in(s) analysed with the VFM daily oil rate (single-phase oil). Reported values come from a full model "
                           f"regression (radial flow, wellbore storage, skin, boundary) fitted to every build-up point; the Horner straight line is the check.")]
        for _, r in T.iterrows():
            blocks.append((f"{r.event_id}", f"m = {r.reported_slope:.2f} psi/cycle, k = {r.reported_k_md:.1f} md, skin = {r.reported_skin:+.2f}, "
                                            f"ΔPskin = {r.reported_dps:.0f} psi (shut-in {r.duration_h:.1f} h, q = {r.q_oil_stbd:.0f} stb/d)."))
        _text_page(pdf, 'Well performance report', blocks, sub=f"Generated {_dt.datetime.now():%d %b %Y %H:%M} · Quyu well intelligence studio")
        # field overview
        fig, ax = plt.subplots(3, 1, figsize=(11.69, 8.27), sharex=True)
        fld = P.groupby('date')[['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']].sum()
        for a, c, colr, lab in zip(ax, fld.columns, [OIL, WATER, GAS], ['Oil, stb/d', 'Water, stb/d', 'Gas, Mscf/d']):
            a.plot(fld.index, fld[c], color=colr, lw=1.4); a.set_ylabel(lab)
        ax[0].set_title('Field total - VFM daily rates'); fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
        rows = []
        for w, d in P.groupby('well_name'):
            S = interpret.well_summary(d, (ws_.prs_daily or {}).get(w), m['wells'][w])
            rows.append([w, f"{S['oil_avg']:,.0f}", f"{S['water_avg']:,.0f}", f"{S['gas_avg']:,.0f}", f"{S['wc_start']:.1f} → {S['wc_end']:.1f}",
                         f"{S['pr_last']:,.0f}", f"{S['pr_slope_psi_per_day'] * 30:+.0f}", f"{S['J']:.2f}", f"{S['GOR']:.0f}"])
        _table_page(pdf, 'Phase 1 - per-well summary', pd.DataFrame(rows, columns=['Well', 'Oil stb/d', 'Water stb/d', 'Gas Mscf/d', 'Water cut %',
                                                                                    'Pr psia (end)', 'Pr psi/month', 'J stb/d/psi', 'GOR scf/stb']),
                    'Averages over producing days. Pr = reservoir pressure from downhole temperature (Joule-Thomson).')
        for w in sorted(P.well_name.unique()):
            fig = vfm_figure(ws_, w); fig.set_size_inches(11.69, 8.27); fig.tight_layout(); pdf.savefig(fig); plt.close(fig)
        if len(T):
            show = T[['event_id', 'duration_h', 'q_oil_stbd', 'pwf_at_shutin_psia', 'reported_slope', 'reported_k_md', 'reported_skin', 'reported_dps',
                      'p_star_psia', 'permeability_md', 'skin']].copy()
            show.columns = ['Event', 'Shut-in h', 'q stb/d', 'pwf psia', 'm psi/cyc', 'k md', 'skin', 'ΔPskin psi', 'p* psia', 'k Horner', 's Horner']
            for c in show.columns[1:]: show[c] = show[c].map(lambda x: '' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x:,.2f}')
            _table_page(pdf, 'Phase 2 - reservoir properties per shut-in', show, 'Reported m, k, skin, ΔPskin: full model regression (radial flow + storage + skin + boundary). k / s Horner: straight-line check.')
            for eid in ws_.pta_cache:
                fig = pta_figure(ws_, eid); fig.set_size_inches(11.69, 8.27); fig.tight_layout(rect=(0, 0, 1, 0.96)); pdf.savefig(fig); plt.close(fig)
                C = ws_.pta_cache[eid]
                fs = interpret.event_findings(C, m['wells'][C['E']['well_name']], (ws_.prs_daily or {}).get(C['E']['well_name']))
                _text_page(pdf, f'{eid} - interpretation', [(f['title'], f['text']) for f in fs])
    return b.getvalue()


def everything_zip(ws_, model_path=None) -> bytes:
    b = _io.BytesIO()
    p1 = ws_.phase1_table().copy(); p1['date'] = p1.date.dt.strftime('%Y-%m-%d')
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('Phase1_VFM_predictions.csv', p1.to_csv(index=False))
        z.writestr('Phase1_VFM_predictions.xlsx', phase1_excel(ws_))
        z.writestr('Phase2_PTA_results.csv', ws_.phase2_csv_table().to_csv(index=False))
        z.writestr('Phase2_PTA_results.xlsx', phase2_excel(ws_))
        z.writestr('Well_performance_report.pdf', pdf_report(ws_))
        with zipfile.ZipFile(_io.BytesIO(plots_zip(ws_))) as pz:
            for n in pz.namelist(): z.writestr(n, pz.read(n))
        if model_path and os.path.exists(model_path): z.write(model_path, 'vfm_model.pkl')
    return b.getvalue()
