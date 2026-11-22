"""Run the trained model on data/ and write the Excel workbooks and the PDF report into results/.

    python scripts/export_results.py
"""
import os, sys, glob, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from wellintel import io, reports
from wellintel.workspace import Workspace, load_model


def main(data_dir=os.path.join(ROOT, 'data'), out=os.path.join(ROOT, 'results')):
    os.makedirs(out, exist_ok=True)
    ws = Workspace(model=load_model(os.path.join(ROOT, 'models', 'vfm_model.pkl')))
    for p in sorted(glob.glob(os.path.join(data_dir, '*'))):
        k = io.detect_kind(p)
        if k: ws.files.setdefault(k, []).append((os.path.basename(p), p))
    t = time.time(); say = lambda msg, f=0: None
    ws.read_inputs(say); ws.run_cleaning(say); ws.run_vfm(progress=say); ws.prepare_pta(say); ws.run_regressions(say)
    for name, data in [('Phase1_VFM_predictions.xlsx', reports.phase1_excel(ws)), ('Phase2_PTA_results.xlsx', reports.phase2_excel(ws)),
                       ('Well_performance_report.pdf', reports.pdf_report(ws))]:
        with open(os.path.join(out, name), 'wb') as f: f.write(data)
        print('wrote', os.path.join('results', name))
    print(f'done in {time.time() - t:.0f} s')


if __name__ == '__main__':
    main()
