# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Servidor HTTP local (solo 127.0.0.1) que une la interfaz con los módulos.

Seguridad: cada petición a /api debe traer el token aleatorio generado al arrancar y el Host debe ser
127.0.0.1:<puerto>; así ninguna web abierta en el navegador puede llamar a la API.
"""
import json
import mimetypes
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (activity, analyzer, cleaning, drivers, history, jobs, optimizer, recovery, registry_clean, safety,
               software, sysinfo)
from .util import (CREATE_NO_WINDOW, DATA_DIR, LOG_DIR, close_processes, is_admin, list_drives, log, resource_path,
                   recycle_bin_info, relaunch_as_admin)

UI_DIR = os.path.normpath(resource_path("ui"))
from .version import AUTHOR, COPYRIGHT, LICENSE, REPO_URL, VERSION  # noqa: E402


def job(kind, fn, *args, **kwargs):
    return {"job": jobs.start(kind, fn, *args, **kwargs).to_dict()}


def _closable():
    names = {p for r in cleaning.all_rules() for p in r.get("processes", [])}
    names |= {b["process"] for b in history.browsers.installed()}
    return names


def _open_folder(path):
    path = os.path.abspath(path)
    if os.path.isfile(path):
        subprocess.Popen(["explorer", "/select,", path], creationflags=CREATE_NO_WINDOW)
    elif os.path.isdir(path):
        subprocess.Popen(["explorer", path], creationflags=CREATE_NO_WINDOW)
    return {"ok": True}


def _toggle(b):
    if not optimizer.known_component(b["id"]):
        raise ValueError("Componente desconocido; vuelve a analizar")
    optimizer.set_component(b["id"], bool(b["enabled"]))
    return {"ok": True}


ROUTES = {
    # general
    "status": lambda b: {"admin": is_admin(), "version": VERSION, "data_dir": DATA_DIR, "author": AUTHOR,
                         "copyright": COPYRIGHT, "license": LICENSE, "repo": REPO_URL},
    "home": lambda b: {"drives": list_drives(), "recycle": dict(zip(("bytes", "items"), recycle_bin_info())),
                       "admin": is_admin()},
    "elevate": lambda b: {"ok": relaunch_as_admin()},
    "heartbeat": lambda b: {"ok": True},
    "open-folder": lambda b: _open_folder(b["path"]),
    "logs": lambda b: _open_folder(LOG_DIR),
    "close-processes": lambda b: {"ok": close_processes([p for p in b["processes"] if p in _closable()])},
    "safety/check": lambda b: dict(zip(("ok", "reason"), safety.check_path(b["path"]))),
    "safety/rules": lambda b: {"untouchable": [{"path": p, "reason": r} for p, r in safety.UNTOUCHABLE]},
    "activity/list": lambda b: {"entries": activity.read(int(b.get("limit", 300)))},
    "activity/open": lambda b: _open_folder(activity.FILE),
    "jobs/get": lambda b: (jobs.get(b["id"]) or _missing()).to_dict(),
    "jobs/cancel": lambda b: ((jobs.get(b["id"]) or _missing()).cancel(), {"ok": True})[1],
    # limpieza básica / avanzada
    "cleaning/rules": lambda b: {"rules": cleaning.rules_for_ui(b.get("level")), "admin": is_admin()},
    "cleaning/analyze": lambda b: job("cleaning-analyze", cleaning.analyze, b["ids"]),
    "cleaning/clean": lambda b: job("cleaning-clean", cleaning.clean, b["ids"]),
    "registry/scan": lambda b: job("registry-scan", registry_clean.scan),
    "registry/fix": lambda b: job("registry-fix", registry_clean.fix, b["ids"]),
    "registry/backups": lambda b: {"backups": registry_clean.list_backups()},
    "registry/restore": lambda b: registry_clean.restore_backup(b["name"]),
    # historial
    "history/status": lambda b: history.status(),
    "history/save": lambda b: (history.save_settings({**history.load_settings(), **b["settings"]}), {"ok": True})[1],
    "history/clean": lambda b: job("history-clean", history.clean, b.get("browsers"), b.get("items"),
                                   b.get("windows"), bool(b.get("close"))),
    "history/schedule": lambda b: history.set_schedule(bool(b["enabled"]), b.get("frequency", "DAILY"),
                                                       b.get("time", "21:00")),
    # analizador de disco
    "analyzer/drives": lambda b: {"drives": analyzer.drives()},
    "analyzer/scan": lambda b: job("analyzer-scan", analyzer.scan, b["items"], b.get("opts", {})),
    "analyzer/delete": lambda b: job("analyzer-delete", analyzer.delete, b["paths"], bool(b.get("permanent"))),
    # optimizador
    "optimizer/overview": lambda b: job("optimizer-overview", optimizer.overview),
    "optimizer/toggle": _toggle,
    "optimizer/sleep": lambda b: optimizer.sleep_app(b["name"]),
    "optimizer/wake": lambda b: optimizer.wake_app(b["name"]),
    "optimizer/processes": lambda b: {"processes": optimizer.processes()},
    "optimizer/kill": lambda b: optimizer.end_process(b["name"]),
    "optimizer/power": lambda b: {"plans": optimizer.power_plans()},
    "optimizer/power-set": lambda b: optimizer.set_power_plan(b["guid"]),
    # controladores
    "drivers/inventory": lambda b: job("drivers-inventory", drivers.inventory),
    "drivers/search": lambda b: job("drivers-search", drivers.search_updates),
    "drivers/install": lambda b: job("drivers-install", drivers.install_updates, b["ids"],
                                     bool(b.get("restore", True)), bool(b.get("backup", True))),
    "drivers/backup": lambda b: job("drivers-backup", drivers.backup_drivers),
    # software
    "software/check": lambda b: job("software-check", software.check_updates),
    "software/update": lambda b: job("software-update", software.install_updates, b["ids"]),
    "software/programs": lambda b: job("software-programs", software.installed_programs),
    "software/uninstall": lambda b: software.uninstall(b["id"]),
    # recuperación
    "recovery/bin": lambda b: recovery.recycle_bin_items(),
    "recovery/restore": lambda b: recovery.restore_from_bin(b["ids"]),
    "recovery/scan": lambda b: job("recovery-scan", recovery.deep_scan, b["letter"]),
    "recovery/results": lambda b: recovery.deep_results(b.get("text", ""), b.get("category", ""),
                                                        b.get("state", ""), int(b.get("limit", 1000)),
                                                        int(b.get("min_size", 0))),
    "recovery/recover": lambda b: job("recovery-recover", recovery.recover, b["ids"], b["dest"]),
    # información del sistema
    "sysinfo/collect": lambda b: job("sysinfo", sysinfo.collect),
    "sysinfo/export": lambda b: {"path": sysinfo.export_html(b["data"])},
}


def _missing():
    raise KeyError("Tarea no encontrada")


class Handler(BaseHTTPRequestHandler):
    token = ""
    port = 0
    last_seen = time.time()

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _host_ok(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "Host no permitido"})
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(UI_DIR, path.lstrip("/")))
        if not full.startswith(UI_DIR) or not os.path.isfile(full):
            return self._send(404, {"error": "No encontrado"})
        with open(full, "rb") as f:
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, f.read(), ctype)

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != self.token:
            return self._send(403, {"error": "No autorizado"})
        Handler.last_seen = time.time()
        route = self.path.split("?", 1)[0].removeprefix("/api/")
        fn = ROUTES.get(route)
        if not fn:
            return self._send(404, {"error": f"Ruta desconocida: {route}"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, fn(body))
        except safety.Blocked as e:
            log.warning("Bloqueado por protección del sistema en %s: %s", route, e)
            self._send(403, {"error": f"Protección del sistema — {e}", "blocked": True})
        except PermissionError as e:
            self._send(403, {"error": str(e) or "Se necesitan permisos de administrador"})
        except (KeyError, ValueError, OSError, RuntimeError) as e:
            log.warning("Error en %s: %s", route, e)
            self._send(400, {"error": str(e)})


def serve(token, port=0, idle_timeout=90):
    """Arranca el servidor y devuelve (servidor, puerto). Se apaga solo si la ventana deja de dar señal."""
    Handler.token = token
    cleaning.all_rules()  # declara desde el inicio las zonas de limpieza (cachés de navegadores, etc.)
    httpd =ThreadingHTTPServer(("127.0.0.1", port), Handler)
    Handler.port = httpd.server_address[1]
    Handler.last_seen = time.time() + 60  # margen para que abra la ventana

    def watchdog():
        while True:
            time.sleep(5)
            if time.time() - Handler.last_seen > idle_timeout and not jobs.any_running():
                log.info("Sin actividad de la interfaz; cerrando servidor")
                httpd.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    return httpd, Handler.port
