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
  <meta name="theme-color" content="#f4f6f8">
  <title>Pasar vídeos sin cable</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --ink: #17202a;
      --muted: #52606d;
      --subtle: #778493;
      --line: #dce3ea;
      --blue: #1769e0;
      --blue-soft: #eaf2ff;
      --green: #17834b;
      --green-soft: #e9f8ef;
      --red: #a32020;
      --red-soft: #fff0f0;
      --shadow: 0 8px 26px rgba(31, 41, 55, 0.08);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; }
    html { background: var(--bg); }
    body { margin: 0; background: var(--bg); color: var(--ink); }
    body, button, input { font: inherit; }
    button { -webkit-tap-highlight-color: transparent; }
    button:focus-visible, .picker-zone:focus-visible { outline: 3px solid #8bb8ff; outline-offset: 3px; }

    main {
      width: min(100%, 720px);
      margin: 0 auto;
      padding: max(20px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(32px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left));
    }

    .hero { display: flex; align-items: flex-start; gap: 13px; padding: 8px 3px 18px; }
    .brand-mark {
      display: grid;
      width: 42px;
      height: 42px;
      flex: 0 0 auto;
      place-items: center;
      border-radius: 13px;
      background: var(--blue);
      color: white;
      box-shadow: 0 6px 14px rgba(23, 105, 224, 0.24);
    }
    .brand-mark svg { width: 24px; height: 24px; }
    .eyebrow { margin: 0 0 5px; color: var(--subtle); font-size: 11px; font-weight: 750; letter-spacing: .1em; text-transform: uppercase; }
    h1 { margin: 0; font-size: clamp(25px, 7vw, 34px); letter-spacing: -0.045em; line-height: 1.08; }
    .lede { max-width: 570px; margin: 8px 0 0; color: var(--muted); font-size: 15px; line-height: 1.45; }

    .connection {
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0 0 14px;
      border: 1px solid #cce3d5;
      border-radius: 12px;
      background: var(--green-soft);
      padding: 11px 13px;
      color: var(--green);
    }
    .connection-dot { width: 9px; height: 9px; flex: 0 0 auto; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 4px rgba(23, 131, 75, .12); }
    .connection strong, .connection span { display: block; }
    .connection strong { font-size: 13px; }
    .connection span { margin-top: 2px; color: #3e7458; font-size: 12px; }

    .panel, .action-panel, .status {
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .panel { margin: 14px 0; padding: 17px; }
    .panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
    h2 { margin: 2px 0 0; font-size: 19px; letter-spacing: -0.025em; }
    .counter { flex: 0 0 auto; border-radius: 999px; background: var(--blue-soft); padding: 6px 9px; color: var(--blue); font-size: 12px; font-weight: 750; }

    .picker-zone {
      display: grid;
      width: 100%;
      min-height: 188px;
      place-items: center;
      margin-top: 15px;
      border: 1.5px dashed #8eafd9;
      border-radius: 14px;
      background: linear-gradient(180deg, #f8fbff, #f0f6ff);
      padding: 20px 16px;
      color: var(--ink);
      cursor: pointer;
      text-align: center;
      transition: border-color 140ms ease, background-color 140ms ease, transform 140ms ease;
    }
    .picker-zone:hover, .picker-zone.is-dragging { border-color: var(--blue); background: var(--blue-soft); }
    .picker-zone:active { transform: scale(.995); }
    .picker-icon { width: 45px; height: 45px; margin-bottom: 8px; color: var(--blue); }
    .picker-title { font-size: 17px; font-weight: 780; }
    .picker-copy { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.35; }
    .picker-cta { display: inline-block; margin-top: 13px; border-radius: 9px; background: var(--blue); padding: 10px 15px; color: white; font-size: 13px; font-weight: 750; }
    .picker-help { margin: 10px 2px 0; color: var(--subtle); font-size: 12px; line-height: 1.4; }

    .sr-only, .visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
    .hidden { display: none !important; }
    .validation { margin-top: 12px; border-radius: 10px; background: var(--red-soft); padding: 10px 12px; color: var(--red); font-size: 13px; line-height: 1.4; }
    .validation ul { margin: 0; padding-left: 18px; }

    .queue { margin-top: 14px; }
    .queue-list { display: grid; gap: 8px; margin: 14px 0 0; padding: 0; list-style: none; }
    .file { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; align-items: center; border: 1px solid #e5e9ef; border-radius: 11px; background: var(--surface-soft); padding: 10px; }
    .file-icon { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 9px; background: var(--blue-soft); color: var(--blue); }
    .file-icon svg { width: 18px; height: 18px; }
    .file-info { min-width: 0; }
    .file-name { overflow: hidden; font-size: 13px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
    .file-meta { margin-top: 3px; color: var(--subtle); font-size: 12px; }
    .file-status { margin-top: 4px; font-size: 11px; font-weight: 700; }
    .file-status.ok { color: var(--green); }
    .file-status.error { color: var(--red); }
    .remove { border: 0; background: transparent; padding: 8px 2px 8px 8px; color: var(--red); cursor: pointer; font-size: 12px; font-weight: 700; }
    .remove:hover { text-decoration: underline; }
    .remove:disabled { cursor: default; opacity: .45; text-decoration: none; }
    .summary { margin-top: 12px; color: var(--muted); font-size: 12px; }

    .action-panel { margin: 14px 0; padding: 17px; }
    .progress-heading { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 13px; font-weight: 700; }
    #progress-value { color: var(--blue); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    progress { display: block; width: 100%; height: 12px; margin: 12px 0 15px; overflow: hidden; border: 0; border-radius: 999px; background: #e4e9ef; }
    progress::-webkit-progress-bar { border-radius: 999px; background: #e4e9ef; }
    progress::-webkit-progress-value { border-radius: 999px; background: var(--blue); transition: width 160ms linear; }
    progress::-moz-progress-bar { border-radius: 999px; background: var(--blue); }
    #upload { width: 100%; min-height: 49px; border: 0; border-radius: 11px; background: var(--blue); color: white; cursor: pointer; font-size: 15px; font-weight: 780; box-shadow: 0 7px 15px rgba(23, 105, 224, .2); }
    #upload:hover { background: #0f59c5; }
    #upload:disabled { background: #b8c3d0; box-shadow: none; cursor: default; }

    .status { display: flex; gap: 10px; align-items: flex-start; margin: 14px 0; padding: 13px 15px; color: var(--muted); font-size: 13px; line-height: 1.4; }
    .status-mark { width: 10px; height: 10px; flex: 0 0 auto; margin-top: 4px; border-radius: 50%; background: var(--blue); box-shadow: 0 0 0 4px var(--blue-soft); }
    .status[data-tone="success"] { border-color: #cce3d5; background: var(--green-soft); color: var(--green); }
    .status[data-tone="success"] .status-mark { background: var(--green); box-shadow: 0 0 0 4px #d9f2e3; }
    .status[data-tone="error"] { border-color: #f0c8c8; background: var(--red-soft); color: var(--red); }
    .status[data-tone="error"] .status-mark { background: var(--red); box-shadow: 0 0 0 4px #ffe0e0; }
    .limits { margin: 14px 3px 0; color: var(--subtle); font-size: 11px; line-height: 1.5; text-align: center; }

    @media (min-width: 650px) {
      main { padding-top: 34px; }
      .picker-zone { min-height: 205px; }
    }

    @media (prefers-reduced-motion: reduce) {
      .picker-zone, progress::-webkit-progress-value { transition: none; }
    }

    @media (prefers-color-scheme: dark) {
      :root {
        color-scheme: dark;
        --bg: #101720;
        --surface: #18222e;
        --surface-soft: #1d2937;
        --ink: #f3f8ff;
        --muted: #b5c1ce;
        --subtle: #8d9aaa;
        --line: #2e3b4a;
        --blue-soft: #1c3558;
        --green-soft: #173629;
        --red-soft: #3b2024;
        --shadow: 0 8px 26px rgba(0, 0, 0, .2);
      }
      .connection { border-color: #2d6246; }
      .connection span { color: #9ad1ad; }
      .picker-zone { border-color: #547da9; background: linear-gradient(180deg, #1b2c42, #172638); }
      .picker-zone:hover, .picker-zone.is-dragging { background: #203b5d; }
      .file { border-color: var(--line); }
      progress, progress::-webkit-progress-bar { background: #2a3746; }
      .status[data-tone="success"] { border-color: #2d6246; }
      .status[data-tone="error"] { border-color: #704047; }
    }
  </style>
</head>
<body>
<main>
  <header class="hero">
    <div class="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/></svg>
    </div>
    <div>
      <p class="eyebrow">Transferencia local</p>
      <h1>Pasar vídeos sin cable</h1>
      <p class="lede">Elige vídeos desde Fotos y guárdalos directamente en la PC.</p>
    </div>
  </header>

  <section class="connection" aria-label="Estado de conexión">
    <span class="connection-dot" aria-hidden="true"></span>
    <div><strong>Conectado a esta PC</strong><span>El iPhone y la PC están en la misma Wi‑Fi.</span></div>
  </section>

  <section class="panel" aria-labelledby="selection-title">
    <div class="panel-heading">
      <div><p class="eyebrow">01 · Selección</p><h2 id="selection-title">Elige tus vídeos</h2></div>
      <span id="selection-count" class="counter">0 vídeos</span>
    </div>
    <button id="pick-zone" class="picker-zone" type="button" aria-describedby="picker-help">
      <svg class="picker-icon" viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="9" width="38" height="30" rx="6"/><path d="m11 32 9-9 6 6 4-4 7 7"/><circle cx="17" cy="18" r="3"/></svg>
      <span class="picker-title">Selecciona tus vídeos</span>
      <span class="picker-copy">Se abrirá Fotos del iPhone</span>
      <span class="picker-cta">Elegir vídeos</span>
    </button>
    <input id="picker" class="visually-hidden" type="file" accept="video/*,.mov,.mp4,.m4v,.avi,.mkv,.3gp" multiple aria-describedby="picker-help">
    <p id="picker-help" class="picker-help">MOV, MP4, M4V, AVI, MKV o 3GP · hasta 10 GB por vídeo y 20 GB por tanda.</p>
    <div id="validation-errors" class="validation hidden" role="alert"></div>
  </section>

  <section id="queue-panel" class="panel queue hidden" aria-labelledby="queue-title">
    <div class="panel-heading">
      <div><p class="eyebrow">02 · Cola</p><h2 id="queue-title">Vídeos seleccionados</h2></div>
      <span id="queue-total" class="counter">0 MB</span>
    </div>
    <ul id="files" class="queue-list" aria-live="polite"></ul>
    <div id="selection-summary" class="summary"></div>
  </section>

  <section class="action-panel" aria-labelledby="progress-title">
    <div class="progress-heading"><span id="progress-title">Progreso de subida</span><span id="progress-value">0%</span></div>
    <progress id="progress" value="0" max="100" aria-label="Progreso de subida"></progress>
    <button id="upload" type="button" disabled>Subir vídeos a la PC</button>
  </section>

  <div id="status" class="status" role="status" aria-live="polite"><span class="status-mark" aria-hidden="true"></span><span id="status-text">Listo para recibir vídeos.</span></div>
  <p class="limits">La página no envía nada fuera de tu red local. Los vídeos se guardan en Documents\iPhone_Seleccionados.</p>
</main>
<script>
const token = {{TOKEN_JSON}};
const allowed = new Set(['.mov', '.mp4', '.m4v', '.avi', '.mkv', '.3gp']);
const maxFileBytes = 10 * 1024 * 1024 * 1024;
const maxBatchBytes = 20 * 1024 * 1024 * 1024;
const picker = document.querySelector('#picker');
const pickZone = document.querySelector('#pick-zone');
const queuePanel = document.querySelector('#queue-panel');
const filesEl = document.querySelector('#files');
const selectionCount = document.querySelector('#selection-count');
const queueTotal = document.querySelector('#queue-total');
const selectionSummary = document.querySelector('#selection-summary');
const validationErrors = document.querySelector('#validation-errors');
const statusEl = document.querySelector('#status');
const statusText = document.querySelector('#status-text');
const uploadButton = document.querySelector('#upload');
const progress = document.querySelector('#progress');
const progressValue = document.querySelector('#progress-value');
let picked = [];
let uploading = false;
let selectionError = '';

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function extension(name) {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot).toLowerCase();
}

function setStatus(text, tone = '') {
  statusEl.dataset.tone = tone;
  statusText.textContent = text;
}

function statusLabel(item) {
  if (item.status === 'terminado') return 'Guardado en la PC';
  if (item.status === 'subiendo') return 'Subiendo…';
  if (item.status === 'error') return item.error || 'No se pudo subir';
  return 'Listo para subir';
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

function showValidationErrors(errors) {
  validationErrors.replaceChildren();
  if (!errors.length) {
    validationErrors.classList.add('hidden');
    return;
  }
  const list = document.createElement('ul');
  errors.forEach(error => {
    const item = document.createElement('li');
    item.textContent = error;
    list.append(item);
  });
  validationErrors.append(list);
  validationErrors.classList.remove('hidden');
}

function makeFileIcon() {
  const icon = document.createElement('span');
  icon.className = 'file-icon';
  icon.setAttribute('aria-hidden', 'true');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  const frame = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  frame.setAttribute('x', '3'); frame.setAttribute('y', '5'); frame.setAttribute('width', '18'); frame.setAttribute('height', '14'); frame.setAttribute('rx', '3');
  const play = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  play.setAttribute('d', 'm9 9 6 3-6 3z');
  svg.append(frame, play);
  icon.append(svg);
  return icon;
}

function renderQueue() {
  filesEl.replaceChildren();
  const totalBytes = picked.reduce((sum, item) => sum + item.file.size, 0);
  const doneCount = picked.filter(item => item.status === 'terminado').length;
  selectionCount.textContent = `${picked.length} vídeo${picked.length === 1 ? '' : 's'}`;
  queueTotal.textContent = formatBytes(totalBytes);
  selectionSummary.textContent = picked.length ? `${doneCount} de ${picked.length} guardados · ${formatBytes(totalBytes)} en total` : '';
  queuePanel.classList.toggle('hidden', !picked.length);
  pickZone.disabled = uploading;
  picker.disabled = uploading;
  uploadButton.disabled = uploading || Boolean(selectionError) || !picked.some(item => item.status !== 'terminado');
  uploadButton.textContent = picked.some(item => item.status === 'error') ? 'Reintentar subida' : 'Subir vídeos a la PC';

  picked.forEach((item, index) => {
    const row = document.createElement('li');
    row.className = 'file';
    const info = document.createElement('div');
    info.className = 'file-info';
    const name = document.createElement('div');
    name.className = 'file-name';
    name.textContent = item.file.name;
    const meta = document.createElement('div');
    meta.className = 'file-meta';
    meta.textContent = formatBytes(item.file.size);
    const state = document.createElement('div');
    state.className = `file-status ${item.status === 'terminado' ? 'ok' : item.status === 'error' ? 'error' : ''}`;
    state.textContent = statusLabel(item);
    info.append(name, meta, state);
    const remove = document.createElement('button');
    remove.className = 'remove';
    remove.type = 'button';
    remove.textContent = 'Quitar';
    remove.disabled = uploading;
    remove.setAttribute('aria-label', `Quitar ${item.file.name}`);
    remove.addEventListener('click', () => {
      picked.splice(index, 1);
      if (picked.reduce((sum, queued) => sum + queued.file.size, 0) <= maxBatchBytes) selectionError = '';
      renderQueue();
    });
    row.append(makeFileIcon(), info, remove);
    filesEl.append(row);
  });
}

function selectFiles(fileList) {
  const result = validateFiles(Array.from(fileList || []));
  picked = result.valid;
  selectionError = result.errors.find(error => error === 'La tanda supera 20 GB.') || '';
  showValidationErrors(result.errors);
  renderQueue();
  if (result.errors.length) setStatus('Revisa los archivos marcados antes de subir.', 'error');
  else if (picked.length) setStatus(`${picked.length} vídeo${picked.length === 1 ? '' : 's'} listo${picked.length === 1 ? '' : 's'} para subir.`);
  else setStatus('No se seleccionaron vídeos.');
}

function uploadOne(item, index, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const query = new URLSearchParams({ token, name: item.file.name, indice: String(index + 1), total: String(total) });
    xhr.open('POST', `/api/upload?${query.toString()}`);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.addEventListener('progress', event => {
      if (!event.lengthComputable) return;
      const value = Math.round(event.loaded / event.total * 100);
      progress.value = value;
      progressValue.textContent = `${value}%`;
      setStatus(`Subiendo ${index + 1} de ${total}: ${item.file.name}`, 'uploading');
    });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`El servidor rechazó ${item.file.name} (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new Error(`No se pudo subir ${item.file.name}.`));
    xhr.ontimeout = () => reject(new Error(`La subida de ${item.file.name} agotó el tiempo de espera.`));
    xhr.send(item.file);
  });
}

pickZone.addEventListener('click', () => { if (!uploading) picker.click(); });
picker.addEventListener('change', () => selectFiles(picker.files));
pickZone.addEventListener('dragover', event => { event.preventDefault(); pickZone.classList.add('is-dragging'); });
pickZone.addEventListener('dragleave', () => pickZone.classList.remove('is-dragging'));
pickZone.addEventListener('drop', event => {
  event.preventDefault();
  pickZone.classList.remove('is-dragging');
  if (!uploading) selectFiles(event.dataTransfer.files);
});

uploadButton.addEventListener('click', async () => {
  if (uploading || !picked.length || selectionError) return;
  uploading = true;
  progress.value = 0;
  progressValue.textContent = '0%';
  const batch = picked.filter(item => item.status !== 'terminado');
  try {
    for (let index = 0; index < batch.length; index += 1) {
      const item = batch[index];
      item.status = 'subiendo';
      item.error = '';
      renderQueue();
      await uploadOne(item, index, batch.length);
      item.status = 'terminado';
      progress.value = 100;
      progressValue.textContent = '100%';
      renderQueue();
    }
    setStatus(`Listo: ${batch.length} vídeo${batch.length === 1 ? '' : 's'} guardado${batch.length === 1 ? '' : 's'} en la PC.`, 'success');
  } catch (error) {
    const current = batch.find(item => item.status === 'subiendo');
    if (current) { current.status = 'error'; current.error = error.message; }
    renderQueue();
    setStatus(error.message, 'error');
  } finally {
    uploading = false;
    renderQueue();
  }
});

window.addEventListener('beforeunload', event => {
  if (!uploading) return;
  event.preventDefault();
  event.returnValue = '';
});

renderQueue();
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
