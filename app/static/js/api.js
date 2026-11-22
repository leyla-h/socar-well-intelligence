// Small fetch layer with a per-run cache (cleared whenever the analysis re-runs).
const cache = new Map();

async function handle(r) {
  if (r.ok) return r.json();
  let msg = `${r.status} ${r.statusText}`;
  try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail && j.detail.msg) || JSON.stringify(j.detail); } catch (e) {}
  throw new Error(msg);
}

export async function get(url, { fresh = false } = {}) {
  if (!fresh && cache.has(url)) return cache.get(url);
  const p = fetch(url).then(handle);
  cache.set(url, p);
  try { return await p; } catch (e) { cache.delete(url); throw e; }
}

export async function post(url, body = {}) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return handle(r);
}

export async function del(url) { return handle(await fetch(url, { method: 'DELETE' })); }

export function clearCache(prefix = '') {
  for (const k of [...cache.keys()]) if (k.startsWith(prefix)) cache.delete(k);
}

// Multipart upload with progress (large sensor files are ~270 MB).
export function upload(files, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    for (const f of files) fd.append('files', f, f.name);
    const x = new XMLHttpRequest();
    x.open('POST', '/api/upload');
    x.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
    x.onload = () => {
      try {
        const j = JSON.parse(x.responseText);
        x.status < 300 ? resolve(j) : reject(new Error(j.detail || x.statusText));
      } catch (e) { reject(e); }
    };
    x.onerror = () => reject(new Error('Upload failed - is the Quyu server still running?'));
    x.send(fd);
  });
}
