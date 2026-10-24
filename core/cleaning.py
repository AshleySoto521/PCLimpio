# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Limpieza básica y avanzada basada en reglas (mismo enfoque que CCleaner: analizar primero, luego limpiar).

Cada regla tiene una o más rutas ("targets") con patrones, antigüedad mínima y si requiere administrador.
Analizar solo cuenta archivos y bytes; limpiar borra lo que se puede (los archivos en uso se omiten).
"""
import ctypes
import fnmatch
import glob
import os
import time

from . import activity, browsers, safety
from .util import (empty_recycle_bin, expand, human_size, is_admin, is_reparse, log, recycle_bin_info,
                   remove_empty_dirs, remove_file, run, running_processes)


def T(path, patterns=("*",), recursive=True, min_age_h=0, admin=False):
    return {"path": path, "patterns": patterns, "recursive": recursive, "min_age_h": min_age_h, "admin": admin}


def _static_rules():
    W = "Windows"
    A = "Tus programas"
    P = "Privacidad"
    return [
        # ---------------------------------------------------------------- básicas
        dict(id="temp_user", name="Archivos temporales del usuario", group=W, level="basica", default=True,
             desc="Carpeta %TEMP% (archivos con más de 24 h).",
             targets=[T(r"%TEMP%", min_age_h=24)]),
        dict(id="temp_windows", name="Archivos temporales de Windows", group=W, level="basica", default=True,
             desc=r"C:\Windows\Temp (más de 24 h).", targets=[T(r"%WINDIR%\Temp", min_age_h=24, admin=True)]),
        dict(id="recycle_bin", name="Papelera de reciclaje", group=W, level="basica", default=True,
             desc="Vacía la Papelera de todas las unidades.", special="recycle_bin"),
        dict(id="thumbnails", name="Caché de miniaturas e iconos", group=W, level="basica", default=True,
             desc="Explorer la vuelve a generar cuando hace falta.",
             targets=[T(r"%LOCALAPPDATA%\Microsoft\Windows\Explorer", ("thumbcache_*.db", "iconcache_*.db"),
                        recursive=False)]),
        dict(id="error_reports", name="Informes de errores de Windows", group=W, level="basica", default=True,
             desc="Informes de WER ya enviados o en cola.",
             targets=[T(r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportArchive"),
                      T(r"%LOCALAPPDATA%\Microsoft\Windows\WER\ReportQueue"),
                      T(r"%PROGRAMDATA%\Microsoft\Windows\WER\ReportArchive", admin=True),
                      T(r"%PROGRAMDATA%\Microsoft\Windows\WER\ReportQueue", admin=True),
                      T(r"%PROGRAMDATA%\Microsoft\Windows\WER\Temp", admin=True)]),
        dict(id="memory_dumps", name="Volcados de memoria", group=W, level="basica", default=True,
             desc="Archivos .dmp que deja un programa o Windows al fallar.",
             targets=[T(r"%LOCALAPPDATA%\CrashDumps"), T(r"%WINDIR%\Minidump", admin=True),
                      T(r"%WINDIR%\MEMORY.DMP", admin=True)]),
        dict(id="shader_cache", name="Caché de sombreadores (DirectX / GPU)", group=W, level="basica", default=True,
             desc="Se regenera al abrir juegos y apps 3D.",
             targets=[T(r"%LOCALAPPDATA%\D3DSCache"), T(r"%LOCALAPPDATA%\NVIDIA\DXCache"),
                      T(r"%LOCALAPPDATA%\NVIDIA\GLCache"), T(r"%LOCALAPPDATA%\AMD\DxCache"),
                      T(r"%LOCALAPPDATA%\AMD\DxcCache"), T(r"%LOCALAPPDATA%\AMD\GLCache")]),
        dict(id="dns_cache", name="Caché DNS", group=W, level="basica", default=True,
             desc="Ejecuta ipconfig /flushdns (no libera espacio en disco).", special="dns"),
        # ---------------------------------------------------------------- avanzadas
        dict(id="windows_update", name="Descargas de Windows Update", group=W, level="avanzada", default=True,
             desc="Instaladores ya aplicados en SoftwareDistribution\\Download.",
             targets=[T(r"%WINDIR%\SoftwareDistribution\Download", min_age_h=72, admin=True)]),
        dict(id="delivery_opt", name="Caché de Optimización de distribución", group=W, level="avanzada",
             default=True, desc="Copias de actualizaciones compartidas entre equipos.",
             targets=[T(r"%WINDIR%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows"
                        r"\DeliveryOptimization\Cache", admin=True)]),
        dict(id="windows_logs", name="Archivos de registro de Windows", group=W, level="avanzada", default=True,
             desc="*.log / *.etl antiguos de C:\\Windows\\Logs (más de 7 días).",
             targets=[T(r"%WINDIR%\Logs", ("*.log", "*.etl", "*.cab"), min_age_h=168, admin=True)]),
        dict(id="chkdsk", name="Fragmentos de Chkdsk", group=W, level="avanzada", default=True,
             desc="Archivos .chk que deja la comprobación de disco.",
             targets=[T(r"%SYSTEMDRIVE%\FOUND.*", ("*.chk",), admin=True)]),
        dict(id="prefetch", name="Datos de Prefetch antiguos", group=W, level="avanzada", default=False,
             desc="*.pf con más de 30 días. Windows los recrea; el primer arranque de cada app será algo más lento.",
             targets=[T(r"%WINDIR%\Prefetch", ("*.pf",), recursive=False, min_age_h=720, admin=True)]),
        dict(id="driver_installers", name="Restos de instaladores de controladores", group=W, level="avanzada",
             default=False, desc="Carpetas que dejan los instaladores de AMD y NVIDIA.",
             targets=[T(r"%SYSTEMDRIVE%\AMD", admin=True), T(r"%SYSTEMDRIVE%\NVIDIA", admin=True),
                      T(r"%PROGRAMDATA%\NVIDIA Corporation\Downloader", admin=True)]),
        dict(id="discord", name="Discord (caché)", group=A, level="avanzada", default=True, processes=["discord.exe"],
             desc="Imágenes y código en caché.",
             targets=[T(r"%APPDATA%\discord\Cache"), T(r"%APPDATA%\discord\Code Cache"),
                      T(r"%APPDATA%\discord\GPUCache")]),
        dict(id="spotify", name="Spotify (caché de canciones)", group=A, level="avanzada", default=True,
             processes=["spotify.exe"], desc="Música en caché; se vuelve a descargar al escuchar.",
             targets=[T(r"%LOCALAPPDATA%\Spotify\Data")]),
        dict(id="steam", name="Steam (caché web y registros)", group=A, level="avanzada", default=True,
             processes=["steam.exe"], desc="No toca juegos ni partidas guardadas.",
             targets=[T(r"%ProgramFiles(x86)%\Steam\appcache\httpcache", admin=True),
                      T(r"%ProgramFiles(x86)%\Steam\logs", admin=True),
                      T(r"%ProgramFiles(x86)%\Steam\dumps", admin=True)]),
        dict(id="vscode", name="Visual Studio Code (caché)", group=A, level="avanzada", default=True,
             processes=["code.exe"], desc="Caché y registros del editor.",
             targets=[T(r"%APPDATA%\Code\Cache"), T(r"%APPDATA%\Code\CachedData"),
                      T(r"%APPDATA%\Code\Code Cache"), T(r"%APPDATA%\Code\GPUCache"), T(r"%APPDATA%\Code\logs")]),
        dict(id="teams_classic", name="Microsoft Teams clásico (caché)", group=A, level="avanzada", default=True,
             processes=["teams.exe"], desc="Caché de la versión clásica de Teams.",
             targets=[T(r"%APPDATA%\Microsoft\Teams\Cache"), T(r"%APPDATA%\Microsoft\Teams\GPUCache"),
                      T(r"%APPDATA%\Microsoft\Teams\Code Cache")]),
        dict(id="dev_caches", name="Cachés de desarrollo (npm, pip)", group=A, level="avanzada", default=False,
             desc="Paquetes descargados; se vuelven a bajar si se necesitan.",
             targets=[T(r"%LOCALAPPDATA%\npm-cache\_cacache"), T(r"%LOCALAPPDATA%\pip\cache")]),
        dict(id="recent_docs", name="Documentos recientes y listas de salto", group=P, level="avanzada",
             default=False, desc="Accesos directos de 'Recientes' del Explorador y de la barra de tareas.",
             targets=[T(r"%APPDATA%\Microsoft\Windows\Recent", ("*.lnk",), recursive=False),
                      T(r"%APPDATA%\Microsoft\Windows\Recent\AutomaticDestinations"),
                      T(r"%APPDATA%\Microsoft\Windows\Recent\CustomDestinations")]),
        dict(id="clipboard", name="Portapapeles", group=P, level="avanzada", default=False,
             desc="Vacía el contenido actual del portapapeles.", special="clipboard"),
    ]


# Textos para cualquier persona: (nombre, qué es y qué pasa si lo limpias). Sustituyen a los técnicos.
PLAIN = {
    "temp_user": ("Archivos temporales",
                  "Archivos que los programas usan un momento y luego olvidan borrar. Solo se quitan los de más de un día."),
    "temp_windows": ("Archivos temporales de Windows",
                     "Lo mismo, pero los que deja Windows. Solo los de más de un día."),
    "recycle_bin": ("Papelera de reciclaje",
                    "Lo que ya mandaste a la Papelera. Al vaciarla ya no se puede recuperar desde ahí."),
    "thumbnails": ("Miniaturas de fotos y videos",
                   "Vistas previas que Windows guarda para que las carpetas carguen rápido. Se vuelven a crear solas."),
    "error_reports": ("Informes de errores",
                      "Avisos que Windows guarda cuando algo falla. Si ya no tienes problemas, no se necesitan."),
    "memory_dumps": ("Informes de fallos graves",
                     "Archivos que se crean cuando un programa o el equipo se cuelga. Ocupan mucho y casi nunca se usan."),
    "shader_cache": ("Caché de gráficos",
                     "Efectos que la tarjeta gráfica guarda para que los juegos carguen más rápido. Se vuelven a crear al jugar."),
    "dns_cache": ("Memoria de direcciones de Internet",
                  "Windows recuerda las direcciones de las páginas que visitas. Vaciarla ayuda si alguna web no carga. "
                  "No libera espacio."),
    "windows_update": ("Actualizaciones de Windows ya instaladas",
                       "Copias de actualizaciones que Windows ya aplicó. Si las vuelve a necesitar, las descarga solo."),
    "delivery_opt": ("Copias de actualizaciones para compartir",
                     "Pedazos de actualizaciones que Windows guarda para pasarlos a otros equipos. Puedes quitarlos sin problema."),
    "windows_logs": ("Notas antiguas de Windows",
                     "Registros de lo que hizo Windows hace más de una semana. Solo sirven para técnicos."),
    "chkdsk": ("Restos de la revisión del disco",
               "Trozos de archivos dañados que deja la revisión de disco de Windows. Casi nunca sirven de algo."),
    "prefetch": ("Datos para abrir programas más rápido",
                 "Windows anota cómo abre cada programa. Si los borras, cada programa tardará un poco más la primera vez."),
    "driver_installers": ("Restos de instaladores de controladores",
                          "Carpetas que dejan los instaladores de AMD y NVIDIA después de instalar. Ya no se usan."),
    "discord": ("Discord: imágenes guardadas", "Imágenes y datos que Discord guarda para ir más rápido. Se vuelven a descargar."),
    "spotify": ("Spotify: canciones guardadas", "Música que Spotify guarda para no descargarla otra vez. "
                "Se vuelve a descargar al escucharla (las descargas para escuchar sin Internet también se borran)."),
    "steam": ("Steam: archivos temporales", "Páginas e informes de Steam. No toca tus juegos ni tus partidas."),
    "vscode": ("Visual Studio Code: archivos temporales", "Datos temporales del editor. No toca tus proyectos."),
    "teams_classic": ("Microsoft Teams: archivos temporales", "Datos temporales de Teams. No borra tus chats."),
    "dev_caches": ("Herramientas de programación: descargas guardadas",
                   "Paquetes que descargaron herramientas como npm o pip. Si no programas, no te afecta."),
    "recent_docs": ("Lista de archivos abiertos recientemente",
                    "La lista de 'Recientes' del Explorador y de la barra de tareas. Tus archivos no se borran, solo la lista."),
    "clipboard": ("Lo que copiaste (portapapeles)", "Borra lo último que copiaste con Ctrl+C."),
}

# Nombres de programa que entiende cualquiera, para avisar "cierra X primero"
APP_NAMES = {"chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge", "firefox.exe": "Firefox",
             "brave.exe": "Brave", "opera.exe": "Opera", "vivaldi.exe": "Vivaldi", "discord.exe": "Discord",
             "spotify.exe": "Spotify", "steam.exe": "Steam", "code.exe": "Visual Studio Code", "teams.exe": "Teams"}


def app_name(process):
    return APP_NAMES.get(process.lower(), process)


def _browser_rules():
    rules = []
    for b in browsers.installed():
        targets, sw = [], []
        for data_dir, cache_dir in b["profiles"]:
            if b["kind"] == "chromium":
                for sub in ("Cache", "Code Cache", "GPUCache"):
                    targets.append(T(os.path.join(cache_dir, sub)))
                sw.append(T(os.path.join(data_dir, "Service Worker", "CacheStorage")))
            else:
                targets.append(T(os.path.join(cache_dir, "cache2")))
                targets.append(T(os.path.join(data_dir, "startupCache")))
        if b["kind"] == "chromium" and not b.get("flat"):
            root = expand(b["data"])
            targets += [T(os.path.join(root, "ShaderCache")), T(os.path.join(root, "GrShaderCache"))]
        rules.append(dict(id=f"cache_{b['id']}", name=f"{b['name']}: páginas guardadas", group="Navegadores",
                          level="basica", default=True, processes=[b["process"]], targets=targets,
                          desc="Copias de páginas web para que carguen más rápido. No borra tu historial, "
                               "contraseñas ni sesiones."))
        if sw:
            rules.append(dict(id=f"sw_{b['id']}", name=f"{b['name']}: datos de sitios para usar sin Internet",
                              group="Navegadores", level="avanzada", default=False, processes=[b["process"]],
                              targets=sw, desc="Algunas webs guardan datos para funcionar sin conexión. Si los "
                                               "borras, esas webs tardarán un poco más la próxima vez."))
    return rules


def _target_exists(t):
    p = expand(t["path"])
    return bool(glob.glob(p)) if any(c in p for c in "*?") else os.path.exists(p)


def all_rules():
    rules = _static_rules() + _browser_rules()
    rules = [r for r in rules if r.get("special") or any(_target_exists(t) for t in r["targets"])]
    for r in rules:
        if r["id"] in PLAIN:
            r["name"], r["desc"] = PLAIN[r["id"]]
        r["app_names"] = [app_name(p) for p in r.get("processes", [])]
    # Las carpetas de las reglas se declaran como zonas de limpieza. safety rechaza cualquier
    # zona que caiga en el núcleo de Windows, así que una regla mal escrita no puede tocarlo.
    for r in rules:
        for t in r.get("targets", []):
            p = expand(t["path"])
            for base in (glob.glob(p) if any(c in p for c in "*?") else [p]):
                if not safety.allow_cleanup_zone(base):
                    log.warning("Regla %s apunta a una zona intocable y se ignora: %s", r["id"], base)
    return rules


def rules_for_ui(level=None):
    admin = is_admin()
    out = []
    for r in all_rules():
        if level and r["level"] != level:
            continue
        targets = r.get("targets", [])
        needs_admin = bool(targets) and all(t["admin"] for t in targets)
        out.append({"id": r["id"], "name": r["name"], "group": r["group"], "level": r["level"],
                    "desc": r["desc"], "default": r["default"], "processes": r.get("processes", []),
                    "app_names": r["app_names"],
                    "needs_admin": needs_admin, "partial_admin": any(t["admin"] for t in targets) and not admin})
    return out


def iter_files(t):
    """Recorre los archivos de un target sin seguir enlaces/uniones. Produce (ruta, tamaño)."""
    path = expand(t["path"])
    bases = glob.glob(path) if any(c in path for c in "*?") else [path]
    cutoff = time.time() - t["min_age_h"] * 3600
    pats = [p.lower() for p in t["patterns"]]
    for base in bases:
        if os.path.isfile(base):
            try:
                st = os.stat(base)
                if st.st_mtime <= cutoff:
                    yield base, st.st_size
            except OSError:
                pass
            continue
        stack = [base]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    if is_reparse(e):
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if t["recursive"]:
                                stack.append(e.path)
                            continue
                        name = e.name.lower()
                        if not any(fnmatch.fnmatch(name, p) for p in pats):
                            continue
                        st = e.stat(follow_symlinks=False)
                        if st.st_mtime <= cutoff:
                            yield e.path, st.st_size
                    except OSError:
                        continue


def _usable_targets(rule, admin):
    return [t for t in rule.get("targets", []) if admin or not t["admin"]]


def _clear_clipboard():
    u32 = ctypes.windll.user32
    if u32.OpenClipboard(None):
        u32.EmptyClipboard()
        u32.CloseClipboard()


def analyze(job, rule_ids):
    rules = [r for r in all_rules() if r["id"] in set(rule_ids)]
    admin = is_admin()
    procs = running_processes()
    results, total = [], 0
    for i, r in enumerate(rules):
        job.update(i * 100 / max(1, len(rules)), f"Analizando: {r['name']}")
        files, size, sample = 0, 0, []
        if r.get("special") == "recycle_bin":
            size, files = recycle_bin_info()
        elif not r.get("special"):
            for path, sz in (f for t in _usable_targets(r, admin) for f in iter_files(t)):
                files += 1
                size += sz
                if len(sample) < 30:
                    sample.append({"path": path, "size": sz})
                if files % 2000 == 0:
                    job.check()
        skipped_admin = (not admin) and any(t["admin"] for t in r.get("targets", []))
        results.append({"id": r["id"], "name": r["name"], "group": r["group"], "files": files, "bytes": size,
                        "sample": sample, "running": [p for p in r.get("processes", []) if p in procs],
                        "running_names": [app_name(p) for p in r.get("processes", []) if p in procs],
                        "skipped_admin": skipped_admin, "special": r.get("special")})
        total += size
    log.info("Análisis de limpieza: %d reglas, %d bytes", len(rules), total)
    return {"rules": results, "total_bytes": total, "admin": admin}


def clean(job, rule_ids):
    rules = [r for r in all_rules() if r["id"] in set(rule_ids)]
    admin = is_admin()
    procs = running_processes()
    results, total = [], 0
    for i, r in enumerate(rules):
        job.update(i * 100 / max(1, len(rules)), f"Limpiando: {r['name']}")
        busy = [p for p in r.get("processes", []) if p in procs]
        freed = deleted = failed = 0
        note = ""
        if busy:
            note = f"No se limpió porque {', '.join(app_name(b) for b in busy)} estaba abierto. Ciérralo y vuelve a intentarlo."
        elif r.get("special") == "recycle_bin":
            freed = empty_recycle_bin()
        elif r.get("special") == "dns":
            code, _ = run(["ipconfig", "/flushdns"], timeout=30)
            note = "Listo." if code == 0 else "No se pudo vaciar."
        elif r.get("special") == "clipboard":
            _clear_clipboard()
            note = "Listo."
        else:
            blocked = 0
            for t in _usable_targets(r, admin):
                for path, _ in list(iter_files(t)):
                    try:
                        got = remove_file(path)
                    except safety.Blocked:
                        blocked += 1
                        continue
                    if got is None:
                        failed += 1
                    else:
                        deleted += 1
                        freed += got
                    if (deleted + failed) % 500 == 0:
                        job.check()
                base = expand(t["path"])
                for b in (glob.glob(base) if any(c in base for c in "*?") else [base]):
                    if os.path.isdir(b) and t["recursive"]:
                        remove_empty_dirs(b)
            if failed:
                note = (f"{failed} archivo(s) se dejaron porque un programa los estaba usando. Es normal; "
                        "se pueden quitar otro día.")
            if blocked:
                note += f"{' ' if note else ''}{blocked} archivo(s) de Windows protegidos no se tocaron."
        results.append({"id": r["id"], "name": r["name"], "freed": freed, "deleted": deleted,
                        "failed": failed, "note": note})
        total += freed
    log.info("Limpieza: %d reglas, %d bytes liberados", len(rules), total)
    activity.record("Limpieza", f"Limpieza de {len(rules)} elemento(s): {human_size(total)} liberados",
                    [f"{r['name']}: {r['deleted']} archivo(s), {human_size(r['freed'])}"
                     + (f" — {r['note']}" if r["note"] else "") for r in results], total)
    return {"rules": results, "total_freed": total}
