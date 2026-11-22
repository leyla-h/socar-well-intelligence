"""Phase 1 - physics-informed Virtual Flow Meter (same maths as the Phase 1 notebook).

Per well, at minute level, then daily mean:
  reservoir pressure  Pr(t) = Pwf + (T - T_res)/eta   (Joule-Thomson heating), robust local-linear smoothing (+-10 d)
  drawdown            D = Pr - Pwf  (0 while shut in)
  oil                 q_o = J_o * (D + offset)          offset only where leave-one-out clearly justifies it
  water               q_w = exp(a + b t) * (D + offset)  ('team')   or mean of that and WOR(t) * q_o ('ensemble')
  gas (formation)     q_g = GOR * q_o                    GOR = solution GOR from the completion file
"""
from __future__ import annotations
import datetime as _dt
import numpy as np
import pandas as pd

T0 = pd.Timestamp('2025-01-01')
MODEL_FORMAT = 'quyu-vfm/1'


# ----------------------------------------------------------------------------- shared helpers
def local_linear(x, y, xq, h=10.0, iters=2):
    w_r = np.ones_like(y); out = None
    for it in range(iters):
        out = np.empty_like(xq, dtype=float)
        for j, x0 in enumerate(xq):
            u = np.abs(x - x0) / h; k = np.where(u < 1, (1 - u**3)**3, 0) * w_r
            if k.sum() < 1e-6: out[j] = np.nan; continue
            X = np.c_[np.ones_like(x), x - x0]; W = k
            b = np.linalg.lstsq(X * np.sqrt(W)[:, None], y * np.sqrt(W), rcond=None)[0]; out[j] = b[0]
        r = y - np.interp(x, xq, out); s = np.median(np.abs(r)) * 6 + 1e-9
        u = np.clip(r / s, -1, 1); w_r = (1 - u**2)**2
    return out


def _restart_after(ev, t, fallback):
    later = ev[ev.timestamp > t]
    return later.timestamp.min() if len(later) else fallback


def stable_mask(h_index, ev, tests=None):
    ok = pd.Series(True, index=h_index)
    for _, e in ev.iterrows():
        ok[(h_index > e.timestamp - pd.Timedelta('1h')) & (h_index < e.timestamp + pd.Timedelta('10h'))] = False
    for _, e in ev[ev.choke_opening_pct == 0].iterrows():
        rs = _restart_after(ev, e.timestamp, h_index[-1])
        ok[(h_index > e.timestamp - pd.Timedelta('1h')) & (h_index < rs + pd.Timedelta('36h'))] = False
    if tests is not None:
        for _, r in tests.iterrows():
            ok[(h_index >= r.test_start - pd.Timedelta('1h')) & (h_index < r.test_start + pd.Timedelta('2h'))] = False
            ok[(h_index >= r.test_end - pd.Timedelta('1h')) & (h_index < r.test_end + pd.Timedelta('8h'))] = False
    return ok


def fit_eta(g: pd.DataFrame, ev: pd.DataFrame, T_res: float) -> float:
    """Joule-Thomson coefficient (degF/psi): makes Pwf + dT/eta smoothest in time on stable hours."""
    g = g.set_index('timestamp')
    h = g[['dh_pressure_psia', 'dh_temperature_degf', 'choke_pct']].resample('1h').mean()
    m = stable_mask(h.index, ev)
    hh = h[m].dropna()
    t = (hh.index - T0).total_seconds().values / 86400
    dT = hh.dh_temperature_degf.values - T_res; p = hh.dh_pressure_psia.values
    best = None
    for eta in np.arange(0.0020, 0.0080, 0.00002):
        pr = p + dT / eta
        X = np.c_[np.ones_like(t), t, t**2]
        b = np.linalg.lstsq(X, pr, rcond=None)[0]; r = pr - X @ b
        s = np.median(np.abs(r))
        if best is None or s < best[1]: best = (eta, s)
    return float(best[0])


