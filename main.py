# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""PCLimpio — mantenimiento de Windows 100 % local.

Uso:
    python main.py                 abre la aplicación
    python main.py --auto-history  limpieza de historial programada (sin ventana)
    python main.py --no-window     solo arranca el servidor e imprime la URL
    PCLimpio.exe --no-window --url-file ruta.txt   igual, pero guarda la URL en un archivo (pruebas del .exe)
"""
import os
import secrets
import subprocess
import sys
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import history, server  # noqa: E402
from core.util import DATA_DIR, log  # noqa: E402

EDGE_PATHS = [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
              r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"]


def open_window(url):
    """Abre la interfaz como ventana de aplicación de Edge (perfil propio, sin barra de direcciones)."""
    for p in EDGE_PATHS:
        exe = os.path.expandvars(p)
        if os.path.exists(exe):
            profile = os.path.join(DATA_DIR, "ventana")
            subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1280,820",
                              "--no-first-run", "--no-default-browser-check"])
            return
    webbrowser.open(url)


def main():
    if "--auto-history" in sys.argv:
        result = history.clean()
        log.info("Limpieza automática del historial: %s", result)
        return
    token = secrets.token_urlsafe(24)
    httpd, port = server.serve(token)
    url = f"http://127.0.0.1:{port}/#t={token}"
    log.info("PCLimpio iniciado en el puerto %d", port)
    if "--no-window" in sys.argv:
        if sys.stdout:  # en el .exe sin consola no hay salida estándar
            print(url, flush=True)
        if "--url-file" in sys.argv:  # para pruebas automáticas del .exe
            with open(sys.argv[sys.argv.index("--url-file") + 1], "w", encoding="utf-8") as f:
                f.write(url)
    else:
        open_window(url)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
