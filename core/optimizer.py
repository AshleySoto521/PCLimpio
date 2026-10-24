# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Optimizador de rendimiento.

- Programas de inicio: se activan/desactivan con las claves StartupApproved, el mismo mecanismo que usa el
  Administrador de tareas de Windows (reversible, no borra nada).
- Tareas programadas y servicios de terceros: se pueden desactivar / poner en manual.
- "Modo suspensión": agrupa por fabricante todo lo que un programa ejecuta en segundo plano (inicio, tareas,
  servicios) y lo desactiva de golpe, guardando el estado previo para poder "despertarlo" después.
- Procesos que más memoria usan y planes de energía.
"""
import json
import os
import re
import struct
import time
import winreg

from .registry_clean import exe_from_command
from . import activity, safety
from .util import DATA_DIR, as_list, expand, is_admin, log, run, run_ps

STATE_FILE = os.path.join(DATA_DIR, "suspension.json")
HKCU, HKLM = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"
RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_SOURCES = [  # (colmena, vista, clave Run, subclave StartupApproved, etiqueta)
    (HKCU, 0, RUN, "Run", "Usuario"),
    (HKLM, winreg.KEY_WOW64_64KEY, RUN, "Run", "Todos los usuarios"),
    (HKLM, winreg.KEY_WOW64_32KEY, RUN, "Run32", "Todos los usuarios (32 bits)"),
]
FOLDERS = [
    (HKCU, r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup", "Carpeta Inicio (usuario)"),
    (HKLM, r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\StartUp", "Carpeta Inicio (todos)"),
]


# ---------------------------------------------------------------- utilidades de registro

def _read_values(hive, key, view=0):
    out = {}
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = data
                i += 1
    except OSError:
        pass
    return out


def _approved_enabled(hive, sub, name):
    data = _read_values(hive, f"{APPROVED}\\{sub}", winreg.KEY_WOW64_64KEY if hive == HKLM else 0).get(name)
    if not isinstance(data, bytes) or not data:
        return True
    return not (data[0] & 1)  # 0x02/0x06 activado, 0x03/0x07 desactivado


def _set_approved(hive, sub, name, enabled):
    if enabled:
        data = b"\x02" + b"\x00" * 11
    else:
        ft = int((time.time() + 11644473600) * 10_000_000)  # FILETIME de la desactivación
        data = b"\x03\x00\x00\x00" + struct.pack("<Q", ft)
    view = winreg.KEY_WOW64_64KEY if hive == HKLM else 0
    with winreg.CreateKeyEx(hive, f"{APPROVED}\\{sub}", 0, winreg.KEY_SET_VALUE | view) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, data)


# ---------------------------------------------------------------- recopilación

def _companies(paths):
    """Fabricante (CompanyName) de cada ejecutable, consultado en una sola llamada a PowerShell."""
    paths = sorted({p for p in paths if p and os.path.isfile(p)})
    if not paths:
        return {}
    tmp = os.path.join(DATA_DIR, "_paths.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(paths, f)
    # Paréntesis: en PowerShell 5.1 ConvertFrom-Json emite el arreglo como un solo objeto
    # Si el ejecutable no declara CompanyName se usa el firmante del certificado (O= o CN=)
    res = run_ps(f"(Get-Content -Raw -Encoding UTF8 '{tmp}' | ConvertFrom-Json) | ForEach-Object {{ "
                 "$v=(Get-Item -LiteralPath $_).VersionInfo; $c=$v.CompanyName; "
                 "if (-not $c) { $s=(Get-AuthenticodeSignature -LiteralPath $_).SignerCertificate.Subject; "
                 "if ($s -match 'O=\"?([^,\"]+)') { $c=$matches[1] } elseif ($s -match 'CN=\"?([^,\"]+)') { $c=$matches[1] } }; "
                 "[pscustomobject]@{p=$_; c=$c; d=$v.FileDescription} }", timeout=180)
    return {r["p"].lower(): {"company": (r.get("c") or "").strip(), "desc": (r.get("d") or "").strip()}
            for r in as_list(res)}


def startup_items():
    items = []
    for hive, view, key, sub, label in RUN_SOURCES:
        for name, cmd in _read_values(hive, key, view).items():
            items.append({"id": f"run|{hive}|{view}|{sub}|{name}", "type": "inicio", "name": name,
                          "command": str(cmd), "exe": exe_from_command(str(cmd)), "location": label,
                          "enabled": _approved_enabled(hive, sub, name), "admin": hive == HKLM})
    for hive, folder, label in FOLDERS:
        folder = expand(folder)
        if not os.path.isdir(folder):
            continue
        for f in os.listdir(folder):
            if f.lower() == "desktop.ini":
                continue
            items.append({"id": f"folder|{hive}|{f}", "type": "inicio", "name": os.path.splitext(f)[0],
                          "command": os.path.join(folder, f), "exe": os.path.join(folder, f), "location": label,
                          "enabled": _approved_enabled(hive, "StartupFolder", f), "admin": hive == HKLM})
    return items


def scheduled_tasks():
    res = run_ps(r"Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\Microsoft\*' } | ForEach-Object { "
                 r"[pscustomobject]@{name=$_.TaskName; path=$_.TaskPath; state=[string]$_.State; "
                 r"author=$_.Author; exe=($_.Actions | Select-Object -First 1).Execute} }", timeout=120)
    out = []
    for t in as_list(res):
        raw = (t.get("exe") or "").strip('"')
        exe = expand(raw) if raw else ""  # tareas COM no tienen ejecutable (normpath("") devolvería ".")
        out.append({"id": f"task|{t['path']}|{t['name']}", "type": "tarea", "name": t["name"],
                    "command": exe, "exe": exe, "location": t["path"], "enabled": t["state"] != "Disabled",
                    "admin": True, "author": t.get("author") or ""})
    return out


def services():
    res = run_ps("Get-CimInstance Win32_Service | Where-Object { $_.StartMode -eq 'Auto' } | ForEach-Object { "
                 "[pscustomobject]@{name=$_.Name; display=$_.DisplayName; path=$_.PathName; state=$_.State; "
                 "mode=$_.StartMode} }", timeout=120)
    out = []
    for s in as_list(res):
        exe = exe_from_command(s.get("path") or "")
        out.append({"id": f"service|{s['name']}", "type": "servicio", "name": s.get("display") or s["name"],
                    "command": s.get("path") or "", "exe": exe, "location": s["name"],
                    "enabled": True, "state": s.get("state"), "admin": True})
    return out


ALIASES = {"advanced micro devices": "AMD", "giga-byte technology": "GIGABYTE", "valve": "Valve (Steam)",
           "softlanding": "Consejos y sugerencias de Windows", "gen digital": "Gen Digital (CCleaner, Avast, Norton)",
           "realtek semiconductor": "Realtek (sonido y red)"}


def _clean_vendor(name):
    name = re.sub(r"\b(Inc|Corp|Corporation|LLC|Ltd|Co|GmbH|S\.A\.|Limited)\b\.?,?", "", name or "",
                  flags=re.I).strip(" ,.")
    return ALIASES.get(name.lower(), name)


def _vendor(info, item):
    company = _clean_vendor((info or {}).get("company", ""))
    if company:
        return company
    author = _clean_vendor(item.get("author", ""))
    if item["type"] == "tarea" and re.search(r"[A-Za-z]", author) and "\\" not in author:
        return author
    windir = os.path.normcase(os.environ.get("WINDIR", r"C:\Windows"))
    if item["exe"] and os.path.isabs(item["exe"]) and not os.path.normcase(item["exe"]).startswith(windir):
        return os.path.splitext(os.path.basename(item["exe"]))[0]
    if item["exe"]:  # usa una herramienta de Windows (xcopy, cmd…): el nombre de la tarea dice más
        return _friendly_name(item)
    if item["type"] == "tarea":
        return item["location"].strip("\\").split("\\")[0] or item["name"]  # carpeta de la tarea
    return item["name"]


def overview(job):
    job.update(10, "Programas de inicio")
    items = startup_items()
    job.update(35, "Tareas programadas")
    items += scheduled_tasks()
    job.update(60, "Servicios")
    svcs = services()
    job.update(80, "Identificando fabricantes")
    info = _companies([i["exe"] for i in items + svcs])
    # solo servicios de terceros (los de Microsoft son parte de Windows)
    svcs = [s for s in svcs if s["exe"] and "microsoft" not in info.get(s["exe"].lower(), {}).get("company", "").lower()]
    items += svcs
    state = _load_state()
    apps = {}
    for it in items:
        meta = info.get((it["exe"] or "").lower(), {})
        it["company"] = meta.get("company", "")
        it["description"] = meta.get("desc", "")
        it["friendly"] = _friendly_name(it)
        it["type_plain"], it["off_effect"] = TYPE_PLAIN[it["type"]]
        ok, why = safety.check_component(it)
        it["protected"] = None if ok else why
        if "microsoft" in it["company"].lower() and it["type"] != "inicio":
            continue
        vendor = _vendor(meta, it)
        vendor = ALIASES.get(vendor.lower(), vendor)
        apps.setdefault(vendor, {"name": vendor, "components": [], "sleeping": vendor in state})
        apps[vendor]["components"].append(it)
    app_list = sorted(apps.values(), key=lambda a: (-len(a["components"]), a["name"].lower()))
    _last_overview.clear()
    _last_overview.update({a["name"]: a["components"] for a in app_list})
    _last_overview["__startup__"] = [i for i in items if i["type"] == "inicio"]
    return {"startup": _last_overview["__startup__"], "apps": app_list, "admin": is_admin()}


_last_overview = {}


def known_component(cid):
    """Solo se permiten cambios sobre componentes que salieron en el último análisis."""
    return any(c["id"] == cid for comps in _last_overview.values() for c in comps)


# ---------------------------------------------------------------- cambios

def set_component(cid, enabled):
    """Activa o desactiva un componente. Desactivar algo protegido (seguridad, Windows) lanza safety.Blocked."""
    if not enabled:
        comp = next((c for comps in _last_overview.values() for c in comps if c["id"] == cid), None)
        ok, why = safety.check_component(comp) if comp else (False, "Componente desconocido; vuelve a analizar.")
        if not ok:
            raise safety.Blocked(f"No se puede desactivar {comp['name'] if comp else cid}: {why}")
    kind, rest = cid.split("|", 1)
    if kind == "run":
        hive, _view, sub, name = rest.split("|", 3)
        _set_approved(int(hive), sub, name, enabled)
    elif kind == "folder":
        hive, name = rest.split("|", 1)
        _set_approved(int(hive), "StartupFolder", name, enabled)
    elif kind == "task":
        path, name = rest.split("|", 1)
        verb = "Enable" if enabled else "Disable"
        q = lambda s: s.replace("'", "''")
        code, out = run(["powershell", "-NoProfile", "-Command",
                         f"{verb}-ScheduledTask -TaskPath '{q(path)}' -TaskName '{q(name)}' -ErrorAction Stop | Out-Null"],
                        timeout=60)
        if code != 0:
            raise OSError(out.strip() or "No se pudo cambiar la tarea (¿falta permiso de administrador?)")
    elif kind == "service":
        mode = "auto" if enabled else "demand"
        code, out = run(["sc", "config", rest, "start=", mode], timeout=60)
        if code != 0:
            raise OSError(out.strip())
        if not enabled:
            run(["sc", "stop", rest], timeout=60)
    log.info("Componente %s -> %s", cid, "activado" if enabled else "desactivado")
    comp = next((c for comps in _last_overview.values() for c in comps if c["id"] == cid), None)
    activity.record("Optimizador de rendimiento",
                    f"{'Activado' if enabled else 'Desactivado'}: {comp['name'] if comp else cid}"
                    + (f" ({comp['type']})" if comp else ""))


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def sleep_app(name):
    """Desactiva los componentes activos de un programa y recuerda cuáles eran para despertarlo."""
    state = _load_state()
    done, errors, kept = [], [], []
    for c in _last_overview.get(name, []):
        if not c.get("enabled", True):
            continue
        try:
            set_component(c["id"], False)
            done.append(c["id"])
        except safety.Blocked:
            kept.append({"name": c["name"], "reason": c.get("protected") or ""})
        except OSError as e:
            errors.append({"id": c["id"], "error": str(e)})
    if done:
        state[name] = sorted(set(state.get(name, []) + done))
        _save_state(state)
    return {"disabled": len(done), "errors": errors, "protected": kept}


def wake_app(name):
    state = _load_state()
    errors = []
    for cid in state.get(name, []):
        try:
            set_component(cid, True)
        except OSError as e:
            errors.append({"id": cid, "error": str(e)})
    state.pop(name, None)
    _save_state(state)
    return {"errors": errors}


# ---------------------------------------------------------------- textos para cualquier persona

TYPE_PLAIN = {
    "inicio": ("Se abre solo al encender el equipo",
               "Dejará de abrirse solo al encender. Si lo necesitas, ábrelo tú como cualquier programa."),
    "tarea": ("Tarea automática (se ejecuta sola a ciertas horas)",
              "Dejará de ejecutarse sola. Normalmente son buscadores de actualizaciones del programa."),
    "servicio": ("Funciona escondido todo el tiempo",
                 "Dejará de arrancar solo; el programa lo puede volver a encender cuando lo abras."),
}

# Procesos de Windows que la gente ve y no reconoce
PROCESS_PLAIN = {
    "svchost": "Servicios de Windows (red, sonido, actualizaciones…)",
    "dwm": "Dibuja las ventanas en la pantalla",
    "explorer": "Escritorio, barra de tareas y carpetas",
    "memory compression": "Windows comprimiendo memoria para que te alcance",
    "msmpeng": "Antivirus de Windows",
    "searchhost": "Búsqueda de Windows",
    "searchindexer": "Búsqueda de Windows (preparando el índice)",
    "runtimebroker": "Permisos de las apps de Windows",
    "msedgewebview2": "Ventanas web que usan otros programas",
    "system": "El núcleo de Windows",
    "registry": "Configuración interna de Windows",
    "audiodg": "Sonido de Windows",
    "csrss": "Parte esencial de Windows",
    "lsass": "Seguridad e inicio de sesión de Windows",
    "winlogon": "Inicio de sesión de Windows",
    "services": "Administrador de servicios de Windows",
    "secure system": "Seguridad de Windows",
    "phoneexperiencehost": "Vincular con el móvil",
    "textinputhost": "Teclado y emojis de Windows",
    "startmenuexperiencehost": "Menú Inicio",
    "shellexperiencehost": "Partes de la barra de tareas",
    "ctfmon": "Teclado e idiomas",
    "widgets": "Widgets de Windows",
    "onedrive": "OneDrive",
}

POWER_PLANS = {
    "381b4222-f694-41f0-9685-ff5bb260df2e": "Lo recomendado: rápido cuando lo necesitas y ahorra energía cuando no.",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "Siempre a máxima velocidad. Gasta más luz o batería y el equipo se calienta más.",
    "a1841308-3541-4fab-bc81-f71556f20b4a": "Ahorra batería al máximo, pero el equipo va más lento.",
    "e9a42b02-d5df-448d-aa00-03f14749eb61": "Rendimiento máximo sin pausas, pensado para equipos de trabajo pesado.",
}


def _friendly_name(item):
    """Nombre que entiende cualquiera: la descripción del programa si existe, si no el nombre tal cual."""
    desc = (item.get("description") or "").strip()
    name = item["name"]
    if desc and desc.lower() not in name.lower() and len(desc) < 70:
        return desc
    return re.sub(r"_\{?[0-9A-F-]{20,}\}?$", "", re.sub(r"[_]+", " ", name), flags=re.I).strip() or name


def processes():
    res = run_ps("Get-Process | Group-Object ProcessName | ForEach-Object { $first = $_.Group | Where-Object Path | "
                 "Select-Object -First 1; [pscustomobject]@{name=$_.Name; "
                 "count=$_.Count; mem=($_.Group | Measure-Object WorkingSet64 -Sum).Sum; "
                 "cpu=[math]::Round(($_.Group | Measure-Object CPU -Sum).Sum,1); "
                 "path=$first.Path; desc=$first.Description; product=$first.Product} } | "
                 "Sort-Object mem -Descending | Select-Object -First 30", timeout=60)
    out = as_list(res)
    for p in out:
        ok, why = safety.check_process(p["name"])
        p["protected"] = None if ok else why
        p["friendly"] = (PROCESS_PLAIN.get(p["name"].lower()) or (p.get("desc") or "").strip()
                         or (p.get("product") or "").strip() or p["name"])
    return out


def end_process(name):
    ok, why = safety.check_process(name)
    if not ok:
        raise safety.Blocked(f"No se puede finalizar {name}: {why}")
    code, out = run(["taskkill", "/IM", f"{name}.exe", "/T", "/F"], timeout=30)
    if code == 0:
        activity.record("Optimizador de rendimiento", f"Proceso finalizado por el usuario: {name}")
    return {"ok": code == 0, "message": out.strip()}


def power_plans():
    _, out = run(["powercfg", "/list"], timeout=30)
    plans = []
    for m in re.finditer(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+\((.+?)\)(\s*\*)?", out, re.I):
        plans.append({"guid": m.group(1), "name": m.group(2), "active": bool(m.group(3)),
                      "plain": POWER_PLANS.get(m.group(1).lower(), "Plan creado por el fabricante o por ti.")})
    return plans


def set_power_plan(guid):
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", guid):
        raise ValueError("GUID inválido")
    code, out = run(["powercfg", "/setactive", guid], timeout=30)
    return {"ok": code == 0, "message": out.strip()}