def minute_features(g: pd.DataFrame, ev: pd.DataFrame, tests_w, T_res: float, eta: float):
    """Minute-level drawdown for one well + daily smoothed reservoir pressure."""
    g = g.reset_index(drop=True)
    ts = g.timestamp; tday = ((ts - T0).dt.total_seconds() / 86400).values
    day0 = ts.min().normalize(); ndays = (ts.max().normalize() - day0).days + 1
    xq = (day0 - T0).days + np.arange(ndays) + 0.5
    days = pd.date_range(day0, periods=ndays, freq='D')
    h = g.set_index('timestamp')[['dh_pressure_psia', 'dh_temperature_degf']].resample('1h').mean()
    ok = stable_mask(h.index, ev, tests_w)
    prT = h.dh_pressure_psia + (h.dh_temperature_degf - T_res) / eta
    d = prT.where(ok).resample('1D').agg(['median', 'count'])
    d = d[d['count'] >= 6]
    xd = ((d.index - T0).total_seconds() / 86400 + 0.5).values
    prs = local_linear(xd, d['median'].values, xq, h=10.0)
    prs = pd.Series(prs).interpolate(limit_direction='both').values
    Pr_min = np.interp(tday, xq, prs)
    flowing = (g.choke_pct.values > 0)
    D = np.where(flowing, np.clip(Pr_min - g.dh_pressure_psia.values, 0, None), 0.0)
    mm = pd.DataFrame({'timestamp': ts, 'D': D, 'flowing': flowing, 'Pr': Pr_min, 'pwf': g.dh_pressure_psia.values,
                       'T': g.dh_temperature_degf.values})
    diag = dict(daily_points=int(len(d)), prT_resid_mad=float(np.median(np.abs(d['median'].values - np.interp(xd, xq, prs)))) if len(d) else np.nan)
    return mm, pd.Series(prs, index=days), diag


# ----------------------------------------------------------------------------- model families
def fit_oil(D, q, off):
    if off:
        W = 1 / q; X = np.c_[D, np.ones_like(D)]
        b = np.linalg.lstsq(X * W[:, None], q * W, rcond=None)[0]; return b[0], b[1] / b[0]
    x = D; J = np.sum(x / q) / np.sum(x**2 / q**2); return J, 0.0


def pred_oil(p, D): return p[0] * (D + p[1])


def fit_water(x, t, q, kind):
    W = 1 / q
    if kind == 'const': X = np.c_[x]
    elif kind == 'linear': X = np.c_[x, x * t]
    elif kind == 'exp':
        X = np.c_[np.ones_like(t), t]; y = np.log(q / x)
        return ('exp', np.linalg.lstsq(X, y, rcond=None)[0])
    return (kind, np.linalg.lstsq(X * W[:, None], q * W, rcond=None)[0])


def pred_water(p, x, t):
    k, b = p
    if k == 'const': return b[0] * x
    if k == 'linear': return (b[0] + b[1] * t) * x
    return np.exp(b[0] + b[1] * t) * x


def water_rate(p, x, t, qo, mode='team'):
    q_exp = pred_water((p['water_model'], np.array(p['water_coef'])), x, t)
    if mode == 'team': return q_exp
    q_wor = np.clip(np.polyval(p['wor_coef'], t), 0, None) * qo
    return 0.5 * (q_exp + q_wor)


# ----------------------------------------------------------------------------- training
def build_minute(clean, events, tests, T_res: dict, eta: dict, progress=None):
    minute, prs_daily, diag = {}, {}, {}
    wells = [w for w in clean.well_name.unique() if w in eta]
    for i, w in enumerate(wells):
        if progress: progress(f'Reservoir pressure from temperature: {w}', i / max(len(wells), 1))
        g = clean[clean.well_name == w]
        tw = tests[tests.well_name == w] if tests is not None else None
        minute[w], prs_daily[w], diag[w] = minute_features(g, events[events.well_name == w], tw, T_res[w], eta[w])
    return minute, prs_daily, diag


