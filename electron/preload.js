const { contextBridge, ipcRenderer } = require('electron');
const QRCode = require('qrcode');

contextBridge.exposeInMainWorld('transferDesktop', {
  getConfig: () => ipcRenderer.invoke('get-config'),
  setWindowHeight: height => ipcRenderer.send('window-height', height),
  onTrayAction: callback => ipcRenderer.on('tray-action', (_event, action) => callback(action)),
  onServerError: callback => ipcRenderer.on('server-error', (_event, message) => callback(message)),
  makeQrDataUrl: text => QRCode.toDataURL(text, {
    width: 58,
    margin: 1,
    errorCorrectionLevel: 'M',
    color: { dark: '#F3F8FF', light: '#0D121BE6' },
  }),
});
