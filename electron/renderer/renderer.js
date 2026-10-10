const desktopBridge = window.transferDesktop;

const ringProgress = document.querySelector('#ring-progress');
const percent = document.querySelector('#percent');
const qr = document.querySelector('#qr');
const filename = document.querySelector('#filename');
const speed = document.querySelector('#speed');
const counter = document.querySelector('#counter');
const url = document.querySelector('#url');
const circumference = 2 * Math.PI * 24;
let config = null;
let lastState = { estado: 'reposo' };
let showQrUntil = 0;

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
  ringProgress.style.strokeDashoffset = String(circumference - (circumference * value / 100));
  percent.textContent = `${value}%`;
  filename.textContent = status === 'reposo' ? 'Listo' : (lastState.archivo || 'Transferencia');
  speed.textContent = status === 'reposo' ? '' : `${Number(lastState.mb_s || 0).toFixed(1)} MB/s`;
  counter.textContent = status === 'reposo' ? '' : `${lastState.indice || 0} de ${lastState.total_tanda || 0}`;
  qr.classList.toggle('visible', status === 'reposo' || Date.now() < showQrUntil);
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
  url.textContent = `http://${config.ip}:${config.port}`;
  qr.src = await desktopBridge.makeQrDataUrl(config.publicUrl);
  desktopBridge.onTrayAction(action => {
    if (action !== 'show-qr') return;
    showQrUntil = Date.now() + 8000;
    renderState(lastState);
    setTimeout(() => renderState(lastState), 8100);
  });
  desktopBridge.onServerError(message => renderState({ estado: 'error', archivo: message, bytes_recibidos: 0, total: 0, mb_s: 0, indice: 0, total_tanda: 0 }));
  sendMeasuredHeight();
  new ResizeObserver(sendMeasuredHeight).observe(document.querySelector('#surface'));
  pollState();
}

init().catch(error => renderState({ estado: 'error', archivo: error.message, bytes_recibidos: 0, total: 0, indice: 0, total_tanda: 0 }));
