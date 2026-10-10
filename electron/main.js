const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  clipboard,
  nativeImage,
  screen,
  ipcMain,
} = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');

const PORT = 8765;
const WINDOW_WIDTH = 160;
const INITIAL_WINDOW_HEIGHT = 130;
const PROJECT_ROOT = path.resolve(__dirname, '..');
const SERVER_SCRIPT = path.join(PROJECT_ROOT, 'iphone_transfer_server.py');
const WINDOW_STATE_PATH = path.join(app.getPath('userData'), 'window-state.json');
const CAPTURE_PATH = process.argv.includes('--capture') ? path.join(PROJECT_ROOT, 'verification', 'overlay.png') : null;

let mainWindow = null;
let tray = null;
let serverProcess = null;
let isQuitting = false;
let savePositionTimer = null;
const authToken = crypto.randomBytes(24).toString('base64url');
const lanIp = detectLanIp();
const publicUrl = `http://${lanIp}:${PORT}/?token=${encodeURIComponent(authToken)}`;
const localUrl = `http://127.0.0.1:${PORT}`;

function isPrivateIpv4(address) {
  const parts = address.split('.').map(Number);
  return parts.length === 4 && (
    parts[0] === 10 ||
    (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31) ||
    (parts[0] === 192 && parts[1] === 168)
  );
}

function detectLanIp() {
  const interfaces = os.networkInterfaces();
  const candidates = [];
  for (const [name, values] of Object.entries(interfaces)) {
    for (const value of values || []) {
      if (value.family === 'IPv4' && !value.internal && isPrivateIpv4(value.address)) {
        candidates.push({ name: name.toLowerCase(), address: value.address });
      }
    }
  }
  candidates.sort((a, b) => {
    const aPreferred = /wi-?fi|wlan|wireless/.test(a.name) ? 0 : 1;
    const bPreferred = /wi-?fi|wlan|wireless/.test(b.name) ? 0 : 1;
    return aPreferred - bPreferred;
  });
  return candidates[0]?.address || '127.0.0.1';
}

function readWindowPosition() {
  try {
    const saved = JSON.parse(fs.readFileSync(WINDOW_STATE_PATH, 'utf8'));
    if (Number.isFinite(saved.x) && Number.isFinite(saved.y)) return { x: saved.x, y: saved.y };
  } catch (_) {
    // A missing or stale state file is normal on first launch.
  }
  const workArea = screen.getPrimaryDisplay().workArea;
  return {
    x: Math.round(workArea.x + workArea.width - WINDOW_WIDTH - 28),
    y: Math.round(workArea.y + workArea.height - INITIAL_WINDOW_HEIGHT - 28),
  };
}

function saveWindowPosition() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  clearTimeout(savePositionTimer);
  savePositionTimer = setTimeout(() => {
    try {
      const bounds = mainWindow.getBounds();
      fs.mkdirSync(path.dirname(WINDOW_STATE_PATH), { recursive: true });
      fs.writeFileSync(WINDOW_STATE_PATH, JSON.stringify({ x: bounds.x, y: bounds.y }), 'utf8');
    } catch (_) {
      // Position persistence is best-effort and must not interrupt transfers.
    }
  }, 200);
}

function makeTrayIcon() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    <circle cx="16" cy="16" r="11" fill="none" stroke="#67b8ff" stroke-width="4"/>
    <circle cx="16" cy="16" r="3" fill="#f3f8ff"/>
  </svg>`;
  const encoded = Buffer.from(svg).toString('base64');
  return nativeImage.createFromDataURL(`data:image/svg+xml;base64,${encoded}`).resize({ width: 16, height: 16 });
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.show();
  mainWindow.focus();
}

function toggleWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isVisible()) mainWindow.hide();
  else showWindow();
}

function createTray() {
  tray = new Tray(makeTrayIcon());
  tray.setToolTip('iPhone Wi-Fi Transfer');
  tray.on('click', toggleWindow);
  const menu = Menu.buildFromTemplate([
    {
      label: 'Copiar URL del iPhone',
      click: () => clipboard.writeText(publicUrl),
    },
    {
      label: 'Mostrar QR',
      click: () => {
        showWindow();
        mainWindow?.webContents.send('tray-action', 'show-qr');
      },
    },
    { type: 'separator' },
    {
      label: 'Cerrar',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(menu);
}

function createWindow() {
  const position = readWindowPosition();
  mainWindow = new BrowserWindow({
    x: position.x,
    y: position.y,
    width: WINDOW_WIDTH,
    height: INITIAL_WINDOW_HEIGHT,
    useContentSize: true,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    minimizable: false,
    maximizable: false,
    skipTaskbar: true,
    show: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  mainWindow.setAlwaysOnTop(true, 'screen-saver');
  mainWindow.setMenuBarVisibility(false);
  mainWindow.on('move', saveWindowPosition);
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  mainWindow.once('ready-to-show', () => {
    showWindow();
    if (CAPTURE_PATH) {
      setTimeout(captureWindowForQa, 900);
    }
  });
}

async function captureWindowForQa() {
  if (!mainWindow || mainWindow.isDestroyed() || !CAPTURE_PATH) return;
  try {
    const image = await mainWindow.webContents.capturePage();
    fs.mkdirSync(path.dirname(CAPTURE_PATH), { recursive: true });
    fs.writeFileSync(CAPTURE_PATH, image.toPNG());
  } finally {
    isQuitting = true;
    app.quit();
  }
}

function startServer() {
  serverProcess = spawn('py', [
    SERVER_SCRIPT,
    '--host', '0.0.0.0',
    '--port', String(PORT),
    '--token', authToken,
  ], {
    cwd: PROJECT_ROOT,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  serverProcess.stdout.on('data', data => console.log(`[server] ${data}`.trimEnd()));
  serverProcess.stderr.on('data', data => console.error(`[server] ${data}`.trimEnd()));
  serverProcess.on('error', error => mainWindow?.webContents.send('server-error', error.message));
  serverProcess.on('exit', (code, signal) => {
    if (!isQuitting) mainWindow?.webContents.send('server-error', `El servidor se cerró (${code ?? signal}).`);
  });
}

function stopServer() {
  if (serverProcess && !serverProcess.killed) serverProcess.kill();
  serverProcess = null;
}

function registerIpc() {
  ipcMain.handle('get-config', () => ({
    localUrl,
    publicUrl,
    ip: lanIp,
    port: PORT,
  }));
  ipcMain.on('window-height', (_event, rawHeight) => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    const height = Math.max(110, Math.min(170, Math.ceil(Number(rawHeight) || INITIAL_WINDOW_HEIGHT)));
    mainWindow.setContentSize(WINDOW_WIDTH, height, false);
  });
}

function configureStartup() {
  app.setLoginItemSettings({
    openAtLogin: true,
    path: process.execPath,
    args: app.isPackaged ? [] : [PROJECT_ROOT],
  });
}

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) {
  app.quit();
} else {
  app.on('second-instance', () => showWindow());
  app.whenReady().then(() => {
    app.setAppUserModelId('com.isaac.iphonewifitransfer');
    registerIpc();
    configureStartup();
    startServer();
    createWindow();
    createTray();
  });
  app.on('before-quit', () => {
    isQuitting = true;
    saveWindowPosition();
    stopServer();
    tray?.destroy();
  });
  app.on('window-all-closed', event => event.preventDefault());
}
