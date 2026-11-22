"""Train the VFM on the organiser's Jan-Sep data and save models/vfm_model.pkl.

    python scripts/train_model.py            # reads data/*.csv
"""
import os, sys, glob, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from wellintel import io
from wellintel.workspace import Workspace, save_model

# Out-of-time validation from notebook 05 (train before a cut-off, score the later well tests; 4 cut-offs).
WALK_FORWARD = {'oil': 2.06, 'water': 6.07, 'gas': 5.91, 'cutoffs': ['2025-05-01', '2025-06-01', '2025-07-01', '2025-08-01']}


def main(data_dir=os.path.join(ROOT, 'data'), out=os.path.join(ROOT, 'models', 'vfm_model.pkl')):
    ws = Workspace(model=None)
    for p in sorted(glob.glob(os.path.join(data_dir, '*'))):
        k = io.detect_kind(p)
        if k: ws.files.setdefault(k, []).append((os.path.basename(p), p))
    print({k: [n for n, _ in v] for k, v in ws.files.items()})
    t = time.time()
    log = lambda msg, f: None
    ws.read_inputs(log); ws.run_cleaning(log); ws.run_vfm(retrain=True, progress=log)
    V = ws.validation
    ws.model['validation'] = {'insample_mape': {s: float(V[s + '_err_pct'].abs().mean()) for s in ['oil', 'water', 'gas']},
                              'loo_mape': {s: float(sum(r[f'LOO_{s}_MAPE'] for r in ws.model['loo_mape'].values()) / len(ws.model['loo_mape'])) for s in ['oil', 'water', 'gas']},
                              'walk_forward_mape': WALK_FORWARD}
    save_model(ws.model, out)
    print('saved', out, f'in {time.time() - t:.1f}s')
    return ws


if __name__ == '__main__':
    main()
