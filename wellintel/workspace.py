"""One analysis session: loaded files -> cleaned data -> VFM rates -> build-up analyses."""
from __future__ import annotations
import pickle
import numpy as np
import pandas as pd
from . import io, cleaning, vfm, pta


def load_model(path):
    with open(path, 'rb') as f:
        m = pickle.load(f)
    if not isinstance(m, dict) or m.get('format') != vfm.MODEL_FORMAT:
        raise ValueError('This file is not a Quyu VFM model (.pkl).')
    return m


def save_model(model, path):
    with open(path, 'wb') as f:
        pickle.dump(model, f, protocol=4)


class Workspace:
    def __init__(self, model: dict | None = None):
        self.model = model
        self.files: dict[str, list] = {}          # kind -> [(name, path)]
        self.reset_results()

    def reset_results(self):
        self.raw = self.choke = self.tests = self.pvt = self.completion = None
        self.clean = self.raw_grid = self.clean_log = self.events = self.label_fixes = None
        self.clean_arr = {}
        self.grid0 = None; self.info = {}
        self.minute = self.prs_daily = self.daily = self.validation = None
        self.events_pta = []; self.pta_cache = {}; self.messages = []
        self.water_mode = (self.model or {}).get('water_mode', 'team')
        self.done = set()

    # ------------------------------------------------------------------ inputs
    def wells(self):
        return sorted(self.raw_grid.keys()) if self.raw_grid else sorted((self.model or {}).get('wells', {}).keys())

    def pvt_table(self):
        if self.pvt is not None: return self.pvt
        return pd.DataFrame({w: p['pvt'] for w, p in self.model['wells'].items()}).T.rename_axis('well_name')

    def completion_table(self):
        if self.completion is not None: return self.completion
        return pd.DataFrame({w: p['completion'] for w, p in self.model['wells'].items()}).T.rename_axis('well_name')

    def read_inputs(self, progress=None):
        def cat(kind):
            fl = self.files.get(kind, [])
            if not fl: return None
            return pd.concat([io.load(p, kind) for _, p in fl], ignore_index=True)
        if progress: progress('Reading files', 0)
        self.raw = cat('hf')
        if self.raw is None: raise ValueError('Add the high-frequency sensor file - it is the one input the analysis cannot run without.')
        for c in io.HF_COLS:
            if c not in self.raw: self.raw[c] = np.nan
        self.choke = cat('choke')
        t = cat('tests')
        self.tests, self.label_fixes = cleaning.clean_tests(t) if t is not None else (None, None)
        p = cat('pvt'); self.pvt = p.drop_duplicates('well_name', keep='last').set_index('well_name') if p is not None else None
        c = cat('completion'); self.completion = c.drop_duplicates('well_name', keep='last').set_index('well_name') if c is not None else None
        if self.model is None and (self.tests is None or self.pvt is None or self.completion is None):
            raise ValueError('No trained model is loaded, so well tests, PVT and completion files are all needed to train one.')
        unknown = sorted(set(self.raw.well_name) - set((self.model or {}).get('wells', {}).keys())) if self.model else []
        if unknown:
            self.messages.append(f'No trained parameters for {", ".join(unknown)} - these wells are shown but not predicted.')

    # ------------------------------------------------------------------ pipeline
    def run_cleaning(self, progress=None):
        init = {w: p.get('last_choke_pct', 50.0) for w, p in (self.model or {}).get('wells', {}).items()}
        self.clean, self.raw_grid, self.clean_log, self.events, self.info = cleaning.clean_hf(self.raw, self.choke, init, progress)
        self.grid0 = pd.Timestamp(self.info['grid_start'])
        self.clean_arr = {w: g[io.HF_COLS + ['choke_pct']].to_numpy(dtype='float32') for w, g in self.clean.groupby('well_name')}
        if self.info['shutins_detected_not_in_choke_file']:
            self.messages.append(f"{self.info['shutins_detected_not_in_choke_file']} shut-in(s) found in the sensor data that the choke file does not list - added automatically.")
        self.done.add('clean')

    def run_vfm(self, retrain=False, progress=None):
        if retrain or self.model is None:
            pvt, comp = self.pvt_table(), self.completion_table()
            model, self.minute, self.prs_daily = vfm.train(self.clean, self.events, self.tests, pvt, comp, None, self.water_mode, progress)
            daily = vfm.predict(model, self.minute, self.water_mode)
            model['training_daily_oil'] = {w: {str(d.date()): float(v) for d, v in zip(g.date, g.oil_rate_stbd)} for w, g in daily.groupby('well_name')}
            model['training_end'] = str(self.clean.timestamp.max())
            for w in model['wells']:
                last = self.events[self.events.well_name == w]
                model['wells'][w]['last_choke_pct'] = float(last.choke_opening_pct.iloc[-1]) if len(last) else 50.0
            if self.model is not None and 'validation' in self.model: model['validation'] = self.model['validation']
            self.model = model
        else:
            self.minute, self.prs_daily, _ = vfm.features_for_model(self.model, self.clean, self.events, self.tests, progress)
        if progress: progress('Daily rates', 0.95)
        self.daily = vfm.predict(self.model, self.minute, self.water_mode)
        self.validation = vfm.test_window_check(self.model, self.minute, self.tests, self.water_mode) if self.tests is not None else None
        self.done.add('vfm')

    def set_water_mode(self, mode):
        self.water_mode = mode
        if self.minute is not None:
            self.daily = vfm.predict(self.model, self.minute, mode)
            if self.tests is not None: self.validation = vfm.test_window_check(self.model, self.minute, self.tests, mode)
            # water does not enter the build-up analysis (single-phase oil), so Phase 2 is unchanged

    def prepare_pta(self, progress=None, with_regression=True):
        data_end = {w: self.clean.timestamp.max() for w in self.clean.well_name.unique()}
        ev = pta.shutin_events(self.events, data_end)
        self.events_pta = []
        pvt = self.pvt_table(); comp = self.completion_table()
        for i, e in ev.iterrows():
            w, s, rs = e.well_name, e.shut_in_start, e.shut_in_end
            eid = f'{w}_{s:%Y%m%d}'
            rec = dict(event_id=eid, well_name=w, shut_in_start=s, shut_in_end=rs, source=e.source,
                       duration_h=(rs - s).total_seconds() / 3600)
            if progress: progress(f'Build-up {eid}', i / max(len(ev), 1))
            try:
                if (rs - s) < pd.Timedelta('2h'): raise ValueError('shut-in shorter than 2 hours')
                if w not in self.model['wells']: raise ValueError('no VFM rate for this well')
                g = self.clean[self.clean.well_name == w].set_index('timestamp')
                pw = self.daily[self.daily.well_name == w].set_index('date')
                cum0 = vfm.cumulative_oil_before(self.model, w, self.grid0, float(comp.loc[w, 'cum_oil_at_2025_01_01_stb']))
                E = pta.prepare_event(w, s, rs, g, pw, pvt.loc[w], cum0)
                Dg = pta.diagnostics(E)
                t1, t2, thump, cv = pta.auto_mtr(Dg)
                H = pta.horner(E, t1, t2)
                self.pta_cache[eid] = dict(E=E, Dg=Dg, auto=dict(t1=t1, t2=t2, thump=thump, cv=cv), H=H, R=None)
                rec.update(status='ok')
            except Exception as ex:
                rec.update(status='skipped', reason=str(ex))
            self.events_pta.append(rec)
        self.done.add('pta')

    def run_regressions(self, progress=None):
        ids = list(self.pta_cache)
        for i, eid in enumerate(ids):
            if progress: progress(f'Regression check {eid}', i / max(len(ids), 1))
            C = self.pta_cache[eid]
            try:
                C['R'] = pta.regression(C['E'], C['H']['k'], C['H']['skin'])
            except Exception as ex:
                C['R'] = dict(error=str(ex))
        self.done.add('regression')

    def pta_table(self):
        rows = []
        for rec in self.events_pta:
            if rec['status'] != 'ok': continue
            C = self.pta_cache[rec['event_id']]; E, H, R = C['E'], C['H'], C['R'] or {}
            rows.append(dict(event_id=rec['event_id'], well_name=rec['well_name'], shut_in_start=rec['shut_in_start'], shut_in_end=rec['shut_in_end'],
                             duration_h=rec['duration_h'], q_oil_last_day_date=E['qday'].date(), q_oil_stbd=H['q'], Np_stb=E['Np'], tp_h=H['tp'],
                             pwf_at_shutin_psia=E['pwf'], mtr_start_h=H['t1'], mtr_end_h=H['t2'], horner_plot_slope=H['m'], horner_r2=H['r2'],
                             p_star_psia=H['p_star'], p1hr_psia=H['p1hr'], permeability_md=H['k'], skin=H['skin'], delta_p_skin_psi=H['dps'],
                             mdh_slope_psi_cycle=H['mdh_slope'], radius_investigation_ft=H['rinv'], PI_stbd_psi=H['PI'], flow_efficiency=H['FE'],
                             h_ft=E['pv']['h'], phi=E['pv']['phi'], ct_1psi=E['pv']['ct'], rw_ft=E['pv']['rw'], Bo=E['pv']['B'], mu_cp=E['pv']['mu'],
                             reg_boundary=R.get('boundary'), reg_k_md=R.get('k'), reg_skin=R.get('skin'), reg_C_bbl_psi=R.get('C'), reg_re_ft=R.get('re'),
                             reg_rms_psi=R.get('rms'), reg_slope=R.get('m'), reg_dps=R.get('dps')))
            ok = 'k' in R
            rows[-1].update(reported_source='model regression' if ok else 'Horner straight line',
                            reported_slope=R['m'] if ok else H['m'], reported_k_md=R['k'] if ok else H['k'],
                            reported_skin=R['skin'] if ok else H['skin'], reported_dps=R['dps'] if ok else H['dps'])
        return pd.DataFrame(rows)

    def phase1_table(self):
        P = self.daily[['date', 'well_name', 'oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']].copy()
        P[['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']] = P[['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']].round(2)
        return P

    def phase2_csv_table(self):
        """Submission table. Reported values come from the model regression (fitted to every build-up point);
        the Horner straight line is used only where the regression is not available."""
        T = self.pta_table()
        cols = ['well_name', 'shut_in_start', 'horner_plot_slope', 'permeability_md', 'skin', 'delta_p_skin_psi']
        if not len(T): return pd.DataFrame(columns=cols)
        s2 = T[['well_name', 'shut_in_start', 'reported_slope', 'reported_k_md', 'reported_skin', 'reported_dps']].copy()
        s2.columns = cols
        return s2.round({'horner_plot_slope': 3, 'permeability_md': 2, 'skin': 3, 'delta_p_skin_psi': 2})
