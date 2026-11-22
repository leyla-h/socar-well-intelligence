"""Start Quyu:  python run.py   (then open http://127.0.0.1:8765 - it opens by itself)."""
import os, sys, threading, webbrowser, argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser(description='Quyu well intelligence studio')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8765)))
    ap.add_argument('--host', default=os.environ.get('HOST', '127.0.0.1'))
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    import uvicorn
    from app.server import app
    url = f'http://{a.host}:{a.port}'
    if not a.no_browser and a.host in ('127.0.0.1', 'localhost'):
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f'\n  Quyu is running at {url}   (Ctrl+C to stop)\n')
    uvicorn.run(app, host=a.host, port=a.port, log_level='warning')


if __name__ == '__main__':
    main()
