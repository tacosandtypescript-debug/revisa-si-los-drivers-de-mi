const desktopBridge = window.transferDesktop;

const ringProgress = document.querySelector('#ring-progress');
const percent = document.querySelector('#percent');
const qr = document.querySelector('#qr');
const qrCard = document.querySelector('#qr-card');
const statusBadge = document.querySelector('#status-badge');
const statusLabel = document.querySelector('#status-label');
const filename = document.querySelector('#filename');
const speed = document.querySelector('#speed');
const counter = document.querySelector('#counter');
const url = document.querySelector('#url');
const hint = document.querySelector('#hint');
const ariaStatus = document.querySelector('#aria-status');
const copyUrlButton = document.querySelector('#copy-url');
let config = null;
let lastState = { estado: 'reposo' };

const labels = {
  reposo: 'Listo',
  subiendo: 'Subiendo',
  terminado: 'Terminado',
  error: 'Error',
};

window.copyIphoneUrl = async () => {
  copyUrlButton.disabled = true;
  try {
    await desktopBridge.copyUrl();
    copyUrlButton.textContent = 'URL copiada';
    ariaStatus.textContent = 'URL copiada al portapapeles.';
    window.setTimeout(() => {
      copyUrlButton.textContent = 'Copiar URL';
      copyUrlButton.disabled = false;
    }, 1600);
  } catch (_) {
    copyUrlButton.textContent = 'No se pudo copiar';
    copyUrlButton.disabled = false;
  }
};

function currentPercent(state) {
  if (state.estado === 'terminado') return 100;
  if (!state.total) return 0;
  return Math.max(0, Math.min(100, Math.round((state.bytes_recibidos / state.total) * 100)));
}

function renderState(state) {
  lastState = state || { estado: 'reposo' };
  const status = ['reposo', 'subiendo', 'terminado', 'error'].includes(lastState.estado) ? lastState.estado : 'error';
  const value = currentPercent(lastState);
  document.body.dataset.state = status;
  ringProgress.style.strokeDashoffset = String((2 * Math.PI * 50) - ((2 * Math.PI * 50) * value / 100));
  percent.textContent = `${value}%`;
  statusBadge.textContent = labels[status];
  statusLabel.textContent = labels[status];
  filename.textContent = status === 'reposo' ? 'Preparado para recibir vídeos' : (lastState.archivo || 'Transferencia');
  speed.textContent = status === 'reposo' ? 'Esperando' : `${Number(lastState.mb_s || 0).toFixed(1)} MB/s`;
  counter.textContent = status === 'reposo' ? '—' : `${lastState.indice || 0} de ${lastState.total_tanda || 0}`;
  hint.textContent = status === 'reposo'
    ? 'Abre la URL o escanea el QR desde el iPhone conectado a la misma Wi‑Fi.'
    : status === 'subiendo'
      ? 'Puedes dejar esta ventana abierta mientras se transfieren los vídeos.'
      : status === 'terminado'
        ? 'El vídeo quedó guardado en Documents\\iPhone_Seleccionados.'
        : 'Revisa que el servidor siga abierto y vuelve a intentar la subida.';
  ariaStatus.textContent = `${labels[status]}. ${filename.textContent}. ${value}%`;
}

async function pollState() {
  try {
    const response = await fetch(`${config.localUrl}/api/estado?token=${encodeURIComponent(config.token)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Servidor ${response.status}`);
    renderState(await response.json());
  } catch (_) {
    renderState({ estado: 'error', archivo: 'Servidor no disponible', bytes_recibidos: 0, total: 0, mb_s: 0, indice: 0, total_tanda: 0 });
  } finally {
    setTimeout(pollState, 250);
  }
}

function sendMeasuredHeight() {
  desktopBridge.setWindowHeight(document.documentElement.scrollHeight);
}

async function init() {
  config = await desktopBridge.getConfig();
  config.token = new URL(config.publicUrl).searchParams.get('token');
  url.textContent = config.publicUrl;
  qr.alt = `Código QR para abrir ${config.publicUrl}`;
  qr.src = await desktopBridge.makeQrDataUrl(config.publicUrl);
  desktopBridge.onTrayAction(action => {
    if (action !== 'show-qr') return;
    qrCard.classList.add('is-highlighted');
    window.setTimeout(() => qrCard.classList.remove('is-highlighted'), 1800);
  });
  desktopBridge.onServerError(message => renderState({ estado: 'error', archivo: message, bytes_recibidos: 0, total: 0, mb_s: 0, indice: 0, total_tanda: 0 }));
  sendMeasuredHeight();
  new ResizeObserver(sendMeasuredHeight).observe(document.querySelector('#surface'));
  pollState();
}

init().catch(error => renderState({ estado: 'error', archivo: error.message, bytes_recibidos: 0, total: 0, indice: 0, total_tanda: 0 }));
