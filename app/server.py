"""Quyu - local web app. FastAPI backend serving the engine (wellintel) and the static UI."""
import io as _io
import math
import os
import shutil
import threading
import time
import traceback
import uuid
from typing import List, Optional
import numpy as np
import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from wellintel import io, vfm, pta, interpret, reports, __version__
from wellintel.workspace import Workspace, load_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, 'app', 'static')
DATA_DIR = os.path.join(ROOT, 'data')
MODEL_PATH = os.path.join(ROOT, 'models', 'vfm_model.pkl')
UPLOADS = os.path.join(ROOT, '.workspace', 'uploads')
os.makedirs(UPLOADS, exist_ok=True)
# QUYU_PUBLIC=1 when the app is reachable by other people: model uploads (.pkl = Python pickle, which can run code)
# and the server-side data folder are switched off. Set by the Dockerfile.
PUBLIC = os.environ.get('QUYU_PUBLIC', '0') == '1'

app = FastAPI(title='Quyu - well intelligence studio', version=__version__)
LOCK = threading.RLock()
STATE = {'ws': None, 'model_source': None}
JOB = {'running': False, 'stage': None, 'message': '', 'fraction': 0.0, 'log': [], 'error': None, 'started': None, 'finished': None, 'id': 0}
STAGES = ['read', 'clean', 'vfm', 'pta', 'regression']


# ----------------------------------------------------------------------------- helpers
def _num(x):
    if x is None: return None
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (pd.Timestamp,)): return x.isoformat()
    return x


def _arr(a, nd=4):
    a = np.asarray(a, dtype=float)
    return [None if not np.isfinite(v) else round(float(v), nd) for v in a]


def _clean_dict(d):
    if isinstance(d, dict): return {k: _clean_dict(v) for k, v in d.items()}
    if isinstance(d, (list, tuple)): return [_clean_dict(v) for v in d]
    return _num(d)


def ws() -> Workspace:
    if STATE['ws'] is None:
        model = load_model(MODEL_PATH) if os.path.exists(MODEL_PATH) else None
        STATE['ws'] = Workspace(model=model); STATE['model_source'] = 'models/vfm_model.pkl' if model else None
    return STATE['ws']


def need(stage):
    if stage not in ws().done:
        raise HTTPException(409, {'clean': 'Run the analysis first.', 'vfm': 'Run the analysis first.', 'pta': 'Run the analysis first.'}.get(stage, 'Not ready.'))


def model_summary(m):
    if not m: return None
    v = m.get('validation', {})
    return dict(name=m['name'], created=m['created'], source=STATE['model_source'], n_tests=m['training']['n_tests'],
                train_start=m['training']['start'][:10], train_end=m['training']['end'][:10], wells=sorted(m['wells'].keys()),
                water_mode=m.get('water_mode', 'team'), validation=_clean_dict(v),
                params=[_clean_dict(dict(well=w, J=p['J_o'], offset=p['D_offset'], eta=p['eta_degF_per_psi'], T_res=p['T_res_degF'],
                                         GOR=p['GOR_mscf_stb'] * 1000, water_b=p['water_coef'][1] if len(p['water_coef']) > 1 else None,
                                         loo=m.get('loo_mape', {}).get(w))) for w, p in sorted(m['wells'].items())],
                completion={w: _clean_dict(p['completion']) for w, p in m['wells'].items()})


# ----------------------------------------------------------------------------- state & files
@app.get('/api/model/pvt')
def model_pvt():
    w = ws()
    try:
        t = w.pvt_table()
    except Exception:
        return {}
    return {k: _clean_dict({c: r.get(c) for c in ['datum_tvd_ft', 'net_pay_thickness_ft', 'reservoir_temperature_degf', 'estimated_drainage_area_acres']})
            for k, r in t.to_dict('index').items()}


@app.get('/api/state')
def state():
    w = ws()
    files = [dict(id=os.path.basename(p), name=n, kind=k, label=io.KINDS[k]['label'], size=os.path.getsize(p) if os.path.exists(p) else 0)
             for k, fl in w.files.items() for n, p in fl]
    folder = sorted(f for f in os.listdir(DATA_DIR) if f.lower().endswith(('.csv', '.xlsx'))) if os.path.isdir(DATA_DIR) else []
    return dict(version=__version__, model=model_summary(w.model), files=files, data_folder=folder, done=sorted(w.done),
                wells=w.wells() if w.raw_grid else [], info=_clean_dict(w.info), messages=w.messages, water_mode=w.water_mode,
                job={k: v for k, v in JOB.items() if k != 'log'})


