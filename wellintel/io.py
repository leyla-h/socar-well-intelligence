"""Reading and recognising the organiser's files (CSV or Excel), whatever they are named."""
from __future__ import annotations
import os
import pandas as pd

KINDS = {
    'hf':         {'label': 'High-frequency sensor data', 'need': {'timestamp', 'well_name', 'dh_pressure_psia', 'dh_temperature_degf'}},
    'tests':      {'label': 'Well tests',                 'need': {'well_name', 'test_start', 'test_end', 'oil_rate_stbd'}},
    'choke':      {'label': 'Choke events',               'need': {'timestamp', 'well_name', 'choke_opening_pct'}},
    'pvt':        {'label': 'Reservoir & PVT',            'need': {'well_name', 'net_pay_thickness_ft', 'porosity_frac', 'oil_viscosity_cp'}},
    'completion': {'label': 'Well completion',            'need': {'well_name', 'gauge_tvd_ft', 'cum_oil_at_2025_01_01_stb'}},
}
HF_COLS = ['whp_psia', 'whp_downstream_psia', 'dh_pressure_psia', 'dh_temperature_degf', 'annulus_pressure_psia', 'gas_lift_rate_mscfd']


def _read(path: str, nrows: int | None = None) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm', '.xls'):
        return pd.read_excel(path, nrows=nrows)
    return pd.read_csv(path, nrows=nrows)


def detect_kind(path: str) -> str | None:
    """Return which dataset a file is, from its column names (file name is ignored)."""
    try:
        cols = {str(c).strip() for c in _read(path, nrows=5).columns}
    except Exception:
        return None
    for kind in ['hf', 'tests', 'choke', 'pvt', 'completion']:     # hf before choke: both have timestamp+well_name
        if KINDS[kind]['need'] <= cols:
            return kind
    return None


def load(path: str, kind: str) -> pd.DataFrame:
    df = _read(path)
    df.columns = [str(c).strip() for c in df.columns]
    if 'well_name' in df.columns:
        df['well_name'] = df['well_name'].astype(str).str.strip()
    if kind in ('hf', 'choke'):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    if kind == 'tests':
        df['test_start'] = pd.to_datetime(df['test_start']); df['test_end'] = pd.to_datetime(df['test_end'])
    return df


def summarize(df: pd.DataFrame, kind: str) -> dict:
    s = {'rows': int(len(df)), 'wells': sorted(df['well_name'].unique().tolist()) if 'well_name' in df else []}
    tcol = {'hf': 'timestamp', 'choke': 'timestamp', 'tests': 'test_start'}.get(kind)
    if tcol:
        s['start'] = str(df[tcol].min()); s['end'] = str(df[tcol].max())
    return s