def test_features(wt, minute):
    rows = []
    for _, r in wt.iterrows():
        mm = minute.get(r.well_name)
        if mm is None: rows.append(dict(D=np.nan, td=np.nan)); continue
        s = mm[(mm.timestamp >= r.test_start) & (mm.timestamp < r.test_end)]
        rows.append(dict(D=s.D.mean(), td=((r.test_start + (r.test_end - r.test_start) / 2) - T0).total_seconds() / 86400))
    return pd.concat([wt.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


def train(clean, events, tests, pvt, completion, eta=None, water_mode='team', progress=None):
    """Fit the VFM from well tests. Returns (model dict, minute features, loo table)."""
    T_res = pvt['reservoir_temperature_degf'].to_dict()
    if eta is None:
        eta = {}
        wells = list(clean.well_name.unique())
        for i, w in enumerate(wells):
            if progress: progress(f'Joule-Thomson coefficient: {w}', i / len(wells))
            eta[w] = fit_eta(clean[clean.well_name == w], events[events.well_name == w], T_res[w])
    minute, prs_daily, diag = build_minute(clean, events, tests, T_res, eta, progress)
    F = test_features(tests, minute).dropna(subset=['D'])
    res = []; params = {}
    for w, g in F.groupby('well_name'):
        g = g.reset_index(drop=True); n = len(g)
        D = g.D.values; t = g.td.values; qo = g.oil_rate_stbd.values; qw = g.water_rate_stbd.values; qg = g.gas_rate_mscfd.values
        loo = {}
        for off in [False, True]:
            e = []
            for i in range(n):
                tr = np.arange(n) != i; p = fit_oil(D[tr], qo[tr], off); e.append(pred_oil(p, D[i:i+1])[0] / qo[i] - 1)
            loo[('oil', off)] = np.array(e)
        use_off = np.mean(np.abs(loo[('oil', True)])) < 0.75 * np.mean(np.abs(loo[('oil', False)]))
        po = fit_oil(D, qo, use_off)
        x = D + po[1]
        for kind in ['const', 'linear', 'exp']:
            e = []
            for i in range(n):
                tr = np.arange(n) != i; p = fit_water(x[tr], t[tr], qw[tr], kind); e.append(pred_water(p, x[i:i+1], t[i:i+1])[0] / qw[i] - 1)
            loo[('water', kind)] = np.array(e)
        Rs = completion.loc[w, 'solution_gor_at_pb_scf_stb'] / 1000
        for gk in ['Rs', 'test', 'blend']:
            e = []
            for i in range(n):
                tr = np.arange(n) != i
                pt = fit_oil(D[tr], qo[tr], use_off); qoi = pred_oil(pt, D[i:i+1])[0]
                gt = qg[tr].sum() / qo[tr].sum()
                G = {'Rs': Rs, 'test': gt, 'blend': 0.5 * (Rs + gt)}[gk]
                e.append(G * qoi / qg[i] - 1)
            loo[('gas', gk)] = np.array(e)
        params[w] = dict(use_offset=bool(use_off), J_o=float(po[0]), D_offset=float(po[1]), Rs=float(Rs), GOR_test=float(qg.sum() / qo.sum()))
        for k, v in loo.items(): res.append(dict(well=w, stream=k[0], variant=str(k[1]), mape=np.mean(np.abs(v)) * 100, errs=v))
    R = pd.DataFrame(res)
    summ = R.groupby(['stream', 'variant'])['errs'].apply(lambda s: np.mean(np.abs(np.concatenate(s.values))) * 100)
    wkind = summ.loc['water'].idxmin(); gkind = summ.loc['gas'].idxmin()
    for w, g in F.groupby('well_name'):
        p = params[w]; x = g.D.values + p['D_offset']
        k, b = fit_water(x, g.td.values, g.water_rate_stbd.values, wkind)
        p['water_model'] = k; p['water_coef'] = [float(v) for v in b]
        p['wor_coef'] = [float(v) for v in np.polyfit(g.td.values, g.water_rate_stbd.values / g.oil_rate_stbd.values, 1)]
        p['GOR_mscf_stb'] = float({'Rs': p['Rs'], 'test': p['GOR_test'], 'blend': 0.5 * (p['Rs'] + p['GOR_test'])}[gkind])
        p['eta_degF_per_psi'] = float(eta[w]); p['T_res_degF'] = float(T_res[w])
    lt = []
    for w in params:
        p = params[w]
        lt.append(dict(well_name=w,
                       LOO_oil_MAPE=float(R[(R.well == w) & (R.stream == 'oil') & (R.variant == str(p['use_offset']))].mape.values[0]),
                       LOO_water_MAPE=float(R[(R.well == w) & (R.stream == 'water') & (R.variant == wkind)].mape.values[0]),
                       LOO_gas_MAPE=float(R[(R.well == w) & (R.stream == 'gas') & (R.variant == gkind)].mape.values[0])))
    model = new_model_dict(params, wkind, gkind, water_mode, pvt, completion, tests, prs_daily, diag, pd.DataFrame(lt))
    return model, minute, prs_daily


def new_model_dict(params, wkind, gkind, water_mode, pvt, completion, tests, prs_daily, diag, loo_table):
    """Plain-python dict (no pandas objects) so the .pkl loads with any pandas/numpy version."""
    def clean_row(r): return {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else str(v)) for k, v in r.items()}
    return {
        'format': MODEL_FORMAT,
        'name': 'Physics-informed VFM (Joule-Thomson drawdown + inflow performance)',
        'created': _dt.datetime.now().isoformat(timespec='seconds'),
        'T0': str(T0.date()),
        'water_family': wkind, 'gas_model': gkind, 'water_mode': water_mode,
        'wells': {w: {**p, 'pvt': clean_row(pvt.loc[w].to_dict()), 'completion': clean_row(completion.loc[w].to_dict())} for w, p in params.items()},
        'training': {'n_tests': int(len(tests)), 'start': str(tests.test_start.min()), 'end': str(tests.test_end.max()),
                     'tests_per_well': {k: int(v) for k, v in tests.groupby('well_name').size().items()}},
        'loo_mape': {r['well_name']: {k: float(v) for k, v in r.items() if k != 'well_name'} for r in loo_table.to_dict('records')},
        'reservoir_pressure_daily': {w: {str(k.date()): float(v) for k, v in s.items()} for w, s in prs_daily.items()},
        'smoothing_diag': diag,
    }


# ----------------------------------------------------------------------------- prediction
def predict(model, minute, water_mode=None):
    """Minute -> daily rates with a trained model. Returns daily DataFrame."""
    water_mode = water_mode or model.get('water_mode', 'team')
    out = []
    for w, mm in minute.items():
        p = model['wells'][w]; tday = ((mm.timestamp - T0).dt.total_seconds() / 86400).values
        x = np.where(mm.flowing, np.clip(mm.D.values + p['D_offset'], 0, None), 0)
        qo = p['J_o'] * x
        qw = water_rate(p, x, tday, qo, water_mode)
        qg = p['GOR_mscf_stb'] * qo
        df = pd.DataFrame({'date': mm.timestamp.dt.date, 'oil': qo, 'water': qw, 'gas': qg, 'flow': mm.flowing.astype(float), 'Pr': mm.Pr, 'pwf': mm.pwf})
        d = df.groupby('date').mean().reset_index(); d['well_name'] = w
        out.append(d)
    P = pd.concat(out, ignore_index=True)
    P['date'] = pd.to_datetime(P['date'])
    P = P.rename(columns={'oil': 'oil_rate_stbd', 'water': 'water_rate_stbd', 'gas': 'gas_rate_mscfd', 'flow': 'producing_fraction_of_day',
                          'Pr': 'reservoir_pressure_psia', 'pwf': 'dh_pressure_psia'})
    return P[['date', 'well_name', 'oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd', 'producing_fraction_of_day',
              'reservoir_pressure_psia', 'dh_pressure_psia']]


def features_for_model(model, clean, events, tests=None, progress=None):
    """Drawdown features for new data using the trained eta / T_res stored in the model."""
    wells = [w for w in clean.well_name.unique() if w in model['wells']]
    eta = {w: model['wells'][w]['eta_degF_per_psi'] for w in wells}
    T_res = {w: model['wells'][w]['T_res_degF'] for w in wells}
    return build_minute(clean[clean.well_name.isin(wells)], events, tests, T_res, eta, progress)


def test_window_check(model, minute, tests, water_mode=None):
    """Predicted vs measured over each well-test window (for the parity plot)."""
    water_mode = water_mode or model.get('water_mode', 'team')
    val = []
    for _, r in tests.iterrows():
        w = r.well_name
        if w not in minute: continue
        p = model['wells'][w]; mm = minute[w]; s = mm[(mm.timestamp >= r.test_start) & (mm.timestamp < r.test_end)]
        if len(s) == 0: continue
        tday = ((s.timestamp - T0).dt.total_seconds() / 86400).values; x = np.clip(s.D.values + p['D_offset'], 0, None)
        qo_m = p['J_o'] * x
        qo = qo_m.mean(); qw = water_rate(p, x, tday, qo_m, water_mode).mean(); qg = p['GOR_mscf_stb'] * qo
        val.append(dict(well_name=w, test_start=r.test_start, test_end=r.test_end, oil_meas=r.oil_rate_stbd, oil_pred=qo,
                        water_meas=r.water_rate_stbd, water_pred=qw, gas_meas=r.gas_rate_mscfd, gas_pred=qg))
    V = pd.DataFrame(val)
    if len(V):
        for s in ['oil', 'water', 'gas']: V[s + '_err_pct'] = (V[s + '_pred'] / V[s + '_meas'] - 1) * 100
    return V


def cumulative_oil_before(model, well, start: pd.Timestamp, completion_cum=None) -> float:
    """Cum. oil at the start of the loaded data: completion-file cum at 1-Jan-2025 + model's daily VFM before that date."""
    base = completion_cum if completion_cum is not None else model['wells'][well]['completion'].get('cum_oil_at_2025_01_01_stb', 0.0)
    daily = model.get('training_daily_oil', {}).get(well, {})
    add = sum(v for d, v in daily.items() if pd.Timestamp(d) < start)
    return float(base) + float(add)