@app.post('/api/upload')
async def upload(files: List[UploadFile] = File(...)):
    out = []
    for f in files:
        fid = f'{uuid.uuid4().hex[:8]}_{os.path.basename(f.filename)}'
        path = os.path.join(UPLOADS, fid)
        with open(path, 'wb') as dst:
            shutil.copyfileobj(f.file, dst, length=8 * 1024 * 1024)
        if f.filename.lower().endswith('.pkl'):
            if PUBLIC:
                os.remove(path); out.append(dict(name=f.filename, kind=None, error='Model uploads are disabled on the public server; the built-in trained model is used.')); continue
            try:
                m = load_model(path)
            except Exception as ex:
                out.append(dict(name=f.filename, kind=None, error=str(ex))); continue
            with LOCK:
                w = ws(); w.model = m; w.water_mode = m.get('water_mode', 'team'); STATE['model_source'] = f.filename
                w.done.discard('vfm'); w.done.discard('pta'); w.done.discard('regression')
            out.append(dict(name=f.filename, kind='model', label='Trained VFM model')); continue
        kind = io.detect_kind(path)
        if kind is None:
            os.remove(path)
            out.append(dict(name=f.filename, kind=None, error='Columns not recognised. Expected one of: sensor data, well tests, choke events, PVT, completion.'))
            continue
        with LOCK:
            w = ws(); w.files.setdefault(kind, []).append((f.filename, path))
        df = io.load(path, kind)
        out.append(dict(id=fid, name=f.filename, kind=kind, label=io.KINDS[kind]['label'], **_clean_dict(io.summarize(df, kind))))
    return dict(files=out)


@app.post('/api/use-folder')
def use_folder():
    if PUBLIC: raise HTTPException(403, 'The data folder is not available on the public server. Upload the files instead.')
    added = []
    with LOCK:
        w = ws()
        known = {p for fl in w.files.values() for _, p in fl}
        for f in (sorted(os.listdir(DATA_DIR)) if os.path.isdir(DATA_DIR) else []):
            p = os.path.join(DATA_DIR, f)
            if p in known or not f.lower().endswith(('.csv', '.xlsx')): continue
            k = io.detect_kind(p)
            if k: w.files.setdefault(k, []).append((f, p)); added.append(dict(name=f, kind=k, label=io.KINDS[k]['label']))
    return dict(files=added)


@app.delete('/api/files/{fid}')
def remove_file(fid: str):
    with LOCK:
        w = ws()
        for k in list(w.files):
            w.files[k] = [(n, p) for n, p in w.files[k] if os.path.basename(p) != fid]
            if not w.files[k]: del w.files[k]
    return dict(ok=True)


@app.post('/api/reset')
def reset():
    with LOCK:
        w = ws(); w.files = {}; w.reset_results()
    return dict(ok=True)


# ----------------------------------------------------------------------------- pipeline job
def _progress(stage):
    def f(msg, frac=0.0):
        JOB['stage'] = stage; JOB['message'] = msg; JOB['fraction'] = float(frac)
    return f


def _log(msg):
    JOB['log'].append(dict(t=round(time.time() - JOB['started'], 1), msg=msg))


