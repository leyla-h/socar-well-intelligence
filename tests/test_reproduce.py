"""The app's engine, loading models/vfm_model.pkl, must reproduce the submitted result files exactly.

    python -m pytest tests -q        (or:  python tests/test_reproduce.py)
Needs the organiser's CSVs in data/.
"""
import os, sys, glob, io as _io
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import pandas as pd
from wellintel import io
from wellintel.workspace import Workspace, load_model

DATA = os.path.join(ROOT, 'data')


def _run():
    ws = Workspace(model=load_model(os.path.join(ROOT, 'models', 'vfm_model.pkl')))
    for p in sorted(glob.glob(os.path.join(DATA, '*'))):
        k = io.detect_kind(p)
        if k: ws.files.setdefault(k, []).append((os.path.basename(p), p))
    say = lambda msg, f=0: None
    ws.read_inputs(say); ws.run_cleaning(say); ws.run_vfm(progress=say); ws.prepare_pta(say); ws.run_regressions(say)
    return ws


def test_reproduces_submitted_results():
    if not glob.glob(os.path.join(DATA, '*.csv')):
        import pytest; pytest.skip('put the organiser CSVs in data/ to run this test')
    ws = _run()
    p1 = ws.phase1_table().copy(); p1['date'] = p1.date.dt.strftime('%Y-%m-%d')
    ref1 = os.path.join(ROOT, 'results', 'Phase1_VFM_predictions.csv')
    if p1.to_csv(index=False) != open(ref1).read():
        b = pd.read_csv(ref1); cols = ['oil_rate_stbd', 'water_rate_stbd', 'gas_rate_mscfd']
        diff = (p1[cols].reset_index(drop=True) - b[cols]).abs().max().max()
        raise AssertionError(f'Phase 1 differs from results/ by up to {diff:.3f} (pandas {pd.__version__}). '
                             'Install the versions in requirements.txt (pandas < 3.1) for a byte-identical result.')
    assert ws.phase2_csv_table().to_csv(index=False) == open(os.path.join(ROOT, 'results', 'Phase2_PTA_results.csv')).read(), 'Phase 2 differs'


if __name__ == '__main__':
    test_reproduces_submitted_results(); print('OK - Phase 1 and Phase 2 results reproduced exactly')
