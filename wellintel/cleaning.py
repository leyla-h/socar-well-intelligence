"""Step 1 - clean the raw per-minute data (same logic as the Phase 1 notebook, step 01).

- drop exact duplicate rows, sort by well/time
- -999.25 sentinel -> NaN, non-positive pressures -> NaN
- spike removal: |log(x / rolling_median_7min)| > threshold -> NaN
- reindex to a full 1-minute grid per well; gaps interpolated
- choke opening from choke events (step function, forward filled)
- fallback shut-in detector: gas-lift rate < 1 Mscf/d for >= 10 consecutive minutes
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from .io import HF_COLS

SPIKE_THR = {'whp_psia': 0.15, 'whp_downstream_psia': 0.15, 'dh_pressure_psia': 0.10, 'dh_temperature_degf': 0.03,
             'annulus_pressure_psia': 0.15, 'gas_lift_rate_mscfd': 0.25}


def detect_shutins(gl: pd.Series, min_len: int = 10):
    """Shut-in = gas-lift rate < 1 Mscf/d for >= min_len consecutive minutes.
    The gas-lift reading lags the choke by 1 minute (checked on every Jan-Sep shut-in), so shift back 1 min."""
    z = (gl < 1).astype(int)
    run = z.groupby((z != z.shift()).cumsum()).transform('size')
    m = (z == 1) & (run >= min_len)
    starts = gl.index[m & ~m.shift(1, fill_value=False)] - pd.Timedelta('1min')
    ends = gl.index[m & ~m.shift(-1, fill_value=False)]
    return list(zip(starts, ends))


def clean_hf(raw: pd.DataFrame, choke: pd.DataFrame | None, initial_choke: dict | None = None, progress=None):
    """Returns clean (long DataFrame), raw_grid {well: float32 array [n, 6]}, log DataFrame, events_used DataFrame, info dict."""
    initial_choke = initial_choke or {}
    n0 = len(raw)
    raw = raw.drop_duplicates().sort_values(['well_name', 'timestamp'])
    raw = raw.drop_duplicates(['well_name', 'timestamp'])
    info = {'raw_rows': int(n0), 'duplicates_removed': int(n0 - len(raw))}
    raw = raw.copy()
    raw[HF_COLS] = raw[HF_COLS].replace(-999.25, np.nan)
    if choke is None or len(choke) == 0:
        choke = pd.DataFrame({'timestamp': pd.Series(dtype='datetime64[ns]'), 'well_name': pd.Series(dtype=str),
                              'choke_opening_pct': pd.Series(dtype=float)})
    grid = pd.date_range(raw.timestamp.min().floor('D'), raw.timestamp.max().floor('D') + pd.Timedelta('1D') - pd.Timedelta('1min'), freq='1min')
    info['grid_start'] = str(grid[0]); info['grid_end'] = str(grid[-1]); info['days'] = int(len(grid) // 1440)
    out, stats, added, raw_grid = [], [], [], {}
    wells = list(raw.groupby('well_name'))
    for i, (w, g) in enumerate(wells):
        if progress: progress(f'Cleaning {w}', i / len(wells))
        g = g.set_index('timestamp')[HF_COLS].reindex(grid)
        raw_grid[w] = g[HF_COLS].to_numpy(dtype='float32', copy=True)
        st = {'well': w, 'missing_minutes': int(g[HF_COLS[0]].isna().sum())}
        for c in HF_COLS:
            x = g[c].astype(float)
            st[c + '_sentinel_or_missing'] = int(x.isna().sum())
            if c != 'gas_lift_rate_mscfd':
                x[x <= 0] = np.nan
            med = x.rolling(7, center=True, min_periods=3).median()
            valid = (x > 1) & (med > 1)
            lr = np.log(x.where(valid) / med.where(valid)).abs()
            bad = lr > SPIKE_THR[c]
            st[c + '_spikes'] = int(bad.sum())
            x[bad] = np.nan
            x = x.interpolate(limit_area='inside').ffill().bfill()
            g[c] = x.astype('float32')
        cw = choke[choke.well_name == w].set_index('timestamp')['choke_opening_pct'].sort_index()
        cw = cw[~cw.index.duplicated(keep='last')]
        ch = cw.reindex(grid, method='ffill') if len(cw) else pd.Series(np.nan, index=grid)
        if ch.isna().any():                         # before the first event: last known opening (from the model), else open
            ch = ch.fillna(initial_choke.get(w, 50.0))
        g['choke_pct'] = ch.astype('float32')
        for s, e in detect_shutins(g['gas_lift_rate_mscfd']):
            covered = (g.loc[s:e - pd.Timedelta('1min'), 'choke_pct'] == 0).mean()
            if covered < 0.5 and (e - s) >= pd.Timedelta('60min'):
                prev = g.loc[:s, 'choke_pct'].iloc[-2] if g.index.get_loc(s) > 0 else initial_choke.get(w, 50.0)
                g.loc[s:e - pd.Timedelta('1min'), 'choke_pct'] = 0.0
                added += [dict(timestamp=s, well_name=w, choke_opening_pct=0.0, source='detected (gas-lift = 0)'),
                          dict(timestamp=e, well_name=w, choke_opening_pct=float(prev), source='detected (gas-lift resumed)')]
        g['well_name'] = w
        out.append(g.rename_axis('timestamp').reset_index())
        stats.append(st)
    clean = pd.concat(out, ignore_index=True)
    ev = choke.copy(); ev['source'] = 'choke file'
    events_used = pd.concat([ev, pd.DataFrame(added)], ignore_index=True) if added else ev
    events_used = events_used[events_used.well_name.isin(raw_grid.keys())].sort_values(['well_name', 'timestamp']).reset_index(drop=True)
    info['shutins_detected_not_in_choke_file'] = len(added) // 2
    return clean, raw_grid, pd.DataFrame(stats), events_used, info


def clean_tests(wt: pd.DataFrame):
    """Well-test label fixes: sign flips and the GL-06 gas unit (Sm3/d -> Mscf/d)."""
    wt = wt.copy(); fix = []
    for col in ['water_rate_stbd', 'gas_rate_mscfd', 'total_gas_rate_mscfd', 'gas_lift_rate_mscfd', 'oil_rate_stbd']:
        if col not in wt: continue
        neg = wt[col] < 0
        for i in wt.index[neg]: fix.append((wt.well_name[i], str(wt.test_start[i]), col, 'sign flipped -> abs()'))
        wt[col] = wt[col].abs()
    m6 = wt.well_name == 'GL-06'
    if m6.any() and wt.loc[m6, 'gas_rate_mscfd'].median() > 2000:      # only if still in Sm3/d
        for i in wt.index[m6]: fix.append(('GL-06', str(wt.test_start[i]), 'gas_rate_mscfd,total_gas_rate_mscfd', 'Sm3/d -> Mscf/d (/28.3168)'))
        wt.loc[m6, 'gas_rate_mscfd'] /= 28.3168
        if 'total_gas_rate_mscfd' in wt: wt.loc[m6, 'total_gas_rate_mscfd'] /= 28.3168
    wt['liq'] = wt.oil_rate_stbd + wt.water_rate_stbd
    return wt, pd.DataFrame(fix, columns=['well', 'test_start', 'column', 'correction'])