def _run(retrain: bool):
    w = ws()
    try:
        JOB.update(running=True, error=None, log=[], started=time.time(), finished=None, id=JOB['id'] + 1)
        with LOCK:
            w.reset_results()
            _progress('read')('Reading files'); w.read_inputs(_progress('read'))
            _log(f"Read {len(w.raw):,} sensor rows for {w.raw.well_name.nunique()} wells")
            w.run_cleaning(_progress('clean'))
            _log(f"Cleaned: {w.info['duplicates_removed']:,} duplicates removed, {int(w.clean_log.filter(like='_spikes').values.sum()):,} spikes removed, "
                 f"{w.info['days']} days on a 1-minute grid")
            for msg in w.messages: _log(msg)
            w.run_vfm(retrain=retrain, progress=_progress('vfm'))
            _log(('Model retrained on the uploaded well tests' if retrain else f"Trained model applied ({STATE['model_source']})")
                 + f" - daily rates for {w.daily.well_name.nunique()} wells")
            w.prepare_pta(_progress('pta'))
            ok = [e for e in w.events_pta if e['status'] == 'ok']
            _log(f"{len(ok)} shut-in(s) analysed" + (f", {len(w.events_pta) - len(ok)} skipped" if len(ok) < len(w.events_pta) else ''))
        _progress('regression')('Model cross-check', 0)
        w.run_regressions(_progress('regression'))
        _log('Regression cross-check finished')
        JOB['stage'] = 'done'; JOB['message'] = 'Analysis complete'; JOB['fraction'] = 1.0
    except Exception as ex:
        JOB['error'] = str(ex); JOB['stage'] = 'error'; _log('Error: ' + str(ex)); traceback.print_exc()
    finally:
        JOB['running'] = False; JOB['finished'] = time.time()


@app.post('/api/run')
def run(body: dict = Body(default={})):
    if JOB['running']: raise HTTPException(409, 'The analysis is already running.')
    if not ws().files.get('hf'): raise HTTPException(400, 'Add the high-frequency sensor file first.')
    if body.get('water_mode'): ws().water_mode = body['water_mode']
    threading.Thread(target=_run, args=(bool(body.get('retrain', False)),), daemon=True).start()
    return dict(ok=True)


@app.get('/api/job')
def job():
    return dict(JOB, stages=STAGES)


@app.post('/api/settings')
def settings(body: dict = Body(...)):
    need('vfm')
    with LOCK:
        if body.get('water_mode') in ('team', 'ensemble'): ws().set_water_mode(body['water_mode'])
    return dict(ok=True, water_mode=ws().water_mode)


# ----------------------------------------------------------------------------- field data
def _bucket(arr, i0, i1, n, how):
    seg = arr[i0:i1]
    L = len(seg); b = max(1, math.ceil(L / n)); nb = math.ceil(L / b)
    pad = np.full(nb * b, np.nan, dtype=float); pad[:L] = seg
    r = pad.reshape(nb, b)
    with np.errstate(all='ignore'):
        if how == 'min': return np.nanmin(r, 1), b
        if how == 'max': return np.nanmax(r, 1), b
        return np.nanmean(r, 1), b


