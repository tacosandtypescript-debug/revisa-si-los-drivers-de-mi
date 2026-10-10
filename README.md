# Transferencia inalámbrica de vídeos del iPhone

Este servidor local permite seleccionar vídeos desde el navegador del iPhone y subirlos al PC por Wi‑Fi, sin cable USB.

## Uso

1. Conecta el iPhone y el PC a la misma red Wi‑Fi.
2. En el PC, abre PowerShell en esta carpeta y ejecuta:

   ```powershell
   py .\iphone_transfer_server.py
   ```

3. Usa la IP Wi-Fi del PC y la clave temporal que aparecen en la ventana. Por ejemplo:

   ```text
   http://IP-DE-LA-PC:8765/?token=CLAVE_TEMPORAL
   ```

4. Desde el iPhone, abre esa URL, pulsa el selector de archivos, elige los vídeos desde Fotos y pulsa **Subir vídeos a la PC**.

Los archivos se guardan en:

```text
%USERPROFILE%\Documents\iPhone_Seleccionados
```

El servidor solo acepta vídeos y está pensado para uso en la red local. No compartas la URL con la clave. Deténlo con `Ctrl+C` cuando termines.
