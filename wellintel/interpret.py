"""Plain-language reservoir and well interpretation from the computed numbers (rules, no hidden fitting)."""
from __future__ import annotations
import numpy as np
import pandas as pd


def _fmt(x, d=0):
    return f'{x:,.{d}f}'


def perm_class(k):
    if k < 1: return 'tight'
    if k < 10: return 'low permeability'
    if k < 100: return 'moderate permeability'
    if k < 500: return 'good permeability'
    return 'very high permeability'


def skin_class(s):
    if s > 5: return 'severely damaged', 'warn'
    if s > 2: return 'damaged', 'warn'
    if s > 0: return 'slightly damaged', 'info'
    if s > -2: return 'undamaged to mildly stimulated', 'good'
    return 'stimulated', 'good'


def event_findings(C, model_well, prs_daily=None):
    """C: pta cache entry (E, Dg, auto, H, R). Returns list of dicts {title, text, tone}."""
    E, H, R, A = C['E'], C['H'], C.get('R') or {}, C['auto']
    pv = E['pv']; out = []
    hump = A['thump']
    out.append(dict(title='Flow regimes', tone='info',
                    text=f"Wellbore storage dominates the first {_fmt(3 * hump, 1)} h (derivative hump at {_fmt(hump, 2)} h). "
                         f"Infinite-acting radial flow is used from {_fmt(H['t1'], 2)} to {_fmt(H['t2'], 2)} h, where the Bourdet derivative "
                         f"is flat within ±10%. The Horner line through that window has R² = {H['r2']:.4f}."))
    out.append(dict(title='Permeability', tone='info',
                    text=f"Horner slope m = {_fmt(H['m'], 2)} psi/cycle gives k = {_fmt(H['k'], 1)} md "
                         f"(kh = {_fmt(H['k'] * pv['h'])} md·ft over {_fmt(pv['h'])} ft of net pay): {perm_class(H['k'])}."))
    cls, tone = skin_class(H['skin'])
    total = H['p_star'] - E['pwf']
    txt = (f"Skin s = {H['skin']:+.2f}: the near-wellbore zone is {cls}. The skin pressure drop is {_fmt(H['dps'])} psi, "
           f"{abs(H['dps']) / total * 100:.0f}% of the {_fmt(total)} psi between p* and the flowing pressure; flow efficiency {H['FE']:.2f}.")
    if H['skin'] > 2:
        txt += (f" Removing the damage (s → 0) would raise the rate by roughly {(1 / H['FE'] - 1) * 100:.0f}% at the same drawdown "
                f"— a stimulation candidate.")
    out.append(dict(title='Skin and damage', tone=tone, text=txt))
    if R and 'k' in R:
        dk = (R['k'] / H['k'] - 1) * 100
        if R['boundary'] == 'closed': bnd = f"a no-flow boundary at about {_fmt(R['re'])} ft"
        elif R['boundary'] == 'const': bnd = f"a constant-pressure boundary at about {_fmt(R['re'])} ft"
        else: bnd = 'no boundary is seen within the test'
        out.append(dict(title='Model cross-check', tone='good' if abs(dk) < 10 else 'warn',
                        text=f"A full model fit (radial flow + storage + skin, every build-up point, RMS {R['rms']:.3f} psi) gives "
                             f"k = {_fmt(R['k'], 1)} md ({dk:+.0f}%) and s = {R['skin']:+.2f}, with {bnd}. "
                             f"Wellbore storage C = {R['C']:.4f} bbl/psi."))
    if np.isfinite(pv.get('area_acres', np.nan)):
        re = np.sqrt(pv['area_acres'] * 43560 / np.pi)
        Jpss = H['k'] * pv['h'] / (141.2 * pv['B'] * pv['mu'] * (np.log(re / pv['rw']) - 0.75 + H['skin']))
        J = model_well['J_o']; d = (Jpss / J - 1) * 100
        out.append(dict(title='Agreement with the flow meter', tone='good' if abs(d) <= 20 else 'warn',
                        text=f"With this k and skin, a {_fmt(pv['area_acres'])}-acre drainage area should deliver {Jpss:.2f} stb/d per psi of drawdown. "
                             f"The VFM, calibrated independently on well tests, uses {J:.2f} stb/d/psi ({d:+.0f}%)."
                             + (" Phase 1 and Phase 2 tell a consistent story." if abs(d) <= 20 else " The difference is worth a look.")))
        out.append(dict(title='Radius of investigation', tone='info',
                        text=f"By the end of the build-up the pressure signal reached about {_fmt(H['rinv'])} ft; "
                             f"the drainage radius from the PVT area is about {_fmt(re)} ft."))
    if prs_daily is not None:
        day = E['shut_in_start'].normalize()
        if day in prs_daily.index:
            pr = prs_daily.loc[day]
            out.append(dict(title='Reservoir pressure', tone='info',
                            text=f"The last build-up pressure was {_fmt(E['p'][-1])} psia after {_fmt(E['dt'][-1], 1)} h. The VFM estimates "
                                 f"{_fmt(pr)} psia from the downhole temperature on that day. Horner p* = {_fmt(H['p_star'])} psia is an "
                                 f"infinite-acting extrapolation, so it sits above the average pressure."))
    return out