@app.get('/api/series')
def series(well: str, t0: Optional[str] = None, t1: Optional[str] = None, n: int = 1400, raw: int = 0):
    need('clean'); w = ws()
    if well not in w.clean_arr: raise HTTPException(404, f'No sensor data for {well}.')
    A = w.clean_arr[well]; R = w.raw_grid[well]; N = len(A)
    i0 = 0 if not t0 else max(0, int((pd.Timestamp(t0) - w.grid0).total_seconds() // 60))
    i1 = N if not t1 else min(N, int((pd.Timestamp(t1) - w.grid0).total_seconds() // 60) + 1)
    if i1 - i0 < 10: i0, i1 = max(0, i0 - 30), min(N, i1 + 30)
    out = {}
    for j, c in enumerate(io.HF_COLS):
        mean, b = _bucket(A[:, j], i0, i1, n, 'mean'); lo, _ = _bucket(A[:, j], i0, i1, n, 'min'); hi, _ = _bucket(A[:, j], i0, i1, n, 'max')
        d = dict(mean=_arr(mean, 3), lo=_arr(lo, 3), hi=_arr(hi, 3))
        if raw:
            rlo, _ = _bucket(R[:, j], i0, i1, n, 'min'); rhi, _ = _bucket(R[:, j], i0, i1, n, 'max')
            d.update(raw_lo=_arr(rlo, 3), raw_hi=_arr(rhi, 3))
        out[c] = d
    ch, b = _bucket(A[:, 6], i0, i1, n, 'min')
    out['choke_pct'] = dict(mean=_arr(ch, 2))
    start = w.grid0 + pd.Timedelta(minutes=i0)
    ev = w.events[w.events.well_name == well]
    shut = pta.shutin_events(ev, {well: w.clean.timestamp.max()}) if len(ev) else pd.DataFrame()
    tests = w.tests[w.tests.well_name == well] if w.tests is not None else pd.DataFrame()
    return dict(well=well, start=start.isoformat(), step_min=b, n=len(out['choke_pct']['mean']), channels=out,
                full_start=w.grid0.isoformat(), full_end=w.clean.timestamp.max().isoformat(),
                shutins=[dict(start=r.shut_in_start.isoformat(), end=r.shut_in_end.isoformat(), source=r.source) for r in shut.itertuples()],
                choke_events=[dict(t=r.timestamp.isoformat(), pct=_num(r.choke_opening_pct), source=r.source) for r in ev.itertuples()],
                tests=[dict(start=r.test_start.isoformat(), end=r.test_end.isoformat()) for r in tests.itertuples()])


@app.get('/api/quality')
def quality():
    need('clean'); w = ws()
    L = w.clean_log.copy()
    rows = []
    for r in L.to_dict('records'):
        rows.append(dict(well=r['well'], missing=r['missing_minutes'],
                         sentinels={c: r[c + '_sentinel_or_missing'] for c in io.HF_COLS}, spikes={c: r[c + '_spikes'] for c in io.HF_COLS}))
    return _clean_dict(dict(info=w.info, wells=rows, label_fixes=(w.label_fixes.to_dict('records') if w.label_fixes is not None else []),
                            minutes=len(w.clean_arr[next(iter(w.clean_arr))]) if w.clean_arr else 0))


# ----------------------------------------------------------------------------- VFM
@app.get('/api/vfm/field')
def vfm_field():
    need('vfm'); w = ws(); P = w.daily
    fld = P.groupby('date')[['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']].sum()
    wells = []
    for well, d in P.groupby('well_name'):
        S = interpret.well_summary(d, (w.prs_daily or {}).get(well), w.model['wells'][well])
        spark = d.oil_rate_stbd.values
        wells.append(dict(well=well, **S, spark=_arr(spark[:: max(1, len(spark) // 60)], 1)))
    V = w.validation
    parity = V.to_dict('records') if V is not None and len(V) else []
    mape = {s: float(V[s + '_err_pct'].abs().mean()) for s in ['oil', 'water', 'gas']} if V is not None and len(V) else None
    return _clean_dict(dict(dates=[d.strftime('%Y-%m-%d') for d in fld.index], oil=_arr(fld.oil_rate_stbd, 1), water=_arr(fld.water_rate_stbd, 1),
                            gas=_arr(fld.gas_rate_mscfd, 1), wells=wells, parity=parity, test_mape=mape, water_mode=w.water_mode,
                            totals=dict(oil=float(P.oil_rate_stbd.sum()), water=float(P.water_rate_stbd.sum()), gas=float(P.gas_rate_mscfd.sum()))))


@app.get('/api/vfm/well')
def vfm_well(well: str):
    need('vfm'); w = ws(); d = w.daily[w.daily.well_name == well]
    if not len(d): raise HTTPException(404, f'No predictions for {well}.')
    p = w.model['wells'][well]; prs = (w.prs_daily or {}).get(well)
    S = interpret.well_summary(d, prs, p)
    V = w.validation[w.validation.well_name == well] if w.validation is not None and len(w.validation) else pd.DataFrame()
    return _clean_dict(dict(well=well, dates=[x.strftime('%Y-%m-%d') for x in d.date], oil=_arr(d.oil_rate_stbd, 2), water=_arr(d.water_rate_stbd, 2),
                            gas=_arr(d.gas_rate_mscfd, 2), producing=_arr(d.producing_fraction_of_day, 3), pr=_arr(d.reservoir_pressure_psia, 1),
                            pwf=_arr(d.dh_pressure_psia, 1), tests=V.to_dict('records'), params=p, summary=S,
                            findings=interpret.well_findings(S, p)))


@app.get('/api/vfm/explain')
def vfm_explain(well: str, date: str):
    """The calculation chain behind one day's prediction, with the well's own numbers."""
    need('vfm'); w = ws(); mm = w.minute[well]; p = w.model['wells'][well]
    day = pd.Timestamp(date); s = mm[(mm.timestamp >= day) & (mm.timestamp < day + pd.Timedelta('1D'))]
    if not len(s): raise HTTPException(404, 'No data on that day.')
    fl = s[s.flowing]
    T = float(fl['T'].mean()) if len(fl) else float('nan'); pwf = float(fl.pwf.mean()) if len(fl) else float('nan')
    Pr = float(s.Pr.mean()); D = float(fl.D.mean()) if len(fl) else 0.0
    tday = (day + pd.Timedelta('12h') - vfm.T0).total_seconds() / 86400
    row = w.daily[(w.daily.well_name == well) & (w.daily.date == day)].iloc[0]
    return _clean_dict(dict(well=well, date=date, T=T, T_res=p['T_res_degF'], dT=T - p['T_res_degF'], eta=p['eta_degF_per_psi'],
                            pwf=pwf, Pr=Pr, D=D, offset=p['D_offset'], J=p['J_o'], producing=float(s.flowing.mean()),
                            oil=float(row.oil_rate_stbd), water=float(row.water_rate_stbd), gas=float(row.gas_rate_mscfd), GOR=p['GOR_mscf_stb'] * 1000,
                            water_factor=float(np.exp(p['water_coef'][0] + p['water_coef'][1] * tday)) if p['water_model'] == 'exp' else None,
                            water_mode=w.water_mode))


# ----------------------------------------------------------------------------- PTA
def _event_head(rec):
    w = ws(); d = dict(rec)
    if rec['status'] == 'ok':
        C = w.pta_cache[rec['event_id']]; H = C['H']; R = C['R'] if (C['R'] and 'k' in C['R']) else H
        d.update(k=R['k'], skin=R['skin'], m=R['m'], dps=R['dps'], q=H['q'], manual=C.get('manual', False), regression=C['R'] is not None,
                 spark=_arr(C['E']['p'][:: max(1, len(C['E']['p']) // 50)], 1))
    return _clean_dict(d)


@app.get('/api/pta/events')
def pta_events():
    need('pta'); return dict(events=[_event_head(e) for e in ws().events_pta])


def _event_payload(eid):
    w = ws(); C = w.pta_cache.get(eid)
    if C is None: raise HTTPException(404, 'Unknown or skipped shut-in.')
    E, Dg, H, R, A = C['E'], C['Dg'], C['H'], C['R'], C['auto']
    well = E['well_name']; s, rs = E['shut_in_start'], E['shut_in_end']
    g = w.clean_arr[well]; i0 = int((s - pd.Timedelta('3D') - w.grid0).total_seconds() // 60); i1 = int((rs + pd.Timedelta('2D') - w.grid0).total_seconds() // 60)
    i0 = max(i0, 0); i1 = min(i1, len(g))
    hp, b = _bucket(g[:, 2], i0, i1, 900, 'mean')
    pw = w.daily[(w.daily.well_name == well) & (w.daily.date >= (s - pd.Timedelta('3D')).normalize()) & (w.daily.date <= (rs + pd.Timedelta('2D')).normalize())]
    model = None
    if R and 'k' in R:
        idx = np.unique(np.round(np.geomspace(1, len(E['dt']), 220)).astype(int) - 1)
        Esub = dict(E, dt=E['dt'][idx])
        model = dict(dt=_arr(E['dt'][idx], 5), p=_arr(pta.model_curve(Esub, R), 3))
    findings = interpret.event_findings(C, w.model['wells'][well], (w.prs_daily or {}).get(well))
    return _clean_dict(dict(event_id=eid, well=well, start=s.isoformat(), end=rs.isoformat(), source=next((e['source'] for e in w.events_pta if e['event_id'] == eid), ''),
                            dt=_arr(E['dt'], 5), p=_arr(E['p'], 3), pwf=E['pwf'], tp=H['tp'], q=E['q'], qday=str(E['qday'].date()), Np=E['Np'], pv=E['pv'],
                            tb=_arr(Dg['tb'], 5), dp_b=_arr(Dg['yb'] - E['pwf'], 3), der=_arr(Dg['der'], 4),
                            history=dict(start=(w.grid0 + pd.Timedelta(minutes=i0)).isoformat(), step_min=b, p=_arr(hp, 2),
                                         dates=[x.strftime('%Y-%m-%d') for x in pw.date], oil=_arr(pw.oil_rate_stbd, 1)),
                            H=H, auto=A, manual=C.get('manual', False), R=R, model=model, findings=findings))


@app.get('/api/pta/event/{eid}')
def pta_event(eid: str):
    need('pta'); return _event_payload(eid)


@app.post('/api/pta/event/{eid}/window')
def pta_window(eid: str, body: dict = Body(...)):
    """Engineer override of the radial-flow window (hours). body: {t1, t2} or {reset: true}. Optional q / pv overrides."""
    need('pta'); w = ws(); C = w.pta_cache.get(eid)
    if C is None: raise HTTPException(404, 'Unknown shut-in.')
    with LOCK:
        if body.get('reset'):
            C['H'] = pta.horner(C['E'], C['auto']['t1'], C['auto']['t2']); C['manual'] = False
        else:
            try:
                C['H'] = pta.horner(C['E'], float(body['t1']), float(body['t2'])); C['manual'] = True
            except ValueError as ex:
                raise HTTPException(400, str(ex))
    return _event_payload(eid)


@app.get('/api/pta/plot/{eid}.png')
def pta_plot(eid: str):
    need('pta'); w = ws()
    if eid not in w.pta_cache: raise HTTPException(404, 'Unknown shut-in.')
    return Response(reports.fig_png(reports.pta_figure(w, eid), 110), media_type='image/png',
                    headers={'Content-Disposition': f'attachment; filename="{eid}_buildup.png"'})


@app.get('/api/reservoir')
def reservoir():
    need('pta'); w = ws(); T = w.pta_table()
    rows = []
    for r in T.to_dict('records'):
        pv = w.pta_cache[r['event_id']]['E']['pv']; J = w.model['wells'][r['well_name']]['J_o']
        re = math.sqrt(pv['area_acres'] * 43560 / math.pi) if np.isfinite(pv['area_acres']) else float('nan')
        Jpss = r['permeability_md'] * pv['h'] / (141.2 * pv['B'] * pv['mu'] * (math.log(re / pv['rw']) - 0.75 + r['skin'])) if np.isfinite(re) else float('nan')
        rows.append(dict(r, J_vfm=J, J_pss=Jpss, re_ft=re, kh=r['permeability_md'] * pv['h']))
    prs = {k: dict(dates=[d.strftime('%Y-%m-%d') for d in s.index], pr=_arr(s.values, 1)) for k, s in (w.prs_daily or {}).items()}
    return _clean_dict(dict(events=rows, pressure=prs))


# ----------------------------------------------------------------------------- exports
EXPORTS = {
    'phase1.csv':  ('Phase1_VFM_predictions.csv', 'text/csv'),
    'phase1.xlsx': ('Phase1_VFM_predictions.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    'phase2.csv':  ('Phase2_PTA_results.csv', 'text/csv'),
    'phase2.xlsx': ('Phase2_PTA_results.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    'plots.zip':   ('PTA_and_VFM_plots.zip', 'application/zip'),
    'report.pdf':  ('Well_performance_report.pdf', 'application/pdf'),
    'model.pkl':   ('vfm_model.pkl', 'application/octet-stream'),
    'all.zip':     ('Quyu_results.zip', 'application/zip'),
}


@app.get('/api/export/{kind}')
def export(kind: str):
    if kind not in EXPORTS: raise HTTPException(404, 'Unknown export.')
    w = ws(); fname, mt = EXPORTS[kind]
    if kind == 'model.pkl':
        import pickle
        data = pickle.dumps(w.model, protocol=4)
    else:
        need('pta')
        with LOCK:
            if kind == 'phase1.csv':
                p1 = w.phase1_table().copy(); p1['date'] = p1.date.dt.strftime('%Y-%m-%d'); data = p1.to_csv(index=False).encode()
            elif kind == 'phase1.xlsx': data = reports.phase1_excel(w)
            elif kind == 'phase2.csv': data = w.phase2_csv_table().to_csv(index=False).encode()
            elif kind == 'phase2.xlsx': data = reports.phase2_excel(w)
            elif kind == 'plots.zip': data = reports.plots_zip(w)
            elif kind == 'report.pdf': data = reports.pdf_report(w)
            else: data = reports.everything_zip(w, MODEL_PATH if STATE['model_source'] == 'models/vfm_model.pkl' else None)
    return Response(data, media_type=mt, headers={'Content-Disposition': f'attachment; filename="{fname}"'})


# ----------------------------------------------------------------------------- static UI
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@app.get('/')
def index():
    return FileResponse(os.path.join(STATIC, 'index.html'), headers={'Cache-Control': 'no-store'})
