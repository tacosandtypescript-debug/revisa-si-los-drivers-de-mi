from __future__ import annotations

import argparse
import json
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}
CHUNK_SIZE = 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024 * 1024
MAX_BATCH_BYTES = 20 * 1024 * 1024 * 1024
MAX_BATCH_FILES = 200
DEFAULT_DESTINATION = Path.home() / "Documents" / "iPhone_Seleccionados"


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def positive_int(value: str, label: str, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} no es válido.") from exc
    if number < 1 or number > maximum:
        raise ValueError(f"{label} debe estar entre 1 y {maximum}.")
    return number


def sanitize_filename(raw_name: str) -> str:
    candidate = Path(raw_name.replace("\\", "/")).name
    candidate = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", candidate).strip(" .")
    if not candidate:
        raise ValueError("El nombre del archivo está vacío.")
    if len(candidate) > 240:
        suffix = Path(candidate).suffix
        candidate = candidate[: 240 - len(suffix)] + suffix
    if Path(candidate).suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError("Solo se permiten vídeos MOV, MP4, M4V, AVI, MKV o 3GP.")
    return candidate


def unique_target(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    counter = 1
    while candidate.exists():
        path = Path(filename)
        candidate = directory / f"{path.stem} ({counter}){path.suffix}"
        counter += 1
    return candidate


class UploadState:
    """Thread-safe status shared by /api/estado and the upload worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._batch_bytes = 0
        self._batch_total = 0
        self._state: dict[str, object] = {
            "estado": "reposo",
            "archivo": "",
            "bytes_recibidos": 0,
            "total": 0,
            "mb_s": 0.0,
            "indice": 0,
            "total_tanda": 0,
        }

    def start(self, filename: str, total: int, index: int, batch_total: int) -> float:
        with self._lock:
            if index == 1 or batch_total != self._batch_total:
                self._batch_bytes = 0
                self._batch_total = batch_total
            if self._batch_bytes + total > MAX_BATCH_BYTES:
                raise ValueError("La tanda supera el límite de 20 GB.")
            self._state = {
                "estado": "subiendo",
                "archivo": filename,
                "bytes_recibidos": 0,
                "total": total,
                "mb_s": 0.0,
                "indice": index,
                "total_tanda": batch_total,
            }
            return time.perf_counter()

    def progress(self, received: int, started_at: float) -> None:
        elapsed = max(time.perf_counter() - started_at, 0.001)
        with self._lock:
            self._state["bytes_recibidos"] = received
            self._state["mb_s"] = round(received / 1024 / 1024 / elapsed, 2)

    def complete(self, total: int, started_at: float) -> None:
        elapsed = max(time.perf_counter() - started_at, 0.001)
        with self._lock:
            self._batch_bytes += total
            self._state["estado"] = "terminado"
            self._state["bytes_recibidos"] = total
            self._state["mb_s"] = round(total / 1024 / 1024 / elapsed, 2)

    def fail(self, received: int, started_at: float | None) -> None:
        elapsed = max((time.perf_counter() - started_at) if started_at else 0.001, 0.001)
        with self._lock:
            self._state["estado"] = "error"
            self._state["bytes_recibidos"] = received
            self._state["mb_s"] = round(received / 1024 / 1024 / elapsed, 2)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state)


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
    button.danger { background: transparent; color: #a32020; padding: 5px 8px; }
    button:disabled { opacity: .5; cursor: default; }
    input[type=file] { width: 100%; box-sizing: border-box; padding: 13px 8px; border: 1px dashed #9aa9b8; border-radius: 10px; background: #f8fafc; margin: 12px 0; }
    .file { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; padding: 10px 0; border-top: 1px solid #e5e9ef; overflow-wrap: anywhere; }
    .file:first-child { border-top: 0; }
    .file-name { font-weight: 650; }
    .meta { color: #6b7785; font-size: .9rem; margin-top: 3px; }
    .ok { color: #17834b; }
    .error { color: #a32020 !important; }
    #status { white-space: pre-wrap; color: #19324d; }
    progress { width: 100%; height: 13px; margin-top: 14px; }
    .note { font-size: .9rem; color: #6b7785; }
    .limits { font-size: .8rem; color: #778493; margin-top: 10px; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
  </style>
</head>
<body>
<main>
  <h1>Pasar vídeos sin cable</h1>
  <p>El iPhone y la PC deben estar en la misma Wi‑Fi. Elige los vídeos desde Fotos y se guardarán directamente en la PC.</p>
  <div class="panel">
    <strong>Elegir vídeos del iPhone</strong>
    <label class="sr-only" for="picker">Seleccionar vídeos</label>
    <input id="picker" type="file" accept="video/*,.mov,.mp4,.m4v,.avi,.mkv,.3gp" multiple>
    <div id="files" class="note" aria-live="polite">Todavía no has elegido vídeos.</div>
    <div class="limits">MOV, MP4, M4V, AVI, MKV o 3GP · máximo 10 GB por archivo · 20 GB por tanda</div>
    <button id="upload" type="button" disabled>Subir vídeos a la PC</button>
    <progress id="progress" value="0" max="100" hidden aria-label="Progreso de subida"></progress>
  </div>
  <div class="panel"><div id="status" role="status" aria-live="polite">Listo para recibir vídeos.</div></div>
</main>
<script>
const token = {{TOKEN_JSON}};
const allowed = new Set(['.mov', '.mp4', '.m4v', '.avi', '.mkv', '.3gp']);
const maxFileBytes = 10 * 1024 * 1024 * 1024;
const maxBatchBytes = 20 * 1024 * 1024 * 1024;
const picker = document.querySelector('#picker');
const filesEl = document.querySelector('#files');
const statusEl = document.querySelector('#status');
const uploadButton = document.querySelector('#upload');
const progress = document.querySelector('#progress');
let picked = [];
let uploading = false;
let selectionError = '';

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function extension(name) {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot).toLowerCase();
}

function setStatus(text, error = false) {
  statusEl.textContent = text;
  statusEl.className = error ? 'error' : '';
}

function validateFiles(files) {
  const valid = [];
  const errors = [];
  for (const file of files) {
    if (!allowed.has(extension(file.name))) errors.push(`${file.name}: formato no permitido.`);
    else if (file.size === 0) errors.push(`${file.name}: el archivo está vacío.`);
    else if (file.size > maxFileBytes) errors.push(`${file.name}: supera 10 GB.`);
    else valid.push({ file, status: 'pendiente', error: '' });
  }
  if (valid.reduce((sum, item) => sum + item.file.size, 0) > maxBatchBytes) errors.push('La tanda supera 20 GB.');
  return { valid, errors };
}

function renderQueue() {
  filesEl.innerHTML = '';
  if (!picked.length) {
    filesEl.textContent = 'Todavía no has elegido vídeos.';
    uploadButton.disabled = true;
    return;
  }
  picked.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'file';
    const info = document.createElement('div');
    const name = document.createElement('div');
    name.className = 'file-name';
    name.textContent = item.file.name;
    const meta = document.createElement('div');
    meta.className = `meta ${item.status === 'terminado' ? 'ok' : item.status === 'error' ? 'error' : ''}`;
    meta.textContent = item.error || `${formatBytes(item.file.size)} · ${item.status}`;
    info.append(name, meta);
    const remove = document.createElement('button');
    remove.className = 'danger';
    remove.type = 'button';
    remove.textContent = 'Quitar';
    remove.disabled = uploading;
    remove.setAttribute('aria-label', `Quitar ${item.file.name}`);
    remove.addEventListener('click', () => {
      picked.splice(index, 1);
      if (picked.reduce((sum, queued) => sum + queued.file.size, 0) <= maxBatchBytes) selectionError = '';
      renderQueue();
    });
    row.append(info, remove);
    filesEl.append(row);
  });
  uploadButton.disabled = uploading || Boolean(selectionError) || !picked.some(item => item.status !== 'terminado');
}

function uploadOne(item, index, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const query = new URLSearchParams({ token, name: item.file.name, indice: String(index + 1), total: String(total) });
    xhr.open('POST', `/api/upload?${query.toString()}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.addEventListener('progress', event => {
      if (!event.lengthComputable) return;
      progress.value = Math.round(event.loaded / event.total * 100);
      setStatus(`Subiendo ${index + 1} de ${total}: ${item.file.name} · ${progress.value}%`);
    });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`El servidor rechazó ${item.file.name} (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new Error(`No se pudo subir ${item.file.name}.`));
    xhr.send(item.file);
  });
}

picker.addEventListener('change', () => {
  const result = validateFiles(Array.from(picker.files || []));
  picked = result.valid;
  selectionError = result.errors.find(error => error === 'La tanda supera 20 GB.') || '';
  renderQueue();
  if (result.errors.length) setStatus(result.errors.join('\n'), true);
  else setStatus(`${picked.length} vídeo${picked.length === 1 ? '' : 's'} listo${picked.length === 1 ? '' : 's'} para subir.`);
});

uploadButton.addEventListener('click', async () => {
  if (uploading || !picked.length) return;
  uploading = true;
  progress.hidden = false;
  progress.value = 0;
  const batch = picked.filter(item => item.status !== 'terminado');
  try {
    for (let index = 0; index < batch.length; index += 1) {
      const item = batch[index];
      item.status = 'subiendo';
      renderQueue();
      await uploadOne(item, index, batch.length);
      item.status = 'terminado';
      progress.value = 100;
      renderQueue();
    }
    setStatus(`Listo: ${batch.length} vídeo${batch.length === 1 ? '' : 's'} guardado${batch.length === 1 ? '' : 's'} en la PC.`);
  } catch (error) {
    const current = batch.find(item => item.status === 'subiendo');
    if (current) { current.status = 'error'; current.error = error.message; }
    renderQueue();
    setStatus(error.message, true);
  } finally {
    uploading = false;
    picker.disabled = false;
    renderQueue();
  }
});

window.addEventListener('beforeunload', event => {
  if (!uploading) return;
  event.preventDefault();
  event.returnValue = '';
});
</script>
</body>
</html>"""


class UploadHandler(BaseHTTPRequestHandler):
    server_version = "iPhoneTransfer/2.0"
    protocol_version = "HTTP/1.1"
    rbufsize = CHUNK_SIZE

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            # Socket tuning is best-effort; the transfer remains portable.
            pass

    def log_message(self, fmt: str, *args: object) -> None:
        if self.path.startswith("/api/estado"):
            return
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)

    def _send_headers(self, content_type: str, length: int, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _send_json(self, value: object, status: int = 200) -> None:
        body = json_bytes(value)
        self._send_headers("application/json; charset=utf-8", len(body), status)
        self.wfile.write(body)

    def _send_error(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _authorized(self, query: dict[str, list[str]]) -> bool:
        return query.get("token", [""])[0] == self.server.auth_token

    def do_OPTIONS(self) -> None:
        self._send_headers("text/plain; charset=utf-8", 0, 204)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self._send_error("Clave no válida.", 403)
            return
        if parsed.path == "/api/estado":
            self._send_json(self.server.upload_state.snapshot())
            return
        if parsed.path != "/":
            self._send_error("Ruta no encontrada.", 404)
            return
        html = HTML.replace("{{TOKEN_JSON}}", json.dumps(self.server.auth_token))
        body = html.encode("utf-8")
        self._send_headers("text/html; charset=utf-8", len(body))
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self._send_error("Clave no válida.", 403)
            return
        if parsed.path != "/api/upload":
            self._send_error("Ruta no encontrada.", 404)
            return

        raw_name = query.get("name", [""])[0]
        try:
            filename = sanitize_filename(raw_name)
            index = positive_int(query.get("indice", [""])[0], "El índice", MAX_BATCH_FILES)
            batch_total = positive_int(query.get("total", [""])[0], "El total", MAX_BATCH_FILES)
            if index > batch_total:
                raise ValueError("El índice no puede superar el total de la tanda.")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValueError("Falta Content-Length.")
            length = int(raw_length)
            if length <= 0:
                raise ValueError("El vídeo está vacío.")
            if length > MAX_FILE_BYTES:
                raise ValueError("El archivo supera el límite de 10 GB.")
        except (TypeError, ValueError) as exc:
            self._send_error(str(exc), 400)
            return

        content_type = self.headers.get("Content-Type", "")
        if content_type and content_type != "application/octet-stream" and not content_type.startswith("video/"):
            self._send_error("Content-Type no permitido.", 415)
            return

        with self.server.upload_lock:
            target = unique_target(self.server.destination, filename)
            partial = self.server.destination / f".{target.name}.{secrets.token_hex(8)}.part"
            received = 0
            started_at: float | None = None
            try:
                started_at = self.server.upload_state.start(filename, length, index, batch_total)
                with partial.open("wb", buffering=CHUNK_SIZE) as output:
                    while received < length:
                        chunk = self.rfile.read(min(CHUNK_SIZE, length - received))
                        if not chunk:
                            raise ConnectionError("La conexión se cerró antes de terminar el vídeo.")
                        output.write(chunk)
                        received += len(chunk)
                        self.server.upload_state.progress(received, started_at)
                partial.replace(target)
                self.server.upload_state.complete(length, started_at)
                self._send_json({"ok": True, "archivo": target.name, "bytes": length, "indice": index, "total": batch_total})
            except Exception as exc:
                try:
                    partial.unlink(missing_ok=True)
                except OSError:
                    pass
                self.server.upload_state.fail(received, started_at)
                self._send_error(str(exc), 500)


class UploadServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str, destination: Path):
        super().__init__(address, UploadHandler)
        self.auth_token = token
        self.destination = destination
        self.destination.mkdir(parents=True, exist_ok=True)
        self.upload_state = UploadState()
        self.upload_lock = threading.Lock()


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor local para recibir vídeos del iPhone por Wi-Fi.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="", help="Clave generada por Electron; si se omite, se genera una nueva.")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    args = parser.parse_args()
    token = args.token or secrets.token_urlsafe(24)
    server = UploadServer((args.host, args.port), token, args.destination.expanduser().resolve())
    print(f"Destino: {server.destination}", flush=True)
    print(f"Clave temporal: {token}", flush=True)
    print(f"Escuchando en {args.host}:{args.port}", flush=True)
    print("Pulsa Ctrl+C para detener el servidor.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
