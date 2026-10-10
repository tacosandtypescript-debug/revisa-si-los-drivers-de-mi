# Transferencia inalámbrica de vídeos del iPhone

Este proyecto incluye un servidor local para seleccionar vídeos desde el navegador del iPhone y subirlos al PC por Wi‑Fi, sin cable USB, además de una pequeña ventana flotante de Electron para supervisar la transferencia.

## Ventana de escritorio

Instala las dependencias y arranca la aplicación:

```powershell
npm install
npm start
```

Después de instalar, también puedes abrir `abrir_iphone_transfer.vbs` con doble clic. El lanzador no abre una consola: inicia directamente la ventana normal de Windows.

La ventana queda encima de las demás, usa la bandeja del sistema y arranca con Windows. El menú de la bandeja permite copiar la URL del iPhone o mostrar el QR.

## Uso

1. Conecta el iPhone y el PC a la misma red Wi‑Fi.
2. Si no usas la ventana de Electron, abre PowerShell en esta carpeta y ejecuta:

   ```powershell
   py .\iphone_transfer_server.py
   ```

3. Desde el menú de la bandeja, elige **Copiar URL del iPhone** o **Mostrar QR**. La URL ya incluye la clave temporal. Si ejecutaste el servidor a mano, usa la IP y la clave que imprime PowerShell. Por ejemplo:

   ```text
   http://IP-DE-LA-PC:8765/?token=CLAVE_TEMPORAL
   ```

4. Desde el iPhone, abre esa URL, pulsa el selector de archivos, elige los vídeos desde Fotos y pulsa **Subir vídeos a la PC**.

Los archivos se guardan en:

```text
%USERPROFILE%\Documents\iPhone_Seleccionados
```

El servidor solo acepta vídeos y está pensado para uso en la red local. No compartas la URL con la clave. Deténlo con `Ctrl+C` cuando termines.

`iphone_backend.ps1` se conserva para las pruebas y el flujo USB legado; el servidor actual no lo necesita para la transferencia por Wi‑Fi.
