from __future__ import annotations

import argparse
import cgi
import json
import secrets
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "iphone_backend.ps1"
DEFAULT_DESTINATION = Path.home() / "Documents" / "iPhone_Seleccionados"
MAX_TOTAL_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024
MAX_FILE_UPLOAD_BYTES = 10 * 1024 * 1024 * 1024


def run_backend(action: str, folder: str = "", selections: list[dict] | None = None, destination: Path | None = None):
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(BACKEND),
        "-Action",
        action,
    ]
    if folder:
        command += ["-Folder", folder]
    if selections is not None:
        command += ["-SelectionsJson", json.dumps(selections, ensure_ascii=False)]
    if destination is not None:
        command += ["-Destination", str(destination)]

    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Error desconocido al consultar el iPhone."
        raise RuntimeError(message)
    output = completed.stdout.strip()
    if not output:
        return []
    return json.loads(output)


HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Vídeos del iPhone</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }
    body { margin: 0; background: #f4f6f8; color: #17202a; }
    main { max-width: 760px; margin: 0 auto; padding: 18px 14px 100px; }
    h1 { font-size: 1.35rem; margin: 0 0 6px; }
    p { margin: 7px 0; color: #52606d; }
    .panel { background: white; border-radius: 16px; padding: 16px; margin: 12px 0; box-shadow: 0 2px 12px #1f29371a; }
    .folders { display: flex; flex-wrap: wrap; gap: 8px; }
    button { border: 0; border-radius: 10px; padding: 11px 14px; font: inherit; background: #1769e0; color: white; cursor: pointer; }
    button.secondary { background: #e8eef7; color: #19324d; }
    button:disabled { opacity: .5; cursor: default; }
    .folder { background: #e8eef7; color: #19324d; }
    .folder.selected { background: #1769e0; color: white; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
    input[type=search] { flex: 1 1 190px; min-width: 0; border: 1px solid #c8d1dc; border-radius: 10px; padding: 11px; font: inherit; }
    .file { display: flex; align-items: flex-start; gap: 10px; padding: 12px 0; border-top: 1px solid #e5e9ef; }
    .file:first-child { border-top: 0; }
    .file input { width: 22px; height: 22px; margin-top: 2px; }
    .file-name { font-weight: 650; overflow-wrap: anywhere; }
    .meta { color: #6b7785; font-size: .9rem; margin-top: 3px; }
    #status { white-space: pre-wrap; color: #19324d; }
    .error { color: #a32020 !important; }
    .sticky { position: fixed; left: 0; right: 0; bottom: 0; padding: 10px 14px calc(10px + env(safe-area-inset-bottom)); background: #ffffffee; backdrop-filter: blur(8px); box-shadow: 0 -2px 12px #1f29371a; }
    .sticky-inner { max-width: 760px; margin: 0 auto; display: flex; gap: 8px; align-items: center; }
    #count { flex: 1; color: #52606d; }
    .muted { font-size: .9rem; }
  </style>
</head>
<body>
<main>
  <h1>Vídeos del iPhone</h1>
  <p>Elige una carpeta, marca los vídeos y pulsa «Copiar a la PC».</p>
  <div class="panel">
    <strong>1. Carpeta del iPhone</strong>
    <div id="folders" class="folders" style="margin-top:10px">Cargando…</div>
  </div>
  <div class="panel">
    <div class="toolbar">
      <strong style="margin-right:auto">2. Vídeos</strong>
      <input id="search" type="search" placeholder="Filtrar por nombre" autocomplete="off">
      <button id="all" class="secondary" type="button">Marcar visibles</button>
    </div>
    <div id="files" class="muted">Selecciona una carpeta.</div>
  </div>
  <div class="panel"><div id="status">Destino en la PC: {{DESTINATION}}</div></div>
</main>
<div class="sticky"><div class="sticky-inner"><span id="count">0 seleccionados</span><button id="copy" type="button" disabled>Copiar a la PC</button></div></div>
<script>
const token = {{TOKEN_JSON}};
const foldersEl = document.querySelector('#folders');
const filesEl = document.querySelector('#files');
const statusEl = document.querySelector('#status');
const searchEl = document.querySelector('#search');
const countEl = document.querySelector('#count');
const copyBtn = document.querySelector('#copy');
const allBtn = document.querySelector('#all');
let currentFolder = null;
let currentFiles = [];
const selected = new Map();

function api(path, options = {}) {
  const joiner = path.includes('?') ? '&' : '?';
  return fetch(path + joiner + 'token=' + encodeURIComponent(token), options).then(async r => {
    const data = await r.json().catch(() => ({error: 'Respuesta inválida'}));
    if (!r.ok || data.error) throw new Error(data.error || 'Error');
    return data;
  });
}
function setStatus(text, error = false) { statusEl.textContent = text; statusEl.className = error ? 'error' : ''; }
function refreshCount() { countEl.textContent = `${selected.size} seleccionado${selected.size === 1 ? '' : 's'}`; copyBtn.disabled = selected.size === 0; }
function fileLabel(f) { return [f.size, f.modified || f.created, f.duration].filter(Boolean).join(' · '); }
function renderFiles() {
  const q = searchEl.value.trim().toLowerCase();
  const visible = currentFiles.filter(f => !q || f.name.toLowerCase().includes(q));
  filesEl.innerHTML = '';
  if (!visible.length) { filesEl.textContent = 'No hay vídeos que coincidan.'; return; }
  for (const f of visible) {
    const row = document.createElement('label'); row.className = 'file';
    const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = selected.has(f.id);
    cb.addEventListener('change', () => { if (cb.checked) selected.set(f.id, f); else selected.delete(f.id); refreshCount(); });
    const text = document.createElement('div');
    const name = document.createElement('div'); name.className = 'file-name'; name.textContent = f.name;
    const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = fileLabel(f);
    text.append(name, meta); row.append(cb, text); filesEl.append(row);
  }
}
async function loadFolder(name, button) {
  currentFolder = name; document.querySelectorAll('.folder').forEach(x => x.classList.remove('selected')); button.classList.add('selected');
  filesEl.textContent = 'Cargando vídeos…'; setStatus('Leyendo ' + name + '…');
  try { currentFiles = await api('/api/files?folder=' + encodeURIComponent(name)); renderFiles(); setStatus('Listo. Selecciona los vídeos que quieres copiar.'); }
  catch (e) { filesEl.textContent = e.message; setStatus(e.message, true); }
}
async function loadFolders() {
  try {
    const folders = await api('/api/folders'); foldersEl.innerHTML = '';
    if (!folders.length) { foldersEl.textContent = 'No se encontraron carpetas.'; return; }
    folders.forEach((f, i) => { const b = document.createElement('button'); b.className = 'folder'; b.textContent = f.name; b.onclick = () => loadFolder(f.name, b); foldersEl.append(b); if (i === 0) setTimeout(() => b.click(), 0); });
  } catch (e) { foldersEl.textContent = e.message; setStatus(e.message, true); }
}
searchEl.addEventListener('input', renderFiles);
allBtn.addEventListener('click', () => { currentFiles.filter(f => !searchEl.value || f.name.toLowerCase().includes(searchEl.value.trim().toLowerCase())).forEach(f => selected.set(f.id, f)); renderFiles(); refreshCount(); });
copyBtn.addEventListener('click', async () => {
  if (!selected.size) return;
  copyBtn.disabled = true; setStatus('Copiando… Mantén el iPhone desbloqueado.');
  try {
    const result = await api('/api/copy', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({selections: [...selected.values()].map(f => ({folder: f.folder, name: f.name}))})});
    const ok = (result.copied || []).length, bad = (result.failed || []).length;
    setStatus(`Copias terminadas: ${ok}. Fallos: ${bad}.\nCarpeta: ${result.destination}`);
    if (!bad) { selected.clear(); renderFiles(); }
  } catch (e) { setStatus(e.message, true); }
  refreshCount();
});
loadFolders(); refreshCount();
</script>
</body>
</html>"""


# Wireless mode: the iPhone's browser selects videos from Photos and uploads
# them over the local Wi-Fi connection. This mode does not need USB/MTP access.
HTML = r"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Pasar vídeos sin cable</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, Segoe UI, sans-serif; }
    body { margin: 0; background: #f4f6f8; color: #17202a; }
    main { max-width: 680px; margin: 0 auto; padding: 22px 14px 40px; }
    h1 { font-size: 1.45rem; margin: 0 0 6px; }
    p { margin: 7px 0; color: #52606d; line-height: 1.45; }
    .panel { background: white; border-radius: 16px; padding: 17px; margin: 14px 0; box-shadow: 0 2px 12px #1f29371a; }
    button { border: 0; border-radius: 10px; padding: 12px 15px; font: inherit; background: #1769e0; color: white; cursor: pointer; }
    button:disabled { opacity: .5; cursor: default; }
    input[type=file] { width: 100%; box-sizing: border-box; padding: 13px 8px; border: 1px dashed #9aa9b8; border-radius: 10px; background: #f8fafc; margin: 12px 0; }
    .file { padding: 10px 0; border-top: 1px solid #e5e9ef; overflow-wrap: anywhere; }
    .file:first-child { border-top: 0; }
    .file-name { font-weight: 650; }
    .meta { color: #6b7785; font-size: .9rem; margin-top: 3px; }
    #status { white-space: pre-wrap; color: #19324d; }
    .error { color: #a32020 !important; }
    progress { width: 100%; height: 13px; margin-top: 14px; }
    .note { font-size: .9rem; color: #6b7785; }
  </style>
</head>
<body>
<main>
  <h1>Pasar vídeos sin cable</h1>
  <p>El iPhone y la PC deben estar en la misma Wi‑Fi. Elige los vídeos desde Fotos y se guardarán directamente en la PC.</p>
  <div class="panel">
    <strong>1. Elegir vídeos del iPhone</strong>
    <input id="picker" type="file" accept="video/*" multiple>
    <div id="files" class="note">Todavía no has elegido vídeos.</div>
    <button id="upload" type="button" disabled>Subir vídeos a la PC</button>
    <progress id="progress" value="0" max="100" hidden></progress>
  </div>
  <div class="panel"><div id="status">Destino en la PC: {{DESTINATION}}</div></div>
</main>
<script>
const token = {{TOKEN_JSON}};
const picker = document.querySelector('#picker');
const filesEl = document.querySelector('#files');
const statusEl = document.querySelector('#status');
const uploadButton = document.querySelector('#upload');
const progress = document.querySelector('#progress');
let picked = [];
function formatBytes(n) { if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`; return `${(n / 1024 / 1024).toFixed(1)} MB`; }
function setStatus(text, error = false) { statusEl.textContent = text; statusEl.className = error ? 'error' : ''; }
function renderPicked() {
  filesEl.innerHTML = '';
  if (!picked.length) { filesEl.textContent = 'Todavía no has elegido vídeos.'; uploadButton.disabled = true; return; }
  picked.forEach(file => { const row = document.createElement('div'); row.className = 'file'; const name = document.createElement('div'); name.className = 'file-name'; name.textContent = file.name; const meta = document.createElement('div'); meta.className = 'meta'; meta.textContent = formatBytes(file.size); row.append(name, meta); filesEl.append(row); });
  uploadButton.disabled = false;
}
picker.addEventListener('change', () => { picked = [...picker.files]; renderPicked(); setStatus(`${picked.length} vídeo${picked.length === 1 ? '' : 's'} listo${picked.length === 1 ? '' : 's'} para subir.`); });
uploadButton.addEventListener('click', () => {
  if (!picked.length) return;
  const form = new FormData(); picked.forEach(file => form.append('files', file, file.name));
  const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/upload?token=' + encodeURIComponent(token));
  uploadButton.disabled = true; picker.disabled = true; progress.hidden = false; progress.value = 0; setStatus('Subiendo vídeos a la PC… No cierres esta página.');
  xhr.upload.onprogress = event => { if (event.lengthComputable) progress.value = Math.round(event.loaded / event.total * 100); };
  xhr.onload = () => { picker.disabled = false; try { const result = JSON.parse(xhr.responseText); if (xhr.status >= 200 && xhr.status < 300) { setStatus(`Listo: ${(result.uploaded || []).length} vídeo(s) guardado(s).\nCarpeta: ${result.destination}`); picked = []; picker.value = ''; renderPicked(); } else { setStatus(result.error || 'No se pudo subir.', true); uploadButton.disabled = false; } } catch (_) { setStatus('Respuesta inválida del servidor.', true); uploadButton.disabled = false; } };
  xhr.onerror = () => { picker.disabled = false; uploadButton.disabled = false; setStatus('No se pudo conectar con la PC.', true); };
  xhr.send(form);
});
renderPicked();
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "iPhoneTransfer/1.0"

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

    def _token_ok(self, query):
        return query.get("token", [""])[0] == self.server.auth_token

    def _json(self, value, code=200):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._token_ok(query):
            self._json({"error": "Enlace no autorizado. Usa la URL que muestra el servidor."}, 403)
            return
        try:
            if parsed.path == "/":
                html = HTML.replace("{{TOKEN_JSON}}", json.dumps(self.server.auth_token)).replace("{{DESTINATION}}", str(self.server.destination))
                payload = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            elif parsed.path == "/api/folders":
                self._json(run_backend("folders"))
            elif parsed.path == "/api/files":
                folder = query.get("folder", [""])[0]
                if not folder:
                    raise ValueError("Falta la carpeta.")
                self._json(run_backend("files", folder=folder))
            else:
                self._json({"error": "Ruta no encontrada."}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def _handle_upload(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise ValueError("La solicitud no contiene archivos.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Tamaño de solicitud inválido.") from exc
        if length <= 0:
            raise ValueError("No se recibieron archivos.")
        if length > MAX_TOTAL_UPLOAD_BYTES:
            raise ValueError("La carga supera el límite permitido de 20 GB.")

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(length),
            },
            keep_blank_values=False,
        )
        raw_files = form["files"] if "files" in form else []
        items = raw_files if isinstance(raw_files, list) else [raw_files]
        items = [item for item in items if getattr(item, "filename", None)]
        if not items:
            raise ValueError("No se seleccionaron vídeos.")
        if len(items) > 100:
            raise ValueError("Puedes subir como máximo 100 vídeos por tanda.")

        destination = self.server.destination
        destination.mkdir(parents=True, exist_ok=True)
        uploaded = []
        failed = []
        total_written = 0

        for item in items:
            original_name = str(item.filename)
            # Keep only a simple filename; never accept a client-provided path.
            filename = Path(original_name.replace("\\", "/")).name
            filename = "".join("_" if (ord(char) < 32 or char in '<>:"/\\|?*') else char for char in filename).strip(" .")
            suffix = Path(filename).suffix.lower()
            if not filename or suffix not in {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}:
                failed.append({"name": original_name, "error": "Solo se permiten archivos de vídeo."})
                continue

            target = destination / filename
            counter = 1
            while target.exists():
                target = destination / f"{Path(filename).stem} ({counter}){suffix}"
                counter += 1
            partial = destination / f".{target.name}.{secrets.token_hex(8)}.part"
            written = 0
            try:
                with partial.open("wb") as output:
                    while True:
                        chunk = item.file.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        total_written += len(chunk)
                        if written > MAX_FILE_UPLOAD_BYTES or total_written > MAX_TOTAL_UPLOAD_BYTES:
                            raise ValueError("La carga supera el límite permitido.")
                        output.write(chunk)
                partial.replace(target)
                uploaded.append({"name": target.name, "size": written, "path": str(target)})
            except Exception as exc:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
                failed.append({"name": original_name, "error": str(exc)})

        if not uploaded and failed:
            raise ValueError("No se pudo guardar ningún vídeo: " + "; ".join(item["error"] for item in failed))
        self._json({"uploaded": uploaded, "failed": failed, "destination": str(destination)})

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._token_ok(query):
            self._json({"error": "Enlace no autorizado."}, 403)
            return
        if parsed.path == "/api/upload":
            try:
                self._handle_upload()
            except Exception as exc:
                self._json({"error": str(exc)}, 500)
            return
        if parsed.path != "/api/copy":
            self._json({"error": "Ruta no encontrada."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100_000:
                raise ValueError("Solicitud demasiado grande.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            selections = body.get("selections", [])
            if not isinstance(selections, list) or not selections or len(selections) > 200:
                raise ValueError("Selecciona entre 1 y 200 vídeos.")
            clean = []
            for item in selections:
                if not isinstance(item, dict) or not isinstance(item.get("folder"), str) or not isinstance(item.get("name"), str):
                    raise ValueError("Selección inválida.")
                clean.append({"folder": item["folder"], "name": item["name"]})
            result = run_backend("copy", selections=clean, destination=self.server.destination)
            self._json(result)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="Servidor local para seleccionar vídeos del iPhone y copiarlos al PC.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    if not BACKEND.exists():
        raise SystemExit(f"Falta el backend: {BACKEND}")
    args.destination = args.destination.expanduser().resolve()
    args.destination.mkdir(parents=True, exist_ok=True)
    auth_token = secrets.token_urlsafe(24)
    httpd = Server((args.host, args.port), Handler)
    httpd.auth_token = auth_token
    httpd.destination = args.destination
    print(f"Destino: {args.destination}", flush=True)
    print(f"Clave temporal: {auth_token}", flush=True)
    print("Abre en el iPhone la URL de la IP Wi-Fi del PC con esta clave.", flush=True)
    print("Pulsa Ctrl+C para detener el servidor.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