def well_summary(daily_w: pd.DataFrame, prs: pd.Series | None, p: dict):
    d = daily_w
    prod = d[d.producing_fraction_of_day > 0.99]
    wc = d.water_rate_stbd / (d.oil_rate_stbd + d.water_rate_stbd)
    first = wc[d.producing_fraction_of_day > 0.99].head(14).mean(); last = wc[d.producing_fraction_of_day > 0.99].tail(14).mean()
    slope = np.polyfit(np.arange(len(prs)), prs.values, 1)[0] if prs is not None and len(prs) > 5 else np.nan
    return dict(days=int(len(d)), producing_days=float(d.producing_fraction_of_day.sum()),
                oil_avg=float(prod.oil_rate_stbd.mean()) if len(prod) else 0.0, water_avg=float(prod.water_rate_stbd.mean()) if len(prod) else 0.0,
                gas_avg=float(prod.gas_rate_mscfd.mean()) if len(prod) else 0.0,
                oil_cum=float(d.oil_rate_stbd.sum()), water_cum=float(d.water_rate_stbd.sum()), gas_cum=float(d.gas_rate_mscfd.sum()),
                wc_start=float(first * 100), wc_end=float(last * 100), pr_slope_psi_per_day=float(slope),
                pr_last=float(prs.iloc[-1]) if prs is not None else np.nan, J=p['J_o'], GOR=p['GOR_mscf_stb'] * 1000, eta=p['eta_degF_per_psi'])


def well_findings(S, p):
    out = []
    out.append(dict(title='Production', tone='info',
                    text=f"Averaging {_fmt(S['oil_avg'])} stb/d oil, {_fmt(S['water_avg'])} stb/d water and {_fmt(S['gas_avg'])} Mscf/d "
                         f"formation gas on producing days ({S['producing_days']:.1f} of {S['days']} days)."))
    dwc = S['wc_end'] - S['wc_start']
    out.append(dict(title='Water', tone='warn' if dwc > 5 else 'info',
                    text=f"Water cut moved from {S['wc_start']:.1f}% to {S['wc_end']:.1f}% ({dwc:+.1f} points) over the period."))
    if np.isfinite(S['pr_slope_psi_per_day']):
        out.append(dict(title='Reservoir pressure', tone='info',
                        text=f"Temperature-derived reservoir pressure is {_fmt(S['pr_last'])} psia at the end of the data and changing "
                             f"{S['pr_slope_psi_per_day'] * 30:+.0f} psi per month (depletion)."))
    out.append(dict(title='Inflow', tone='info',
                    text=f"Productivity index {p['J_o']:.2f} stb/d/psi" + (f" with a {p['D_offset']:.0f} psi drawdown offset" if p['use_offset'] else '')
                         + f"; GOR {p['GOR_mscf_stb'] * 1000:.0f} scf/stb (solution GOR)."))
    return out
