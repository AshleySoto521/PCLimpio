# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Limpieza del registro: detecta entradas que apuntan a archivos que ya no existen.

Antes de corregir se exporta cada clave afectada a un .reg (se puede restaurar con doble clic o desde la app).
Solo se tocan tipos de entradas seguros: autoarranque huérfano, App Paths, MUICache, DLL compartidas,
carpetas del instalador y desinstaladores sin programa.
"""
import os
import re
import time
import winreg

from . import activity
from .util import BACKUP_DIR, expand, is_admin, log, run

HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
HIVE_NAME = {HKCU: "HKEY_CURRENT_USER", HKLM: "HKEY_LOCAL_MACHINE"}
VIEWS = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)


def exe_from_command(cmd):
    """Extrae la ruta del ejecutable de una línea de comandos del registro ('' si no se puede)."""
    if not cmd:
        return ""
    cmd = expand(cmd.strip())
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        path = cmd[1:end] if end > 0 else cmd[1:]
    else:
        m = re.match(r"(.+?\.(exe|com|bat|cmd|dll|scr|msc|cpl|vbs|ps1))(\s|,|$)", cmd, re.I)
        path = m.group(1) if m else cmd.split(" ")[0]
    name = os.path.basename(path).lower()
    if name in ("rundll32.exe", "rundll32"):
        m = re.search(r"rundll32(?:\.exe)?\"?\s+\"?([^\",]+)", cmd, re.I)
        path = m.group(1).strip() if m else ""
    if name in ("msiexec.exe", "msiexec", "explorer.exe", "cmd.exe", "powershell.exe", "wscript.exe"):
        return ""  # comandos del sistema: no se puede juzgar por el ejecutable
    if path and not os.path.isabs(path):
        return ""  # sin ruta absoluta Windows lo busca en PATH; no lo marcamos como roto
    return path


def _exists(path):
    path = expand(path)
    if os.path.exists(path):
        return True
    # Programas de 32 bits ven System32 redirigido; comprobamos también Sysnative/SysWOW64
    low = path.lower()
    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    for a, b in (("\\system32\\", "\\sysnative\\"), ("\\system32\\", "\\syswow64\\")):
        if low.startswith(windir) and a in low and os.path.exists(low.replace(a, b)):
            return True
    return False


def _values(hive, key, view=0):
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    yield winreg.EnumValue(k, i)
                except OSError:
                    return
                i += 1
    except OSError:
        return


def _subkeys(hive, key, view=0):
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    yield winreg.EnumKey(k, i)
                except OSError:
                    return
                i += 1
    except OSError:
        return


def _get(hive, key, name, view=0):
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


# Cada tipo explicado para cualquier persona: (título, qué es y qué pasa si se quita)
PLAIN_KINDS = [
    ("Inicio:", "Programas de inicio que ya no existen",
     "Windows intenta abrir al encender un programa que ya no está. Quitarlo evita ese intento inútil."),
    ("App Path", "Accesos directos internos a programas borrados",
     "Atajos que Windows guarda para abrir programas que ya desinstalaste. Ya no llevan a ningún lado."),
    ("MUICache", "Nombres guardados de programas que ya no están",
     "Windows recuerda el nombre de programas que abriste alguna vez y ya no existen. Ocupan casi nada; quitarlos solo ordena."),
    ("DLL compartida", "Piezas compartidas que ya no existen",
     "Anotaciones de piezas que varios programas usaban y que ya se borraron. Normalmente vienen de programas muy viejos."),
    ("Carpeta de instalador", "Carpetas de instalación que ya no existen",
     "Windows recuerda carpetas que creó un instalador y que ya no están."),
    ("Desinstalador huérfano", "Programas en la lista de instalados que ya no existen",
     "Aparecen en «Programas instalados», pero sus archivos ya no están, así que no se pueden desinstalar normalmente."),
]


def _plain(kind):
    for prefix, title, what in PLAIN_KINDS:
        if kind.startswith(prefix):
            return title, what
    return kind, ""


def _issue(kind, hive, key, value, target, view=0, delete="value"):
    wow = "\\WOW6432Node" if view == winreg.KEY_WOW64_32KEY and hive == HKLM else ""
    display_key = key.replace("SOFTWARE\\", "SOFTWARE" + wow + "\\", 1) if wow else key
    title, what = _plain(kind)
    return {"id": f"{hive}|{view}|{key}|{value}|{delete}", "kind": kind, "hive": HIVE_NAME[hive],
            "key": display_key, "value": value, "target": target, "admin": hive == HKLM,
            "plain_title": title, "plain_what": what}


def scan(job):
    issues = []
    run_keys = [(HKCU, r"Software\Microsoft\Windows\CurrentVersion\Run"),
                (HKLM, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run")]
    job.update(5, "Programas de inicio")
    for hive, key in run_keys:
        for view in (VIEWS if hive == HKLM else (0,)):
            for name, data, _ in _values(hive, key, view):
                exe = exe_from_command(str(data))
                if exe and not _exists(exe):
                    issues.append(_issue("Inicio: programa inexistente", hive, key, name, exe, view))

    job.update(25, "Rutas de aplicaciones (App Paths)")
    ap = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (HKCU, HKLM):
        for view in (VIEWS if hive == HKLM else (0,)):
            for sub in _subkeys(hive, ap, view):
                target = _get(hive, f"{ap}\\{sub}", "", view)
                exe = exe_from_command(str(target)) if target else ""
                if exe and not _exists(exe):
                    issues.append(_issue("App Path a archivo inexistente", hive, f"{ap}\\{sub}", "", exe, view,
                                         delete="key"))

    job.update(45, "Caché de nombres de programas (MUICache)")
    mui = r"Software\Classes\Local Settings\Software\Microsoft\Windows\Shell\MuiCache"
    for name, _, _ in _values(HKCU, mui):
        path = name.rsplit(".", 1)[0] if name.lower().endswith((".friendlyappname", ".applicationcompany")) else ""
        if path and os.path.isabs(path) and not _exists(path):
            issues.append(_issue("MUICache de programa eliminado", HKCU, mui, name, path))

    job.update(60, "DLL compartidas")
    sd = r"SOFTWARE\Microsoft\Windows\CurrentVersion\SharedDLLs"
    for view in VIEWS:
        for name, _, _ in _values(HKLM, sd, view):
            if os.path.isabs(name) and not _exists(name):
                issues.append(_issue("DLL compartida inexistente", HKLM, sd, name, name, view))

    job.update(70, "Carpetas del instalador")
    inf = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\Folders"
    for name, _, _ in _values(HKLM, inf):
        if os.path.isabs(name) and not _exists(name):
            issues.append(_issue("Carpeta de instalador inexistente", HKLM, inf, name, name))

    job.update(80, "Desinstaladores sin programa")
    un = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (HKCU, HKLM):
        for view in (VIEWS if hive == HKLM else (0,)):
            for sub in _subkeys(hive, un, view):
                k = f"{un}\\{sub}"
                if _get(hive, k, "WindowsInstaller", view) == 1:
                    continue  # los MSI se gestionan con msiexec; no se tocan
                cmd = _get(hive, k, "UninstallString", view)
                loc = _get(hive, k, "InstallLocation", view)
                exe = exe_from_command(str(cmd)) if cmd else ""
                if exe and not _exists(exe) and not (loc and _exists(str(loc))):
                    label = _get(hive, k, "DisplayName", view) or sub
                    issues.append(_issue(f"Desinstalador huérfano: {label}", hive, k, "", exe, view,
                                         delete="key"))
    log.info("Registro: %d problemas encontrados", len(issues))
    _last_ids.clear()
    _last_ids.update(i["id"] for i in issues)
    return {"issues": issues, "admin": is_admin()}


_last_ids = set()  # solo se corrige lo que encontró el último análisis


def _parse_id(issue_id):
    hive, view, key, value, delete = issue_id.split("|", 4)
    return int(hive), int(view), key, value, delete


def fix(job, issue_ids):
    """Exporta cada clave a un .reg y después elimina el valor o la clave."""
    folder = os.path.join(BACKUP_DIR, "registro_" + time.strftime("%Y%m%d_%H%M%S"))
    fixed, failed, exported = [], [], {}
    admin = is_admin()
    for i, iid in enumerate(issue_ids):
        job.update(i * 100 / max(1, len(issue_ids)), "Corrigiendo registro")
        if iid not in _last_ids:
            failed.append({"id": iid, "error": "La entrada no salió en el último análisis; no se toca."})
            continue
        hive, view, key, value, delete = _parse_id(iid)
        if hive == HKLM and not admin:
            failed.append({"id": iid, "error": "Requiere administrador"})
            continue
        full = f"{HIVE_NAME[hive]}\\{key}"
        reg_view = "/reg:32" if view == winreg.KEY_WOW64_32KEY else "/reg:64"
        if (full, reg_view) not in exported:
            os.makedirs(folder, exist_ok=True)  # solo se crea si de verdad se va a corregir algo
            out = os.path.join(folder, f"{len(exported):03d}.reg")
            code, msg = run(["reg", "export", full, out, "/y", reg_view], timeout=60)
            if code != 0:
                failed.append({"id": iid, "error": f"No se pudo respaldar: {msg.strip()}"})
                continue
            exported[(full, reg_view)] = out
        try:
            if delete == "key":
                parent, leaf = key.rsplit("\\", 1)
                with winreg.OpenKey(hive, parent, 0, winreg.KEY_ALL_ACCESS | view) as k:
                    _delete_tree(k, leaf, view)
            else:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE | view) as k:
                    winreg.DeleteValue(k, value)
            fixed.append(iid)
        except OSError as e:
            failed.append({"id": iid, "error": str(e)})
    log.info("Registro corregido: %d, fallidos: %d, respaldo en %s", len(fixed), len(failed), folder)
    if fixed:
        activity.record("Registro de Windows", f"{len(fixed)} entrada(s) rotas corregidas (copia en {folder})",
                        [i.split("|")[2] + (f" → {i.split('|')[3]}" if i.split("|")[3] else "") for i in fixed])
    return {"fixed": len(fixed), "failed": failed, "backup": folder}


def _delete_tree(parent, name, view):
    with winreg.OpenKey(parent, name, 0, winreg.KEY_ALL_ACCESS | view) as k:
        while True:
            try:
                sub = winreg.EnumKey(k, 0)
            except OSError:
                break
            _delete_tree(k, sub, view)
    winreg.DeleteKeyEx(parent, name, view or winreg.KEY_WOW64_64KEY)


def list_backups():
    out = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        p = os.path.join(BACKUP_DIR, name)
        if name.startswith("registro_") and os.path.isdir(p):
            out.append({"name": name, "path": p, "files": len([f for f in os.listdir(p) if f.endswith(".reg")])})
    return out


def restore_backup(name):
    folder = os.path.join(BACKUP_DIR, os.path.basename(name))
    errors = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".reg"):
            code, msg = run(["reg", "import", os.path.join(folder, f)], timeout=60)
            if code != 0:
                errors.append(f"{f}: {msg.strip()}")
    return {"restored": not errors, "errors": errors}
