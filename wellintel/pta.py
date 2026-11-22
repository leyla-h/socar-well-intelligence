"""Phase 2 - build-up analysis on the VFM-predicted oil rate (single-phase oil), same maths as the Phase 2 notebook.

A. Horner straight line (reported): MTR picked where the Bourdet derivative is flat; m, k, s, dP_skin.
B. Nonlinear regression (cross-check): radial flow + wellbore storage + skin + boundary, Laplace/Stehfest.
"""
from __future__ import annotations
from math import factorial
import warnings
import numpy as np
import pandas as pd
from scipy.special import kve, ive
from scipy.optimize import least_squares

warnings.filterwarnings('ignore', category=RuntimeWarning)


# ----------------------------------------------------------------------------- analytical model
def _stehfest_V(N=12):
    V = np.zeros(N)
    for i in range(1, N + 1):
        s = 0.0
        for k in range((i + 1) // 2, min(i, N // 2) + 1):
            s += k**(N // 2) * factorial(2 * k) / (factorial(N // 2 - k) * factorial(k) * factorial(k - 1) * factorial(i - k) * factorial(2 * k - i))
        V[i - 1] = (-1)**(N // 2 + i) * s
    return V
VS = _stehfest_V(12)


def _pwd_lap(u, CD, S, bound='inf', reD=None):
    x = np.sqrt(u); k0, k1 = kve(0, x), kve(1, x)
    if bound == 'inf':
        A = k0 / k1
    else:
        y = reD * x; i0, i1 = ive(0, x), ive(1, x); e = np.exp(-2 * (y - x))
        if bound == 'closed': a = kve(1, y) / ive(1, y) * e; A = (k0 + a * i0) / (k1 - a * i1)
        else:                 a = kve(0, y) / ive(0, y) * e; A = (k0 - a * i0) / (k1 + a * i1)
    g = A + S * x
    return g / (u * (x + CD * u * g))


def pwd(tD, CD, S, bound='inf', reD=None):
    tD = np.atleast_1d(tD).astype(float)[:, None]; ln2 = np.log(2)
    u = np.arange(1, 13)[None, :] * ln2 / tD
    return (ln2 / tD[:, 0]) * np.sum(VS[None, :] * _pwd_lap(u, CD, S, bound, reD), axis=1)


def buildup_dp(dt_h, tp_h, k, S, C, pv, q, bound='inf', re=None):
    h, phi, mu, ct, rw, B = pv
    a = 0.0002637 * k / (phi * mu * ct * rw**2); CD = 0.8936 * C / (phi * ct * h * rw**2)
    reD = None if re is None or (isinstance(re, float) and np.isnan(re)) else re / rw; mp = 141.2 * q * B * mu / (k * h)
    if bound == 'closed': late = 2 * a * dt_h / reD**2
    elif bound == 'inf':  late = 0.5 * np.log((tp_h + dt_h) / tp_h)
    else:                 late = 0.0
    return mp * (pwd(a * dt_h, CD, S, bound, reD) - late)


def bourdet(x, y, L=0.12):
    d = np.full_like(y, np.nan)
    for i in range(len(x)):
        l = np.where(x <= x[i] - L)[0]; r = np.where(x >= x[i] + L)[0]
        if len(l) == 0 or len(r) == 0: continue
        j, k = l[-1], r[0]; d1 = (y[i] - y[j]) / (x[i] - x[j]); d2 = (y[k] - y[i]) / (x[k] - x[i])
        d[i] = (d1 * (x[k] - x[i]) + d2 * (x[i] - x[j])) / (x[k] - x[j])
    return d


# ----------------------------------------------------------------------------- event preparation
def shutin_events(events: pd.DataFrame, data_end: dict):
    rows = []
    for _, e in events[events.choke_opening_pct == 0].iterrows():
        ev = events[events.well_name == e.well_name]
        later = ev[ev.timestamp > e.timestamp]
        rs = later.timestamp.min() if len(later) else data_end[e.well_name]
        rows.append(dict(well_name=e.well_name, shut_in_start=e.timestamp, shut_in_end=rs, source=e.get('source', 'choke file')))
    return pd.DataFrame(rows)


def prepare_event(w, s, rs, g, pw, pvt_row, cum_before):
    """Arrays + rate history inputs for one shut-in. g: clean well data indexed by timestamp; pw: daily VFM indexed by date."""
    day = s.normalize()
    full = pw[(pw.index < day) & (pw.producing_fraction_of_day > 0.99)]
    if len(full) == 0: raise ValueError('no fully producing day before the shut-in in the loaded data')
    qday = full.index.max(); q = float(pw.loc[qday, 'oil_rate_stbd'])
    frac = (s - day).total_seconds() / 86400
    Np = cum_before + pw.loc[:day - pd.Timedelta('1D'), 'oil_rate_stbd'].sum() + q * frac
    tp = 24 * Np / q
    pwf = float(g.loc[s - pd.Timedelta('4min'):s, 'dh_pressure_psia'].mean())
    b = g.loc[s + pd.Timedelta('1min'):rs]
    dt = ((b.index - s).total_seconds() / 3600).values; p = b.dh_pressure_psia.values.astype(float)
    pv = dict(h=float(pvt_row['net_pay_thickness_ft']), phi=float(pvt_row['porosity_frac']), ct=float(pvt_row['total_compressibility_1_psi']),
              rw=float(pvt_row['wellbore_radius_ft']), B=float(pvt_row['oil_fvf_rb_stb']), mu=float(pvt_row['oil_viscosity_cp']),
              area_acres=float(pvt_row.get('estimated_drainage_area_acres', np.nan)))
    return dict(well_name=w, shut_in_start=s, shut_in_end=rs, qday=qday, q=q, Np=Np, tp=tp, pwf=pwf, dt=dt, p=p, pv=pv)


def diagnostics(E):
    """Log-binned pressure + Bourdet derivative (does not depend on q or PVT)."""
    dt, p, tp = E['dt'], E['p'], E['tp']
    dte = tp * dt / (tp + dt)
    lx = np.log(dte); bins = np.arange(lx.min(), lx.max() + 0.05, np.log(10) / 40)
    idx = np.digitize(lx, bins); xb, yb, tb = [], [], []
    for kk in np.unique(idx):
        mk = idx == kk; xb.append(lx[mk].mean()); yb.append(p[mk].mean()); tb.append(dt[mk].mean())
    xb, yb, tb = np.array(xb), np.array(yb), np.array(tb)
    der = bourdet(xb, yb, 0.12)
    return dict(tb=tb, yb=yb, der=der, ok=~np.isnan(der))


def auto_mtr(Dg):
    tb, der, ok = Dg['tb'], Dg['der'], Dg['ok']
    ihump = np.nanargmax(der); thump = tb[ihump]
    cand = ok & (tb > 3 * thump)
    best = None; lt = np.log10(tb)
    for i in np.where(cand)[0]:
        mk = cand & (lt >= lt[i]) & (lt <= lt[i] + 0.4)
        if lt[mk].max() - lt[i] < 0.35: continue
        cv = np.std(der[mk]) / np.mean(der[mk])
        if best is None or cv < best[0]: best = (cv, i, np.median(der[mk]))
    if best is None:
        i0 = int(np.where(ok)[0][np.searchsorted(lt[ok], lt[ok].max() - 0.4)]); best = (np.nan, i0, der[i0])
    cv, i0, dmed = best
    sel = cand & (np.abs(der / dmed - 1) < 0.10); sel[i0] = True
    j0 = i0
    while j0 - 1 >= 0 and sel[j0 - 1]: j0 -= 1
    j1 = i0
    while j1 + 1 < len(sel) and sel[j1 + 1]: j1 += 1
    return float(tb[j0]), float(tb[j1]), float(thump), (None if np.isnan(cv) else float(cv))


def horner(E, t1, t2, q=None, pv=None):
    """Straight-line Horner analysis on the window t1..t2 (hours). q / pv override the event's values."""
    q = E['q'] if q is None else q
    pv = {**E['pv'], **(pv or {})}
    tp = 24 * E['Np'] / E['q'] if q == E['q'] else 24 * E['Np'] / q
    dt, p, pwf = E['dt'], E['p'], E['pwf']
    HT = (tp + dt) / dt
    mm = (dt >= t1) & (dt <= t2)
    if mm.sum() < 3: raise ValueError('pick a window with at least 3 points')
    A_ = np.c_[np.ones(mm.sum()), np.log10(HT[mm])]
    coef = np.linalg.lstsq(A_, p[mm], rcond=None)[0]; pstar = coef[0]; m = -coef[1]
    r2 = 1 - np.sum((p[mm] - A_ @ coef)**2) / np.sum((p[mm] - p[mm].mean())**2)
    p1 = pstar - m * np.log10(tp + 1.0)
    h, phi, ct, rw, B, mu = pv['h'], pv['phi'], pv['ct'], pv['rw'], pv['B'], pv['mu']
    k = 162.6 * q * B * mu / (m * h)
    skin = 1.1513 * ((p1 - pwf) / m - np.log10(k / (phi * mu * ct * rw**2)) + 3.2275)
    dps = 0.8686 * m * skin
    mdh = np.polyfit(np.log10(dt[mm]), p[mm], 1)[0]
    rinv = np.sqrt(k * dt[-1] / (948 * phi * mu * ct))
    return dict(t1=t1, t2=t2, q=q, tp=tp, m=float(m), p_star=float(pstar), p1hr=float(p1), r2=float(r2), k=float(k), skin=float(skin),
                dps=float(dps), mdh_slope=float(mdh), rinv=float(rinv), PI=float(q / (pstar - pwf)),
                FE=float((pstar - pwf - dps) / (pstar - pwf)), n_points=int(mm.sum()))



# --- exact numerics of the submitted Phase 2 fit (used by regression) ---------------------------------
from scipy.special import k0e as _k0e, k1e as _k1e, i0e as _i0e, i1e as _i1e
from math import log as _log


def _psD_bar(u, reD, bc):
    a = np.sqrt(u); K0 = _k0e(a) * np.exp(-a); K1 = _k1e(a) * np.exp(-a)
    if bc == 'inf': return K0 / (u * a * K1)
    Rr = reD * a; big = Rr > 600
    I0 = _i0e(a) * np.exp(a); I1 = _i1e(a) * np.exp(a)
    Rs = np.where(big, 1.0, Rr)
    if bc == 'closed':
        r = np.where(big, 0.0, _k1e(Rs) / _i1e(Rs) * np.exp(-2 * Rs))
        return (r * I0 + K0) / (u * a * (K1 - r * I1))
    r = np.where(big, 0.0, _k0e(Rs) / _i0e(Rs) * np.exp(-2 * Rs))
    return (K0 - r * I0) / (u * a * (K1 + r * I1))


def _pwD_fit(tD, CD, S, reD, bc):
    tD = np.atleast_1d(tD); out = np.zeros_like(tD, dtype=float)
    for i in range(12):
        u = (i + 1) * _log(2) / tD; ps = u * _psD_bar(u, reD, bc)
        out += VS[i] * (ps + S) / (u * (1 + CD * u * (ps + S)))
    return out * _log(2) / tD


def _fit_dp(par, dt, pv, q, tp, bc):
    lk, S, lC, lre = par; k = 10**lk; C = 10**lC; reD = 10**lre
    tDc = 0.0002637 * k / (pv['phi'] * pv['mu'] * pv['ct'] * pv['rw']**2); CD = 0.8936 * C / (pv['phi'] * pv['ct'] * pv['h'] * pv['rw']**2)
    fac = 141.2 * q * pv['B'] * pv['mu'] / (k * pv['h']); dtD = tDc * dt
    if bc == 'closed': corr = 2 * dtD / reD**2
    elif bc == 'const': corr = 0.0
    else: tpD = tDc * tp; corr = 0.5 * np.log((tpD + dtD) / tpD)
    return fac * (_pwD_fit(dtD, CD, S, reD, bc) - corr)


def regression(E, k0, s0):
    """Fit radial flow + wellbore storage + skin + boundary (infinite / closed / constant-pressure circle) to the build-up.
    Data are averaged into 40 log-spaced bins per cycle so every time decade weighs the same; each boundary model is
    started from the Horner k and skin (and three boundary distances), and the model with the lowest AIC is reported."""
    pv = E['pv']
    dt, p, pwf, tp, q = np.asarray(E['dt'], float), np.asarray(E['p'], float), E['pwf'], E['tp'], E['q']
    lx = np.log10(dt); bins = np.arange(lx.min(), lx.max() + 1e-9, 1 / 40); idx = np.digitize(lx, bins)
    u = np.unique(idx)
    dp = p.astype(np.float32) - float(pwf)      # gauge (float32) precision, exactly as in the submitted run
    tb = np.array([dt[idx == j].mean() for j in u]); pb = np.array([dp[idx == j].mean() for j in u])
    C0 = q * pv['B'] * tb[0] / (24 * pb[0])
    lb = [-1, -6, -4, 2.0]; ub = [4, 50, 1, 5.5]
    fits = {}; best = None
    for bound in ['inf', 'closed', 'const']:
        def res(x, bound=bound):
            return _fit_dp(x, tb, pv, q, tp, bound) - pb
        for lre0 in ([3.5] if bound == 'inf' else [3.0, 3.5, 4.0]):
            x0 = np.clip([np.log10(k0), s0, np.log10(C0), lre0], np.array(lb) + 1e-9, np.array(ub) - 1e-9)
            try:
                r = least_squares(res, x0, bounds=(lb, ub), x_scale=[0.1, 1, 0.1, 0.2], max_nfev=400)
            except Exception as ex:
                fits.setdefault(bound, dict(error=str(ex))); continue
            rss = float(np.sum(r.fun**2)); npar = 3 if bound == 'inf' else 4
            aic = len(pb) * np.log(rss / len(pb)) + 2 * npar
            F = dict(k=float(10**r.x[0]), S=float(r.x[1]), C=float(10**r.x[2]), re=None if bound == 'inf' else float(10**r.x[3] * pv['rw']),
                     rms=float(np.sqrt(rss / len(pb))), aic=float(aic))
            if bound not in fits or 'aic' not in fits[bound] or aic < fits[bound]['aic']: fits[bound] = F
            if best is None or aic < best[0]: best = (aic, bound)
    if best is None: raise ValueError('regression did not converge')
    bnd = best[1]; F = fits[bnd]
    m = 162.6 * q * pv['B'] * pv['mu'] / (F['k'] * pv['h'])
    return dict(boundary=bnd, k=F['k'], skin=F['S'], C=F['C'], re=F['re'], rms=F['rms'], m=float(m), dps=float(0.8686 * m * F['S']), all=fits)


def model_curve(E, R):
    pv = E['pv']; P = (pv['h'], pv['phi'], pv['mu'], pv['ct'], pv['rw'], pv['B'])
    return E['pwf'] + buildup_dp(E['dt'], E['tp'], R['k'], R['skin'], R['C'], P, E['q'], R['boundary'], R['re'])
