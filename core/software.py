# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Actualizador de software (winget, el gestor de paquetes de Windows) y desinstalador de programas.

El tamaño de cada programa se calcula como CCleaner: EstimatedSize del registro y, si falta,
sumando la carpeta InstallLocation.
"""
import os
import re
import subprocess
import winreg

from . import activity, safety
from .util import CREATE_NO_WINDOW, as_list, log, run, run_ps

WINGET_FLAGS = ["--accept-source-agreements", "--disable-interactivity"]


def parse_winget_table(text):
    """Convierte la tabla de 'winget upgrade' en una lista de dicts (independiente del idioma)."""
    lines = [l.split("\r")[-1].rstrip() for l in text.splitlines()]
    rows = []
    for i, line in enumerate(lines):
        if i > 0 and re.fullmatch(r"-{10,}", line.strip()):
            header = lines[i - 1]
            starts = [m.start() for m in re.finditer(r"\S+", header)]
            if len(starts) < 4:
                continue
            for row in lines[i + 1:]:
                if not row.strip() or len(row) < starts[2] or re.fullmatch(r"-{10,}", row.strip()):
                    break
                cols = [row[s:e].strip() for s, e in zip(starts, starts[1:] + [None])]
                if len(cols) >= 4 and cols[1] and " " not in cols[1]:
                    rows.append({"name": cols[0], "id": cols[1], "version": cols[2], "available": cols[3],
                                 "source": cols[4] if len(cols) > 4 else ""})
    return rows


def check_updates(job):
    job.update(10, "Consultando winget")
    code, out = run(["winget", "upgrade", "--include-unknown", *WINGET_FLAGS], timeout=600)
    if code not in (0, -1978335212) and "winget" not in out.lower():  # sin actualizaciones también es válido
        raise RuntimeError("winget no está disponible en este equipo")
    return {"updates": parse_winget_table(out)}


def install_updates(job, ids):
    results = []
    for i, pid in enumerate(ids):
        if not re.fullmatch(r"[\w.+\-]+", pid):
            results.append({"id": pid, "ok": False, "message": "Id inválido"})
            continue
        job.update(i * 100 / max(1, len(ids)), f"Actualizando {pid} ({i + 1}/{len(ids)})")
        code, out = run(["winget", "upgrade", "--id", pid, "--exact", "--silent",
                         "--accept-package-agreements", *WINGET_FLAGS], timeout=1800)
        tail = [l.split("\r")[-1].strip() for l in out.splitlines() if l.strip()]
        results.append({"id": pid, "ok": code == 0, "message": tail[-1] if tail else ""})
    log.info("Actualizaciones de software: %s", results)
    activity.record("Actualizador de software", f"{sum(r['ok'] for r in results)} programa(s) actualizados",
                    [f"{r['id']}: {'actualizado' if r['ok'] else 'error'}" for r in results])
    return {"results": results}


# ---------------------------------------------------------------- desinstalador

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def _dir_size(path, limit_files=200000):
    total = n = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
            n += 1
            if n > limit_files:
                return total
    return total


def _read(k, name):
    try:
        return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def installed_programs(job):
    seen, out = set(), []
    sources = [(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "Todos"),
               (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "Todos (32 bits)"),
               (winreg.HKEY_CURRENT_USER, 0, "Usuario")]
    job.update(5, "Leyendo programas instalados")
    for hive, view, scope in sources:
        try:
            root = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = _read(k, "DisplayName")
                        if not name or _read(k, "SystemComponent") == 1 or _read(k, "ParentKeyName"):
                            continue
                        uninstall = _read(k, "UninstallString")
                        if not uninstall:
                            continue
                        key = (name.lower(), (_read(k, "DisplayVersion") or ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        est = _read(k, "EstimatedSize")
                        out.append({"id": f"{hive}|{view}|{sub}", "name": name, "publisher": _read(k, "Publisher") or "",
                                    "version": _read(k, "DisplayVersion") or "", "date": _read(k, "InstallDate") or "",
                                    "location": (_read(k, "InstallLocation") or "").strip('"'),
                                    "size": int(est) * 1024 if isinstance(est, int) else None,
                                    "uninstall": uninstall, "quiet": _read(k, "QuietUninstallString") or "",
                                    "scope": scope, "kind": "Win32"})
                except OSError:
                    continue
    job.update(40, "Calculando tamaños que faltan")
    missing = [p for p in out if p["size"] is None and p["location"] and os.path.isdir(p["location"])]
    for n, p in enumerate(missing):
        job.update(40 + 40 * n / max(1, len(missing)), f"Midiendo {p['name']}")
        p["size"] = _dir_size(p["location"])
    job.update(85, "Aplicaciones de Microsoft Store")
    store = as_list(run_ps(
        "Get-AppxPackage | Where-Object { -not $_.IsFramework -and $_.SignatureKind -eq 'Store' } | ForEach-Object { "
        "[pscustomobject]@{ full=$_.PackageFullName; name=$_.Name; version=[string]$_.Version; "
        "publisher=$_.PublisherId; location=$_.InstallLocation } }", timeout=120))
    for s in store:
        loc = s.get("location") or ""
        out.append({"id": f"appx|{s['full']}", "name": s["name"], "publisher": s.get("publisher") or "",
                    "version": s.get("version") or "", "date": "", "location": loc,
                    "size": _dir_size(loc) if loc and os.path.isdir(loc) else None,
                    "uninstall": "", "quiet": "", "scope": "Usuario", "kind": "Store"})
    for p in out:
        ok, why = safety.check_program(p["name"], p["publisher"], p["location"])
        p["protected"] = None if ok else why
    out.sort(key=lambda p: p["size"] or 0, reverse=True)
    return {"programs": out}


def uninstall(program_id):
    """Lanza el desinstalador del programa (interactivo, como hace Windows).

    El comando se vuelve a leer del registro a partir del id; nunca se ejecuta texto enviado por la interfaz.
    """
    if program_id.startswith("appx|"):
        full = program_id.split("|", 1)[1]
        if not re.fullmatch(r"[\w.\-~]+", full):
            raise ValueError("Paquete inválido")
        ok, why = safety.check_program(full.split("_", 1)[0])
        if not ok:
            raise safety.Blocked(f"No se puede desinstalar {full}: {why}")
        code, out = run(["powershell", "-NoProfile", "-Command", f"Remove-AppxPackage -Package '{full}'"],
                        timeout=600)
        if code == 0:
            activity.record("Programas instalados", f"Aplicación de la Tienda desinstalada: {full}")
        return {"ok": code == 0, "message": out.strip()}
    hive, view, sub = program_id.split("|", 2)
    with winreg.OpenKey(int(hive), f"{UNINSTALL}\\{sub}", 0, winreg.KEY_READ | int(view)) as k:
        cmd = _read(k, "UninstallString") or ""
        name = _read(k, "DisplayName") or sub
        location = (_read(k, "InstallLocation") or "").strip('"')
        publisher = _read(k, "Publisher") or ""
    ok, why = safety.check_program(name, publisher, location)
    if not ok:
        raise safety.Blocked(f"No se puede desinstalar {name}: {why}")
    if not cmd:
        raise ValueError("El programa no tiene desinstalador registrado")
    if re.match(r'(?i)^\s*"?msiexec(\.exe)?"?\s+/i', cmd):
        cmd = re.sub(r"(?i)/i", "/x", cmd, count=1)  # algunos MSI registran /I (reparar) en lugar de /X
    log.info("Desinstalando %s: %s", name, cmd)
    activity.record("Programas instalados", f"Se abrió el desinstalador oficial de {name} (lo confirma el usuario)", [cmd])
    subprocess.Popen(cmd, shell=True, creationflags=CREATE_NO_WINDOW)
    return {"ok": True, "message": f"Se abrió el desinstalador de {name}"}
