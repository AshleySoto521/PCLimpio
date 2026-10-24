# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Limpiador automático del historial: navegadores y rastros de Windows, manual o programado.

Chromium (Chrome, Edge, Brave, Opera, Vivaldi): se borran los archivos de historial del perfil.
Firefox: places.sqlite también guarda los marcadores, así que se vacía con SQL conservando los marcadores.
La programación usa el Programador de tareas de Windows con una tarea del usuario actual.
"""
import json
import os
import sqlite3
import winreg

from . import activity, browsers, safety
from .util import DATA_DIR, app_command, log, remove_file, run, running_processes

SETTINGS = os.path.join(DATA_DIR, "historial.json")
TASK_NAME = "PCLimpio\\LimpiezaHistorial"

ITEMS = {
    "history": "Páginas que visitaste y lista de descargas (los archivos descargados no se borran)",
    "cookies": "Sesiones abiertas en webs (tendrás que volver a entrar en tus cuentas)",
    "forms": "Lo que escribiste en formularios: nombres, correos… (no borra contraseñas)",
    "session": "Pestañas que tenías abiertas la última vez",
    "cache": "Páginas guardadas para cargar más rápido",
}

ITEMS_SHORT = {"history": "historial", "cookies": "sesiones", "forms": "formularios", "session": "pestañas",
               "cache": "páginas guardadas"}

CHROMIUM_FILES = {
    "history": ["History", "History-journal", "Visited Links", "Top Sites", "Top Sites-journal", "Shortcuts",
                "Shortcuts-journal", "Network Action Predictor", "Network Action Predictor-journal"],
    "cookies": ["Network\\Cookies", "Network\\Cookies-journal", "Cookies", "Cookies-journal"],
    "session": ["Current Session", "Current Tabs", "Last Session", "Last Tabs", "Sessions"],
    "cache": ["Cache", "Code Cache", "GPUCache"],
}

WINDOWS_ITEMS = {
    "run_mru": ("Comandos que escribiste en «Ejecutar» (Windows + R)", r"Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU"),
    "typed_paths": ("Direcciones que escribiste en el Explorador de archivos", r"Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths"),
    "recent_docs": ("Lista de documentos que abriste hace poco (tus documentos no se borran)", r"Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs"),
}

DEFAULT_SETTINGS = {"browsers": {}, "items": ["history", "cache"], "windows": [],
                    "schedule": {"enabled": False, "frequency": "DAILY", "time": "21:00"}}


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def save_settings(s):
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def _path_size(p):
    if os.path.isfile(p):
        return os.path.getsize(p)
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _chromium_paths(profile_data, profile_cache, item):
    base = profile_cache if item == "cache" else profile_data
    return [os.path.join(base, f) for f in CHROMIUM_FILES.get(item, []) if os.path.exists(os.path.join(base, f))]


def status():
    """Navegadores encontrados, si están abiertos y cuánto ocupa cada elemento."""
    procs = running_processes()
    s = load_settings()
    out = []
    for b in browsers.installed():
        items = {}
        for item in ITEMS:
            size = 0
            for data, cache in b["profiles"]:
                if b["kind"] == "chromium":
                    if item == "forms":
                        size += _path_size(os.path.join(data, "Web Data")) if os.path.exists(
                            os.path.join(data, "Web Data")) else 0
                    else:
                        size += sum(_path_size(p) for p in _chromium_paths(data, cache, item))
                else:
                    size += sum(_path_size(os.path.join(d, f)) for d, f in _firefox_files(data, cache, item)
                                if os.path.exists(os.path.join(d, f)))
            items[item] = size
        out.append({"id": b["id"], "name": b["name"], "running": b["process"] in procs,
                    "profiles": len(b["profiles"]), "sizes": items,
                    "enabled": s["browsers"].get(b["id"], True)})
    return {"browsers": out, "items": ITEMS,
            "windows": {k: v[0] for k, v in WINDOWS_ITEMS.items()}, "settings": s,
            "task": task_status()}


def _firefox_files(data, cache, item):
    return {
        "history": [],  # se limpia por SQL en places.sqlite
        "cookies": [(data, "cookies.sqlite"), (data, "cookies.sqlite-wal")],
        "forms": [(data, "formhistory.sqlite")],
        "session": [(data, "sessionstore.jsonlz4"), (data, "sessionstore-backups")],
        "cache": [(cache, "cache2")],
    }[item]


def _clear_firefox_history(profile):
    db = os.path.join(profile, "places.sqlite")
    if not os.path.exists(db):
        return 0
    before = os.path.getsize(db)
    con = sqlite3.connect(db, timeout=5)
    try:
        con.executescript("""
            DELETE FROM moz_historyvisits;
            DELETE FROM moz_inputhistory;
            DELETE FROM moz_annos WHERE place_id NOT IN (SELECT fk FROM moz_bookmarks WHERE fk IS NOT NULL);
            DELETE FROM moz_places WHERE id NOT IN (SELECT fk FROM moz_bookmarks WHERE fk IS NOT NULL);
            UPDATE moz_places SET visit_count = 0, last_visit_date = NULL, frecency = 0;
        """)
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()
    return max(0, before - os.path.getsize(db))


def _clear_chromium_forms(profile):
    db = os.path.join(profile, "Web Data")
    if not os.path.exists(db):
        return 0
    con = sqlite3.connect(db, timeout=5)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("autofill", "autofill_model_type_state"):
            if t in tables:
                con.execute(f"DELETE FROM {t}")  # solo autocompletar; no toca tarjetas ni direcciones
        con.commit()
    finally:
        con.close()
    return 0


def _delete(path):
    """Borra un archivo o carpeta de datos del navegador. Pasa por safety (lanza Blocked si es del sistema)."""
    if not safety.allow_cleanup_zone(path):
        raise safety.Blocked(f"{path}: {safety.check_path(path)[1]}")
    if os.path.isdir(path):
        freed = 0
        for root, _, files in os.walk(path, topdown=False):
            for f in files:
                freed += remove_file(os.path.join(root, f)) or 0
            if safety.check_path(root, is_dir=True)[0]:
                try:
                    os.rmdir(root)
                except OSError:
                    pass
        return freed
    return remove_file(path) or 0


def _clear_windows_item(key):
    _, sub = WINDOWS_ITEMS[key]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_ALL_ACCESS) as k:
            names = []
            i = 0
            while True:
                try:
                    names.append(winreg.EnumValue(k, i)[0])
                except OSError:
                    break
                i += 1
            for n in names:
                winreg.DeleteValue(k, n)
        return True
    except OSError:
        return False


def clean(job=None, browser_ids=None, items=None, windows=None, close_browsers=False):
    s = load_settings()
    items = items if items is not None else s["items"]
    windows = windows if windows is not None else s["windows"]
    found = browsers.installed()
    if browser_ids is None:
        browser_ids = [b["id"] for b in found if s["browsers"].get(b["id"], True)]
    procs = running_processes()
    report = []
    for b in [b for b in found if b["id"] in browser_ids]:
        if job:
            job.update(None, f"Limpiando {b['name']}")
        if b["process"] in procs:
            if close_browsers:
                from .util import close_processes
                close_processes([b["process"]])
            else:
                report.append({"browser": b["name"], "skipped": "El navegador está abierto"})
                continue
        freed, errors = 0, []
        for data, cache in b["profiles"]:
            for item in items:
                try:
                    if b["kind"] == "chromium":
                        if item == "forms":
                            _clear_chromium_forms(data)
                        else:
                            for p in _chromium_paths(data, cache, item):
                                freed += _delete(p)
                    else:
                        if item == "history":
                            freed += _clear_firefox_history(data)
                        for d, f in _firefox_files(data, cache, item):
                            if os.path.exists(os.path.join(d, f)):
                                freed += _delete(os.path.join(d, f))
                except (OSError, sqlite3.Error) as e:  # incluye safety.Blocked

                    errors.append(f"{item}: {e}")
        report.append({"browser": b["name"], "freed": freed, "errors": errors})
    win_done = [WINDOWS_ITEMS[k][0] for k in windows if k in WINDOWS_ITEMS and _clear_windows_item(k)]
    log.info("Historial limpiado: %s; Windows: %s", report, win_done)
    activity.record("Historial del navegador",
                    f"Limpieza del navegador ({', '.join(ITEMS_SHORT[i] for i in items if i in ITEMS_SHORT)})",
                    [f"{r['browser']}: {r.get('skipped') or 'limpiado'}" for r in report] + win_done,
                    sum(r.get("freed", 0) for r in report))
    return {"browsers": report, "windows": win_done}


# ---------------------------------------------------------------- programación

def _launcher_command():
    exe, args = app_command("--auto-history")
    return " ".join(f'"{a}"' if " " in a or a.endswith((".py", ".exe")) else a for a in [exe, *args])


def task_status():
    code, out = run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"], timeout=30)
    return {"exists": code == 0, "detail": out.strip() if code == 0 else ""}


def set_schedule(enabled, frequency="DAILY", at="21:00"):
    s = load_settings()
    s["schedule"] = {"enabled": enabled, "frequency": frequency, "time": at}
    save_settings(s)
    if not enabled:
        run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], timeout=30)
        return {"ok": True, "message": "Limpieza automática desactivada"}
    cmd = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", _launcher_command(), "/SC", frequency, "/ST", at]
    if frequency == "WEEKLY":
        cmd += ["/D", "SUN"]
    code, out = run(cmd, timeout=30)
    return {"ok": code == 0, "message": out.strip()}
