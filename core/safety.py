# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Protección del sistema: decide qué se puede borrar, desinstalar, desactivar o finalizar.

Todas las operaciones destructivas de la app pasan por aquí (también las internas), y se aplican igual
aunque la app tenga permisos de administrador. Cada bloqueo devuelve el motivo para mostrárselo al usuario.

Niveles para rutas:
1. INTOCABLE: núcleo de Windows, arranque, raíces de unidades y perfiles. Nunca se borra, ni siquiera
   desde las reglas de limpieza de la propia app.
2. PROTEGIDO: Windows, Program Files, ProgramData y AppData. Solo se permite borrar dentro de las zonas de
   limpieza revisadas (temporales, cachés…) que se declaran abajo o que registran los módulos de limpieza.
3. Resto: se permite.
"""
import os
import re
import threading

_lock = threading.Lock()


def _env(name, default=""):
    return os.environ.get(name, default)


WINDIR = _env("WINDIR", r"C:\Windows")
SYSDRIVE = _env("SYSTEMDRIVE", "C:") + "\\"
PROFILE = os.path.expanduser("~")


def norm(path):
    """Ruta absoluta, real (resuelve enlaces, uniones y nombres cortos 8.3) y en minúsculas."""
    p = os.path.abspath(os.path.expandvars(str(path)))
    try:
        p = os.path.realpath(p)
    except (OSError, ValueError):
        pass
    if p.startswith("\\\\?\\"):
        p = p[4:]
    return os.path.normcase(p).rstrip("\\") or p


def _within(path, root):
    return path == root or path.startswith(root + "\\")


# ---------------------------------------------------------------- nivel 1: intocable

_W = lambda *p: os.path.join(WINDIR, *p)  # noqa: E731

UNTOUCHABLE = [
    (_W("System32"), "System32 contiene el núcleo de Windows: kernel, controladores, servicios y bibliotecas "
                     "básicas. Si se borra, Windows deja de arrancar."),
    (_W("SysWOW64"), "SysWOW64 tiene los componentes de Windows para programas de 32 bits. Sin ella la mayoría "
                     "de los programas y partes de Windows fallan."),
    (_W("WinSxS"), "WinSxS es el almacén de componentes de Windows; se usa para instalar actualizaciones y "
                   "reparar el sistema. Para reducirla usa el Liberador de espacio de Windows (DISM)."),
    (_W("Boot"), "Contiene los archivos de arranque de Windows; sin ellos el equipo no inicia."),
    (_W("servicing"), "Pila de mantenimiento de Windows: sin ella no se pueden instalar actualizaciones."),
    (_W("Installer"), "Caché de instaladores MSI. Si se borra, los programas no se pueden reparar ni "
                      "desinstalar correctamente."),
    (_W("assembly"), "Caché global de .NET; muchos programas dejan de abrir sin ella."),
    (_W("Microsoft.NET"), ".NET Framework: lo necesitan Windows y gran parte de los programas."),
    (_W("SystemApps"), "Aplicaciones integradas de Windows (menú Inicio, Configuración, búsqueda)."),
    (_W("SystemResources"), "Recursos gráficos y de idioma que usa la interfaz de Windows."),
    (_W("Fonts"), "Fuentes del sistema; borrarlas deja textos ilegibles en Windows y programas."),
    (_W("INF"), "Información de instalación de controladores; sin ella Windows no reconoce el hardware."),
    (_W("PolicyDefinitions"), "Plantillas de directivas de Windows."),
    (_W("explorer.exe"), "El Explorador de Windows (escritorio, barra de tareas y carpetas)."),
    (os.path.join(SYSDRIVE, "Boot"), "Archivos de arranque del equipo."),
    (os.path.join(SYSDRIVE, "EFI"), "Partición/archivos de arranque UEFI."),
    (os.path.join(SYSDRIVE, "bootmgr"), "Gestor de arranque de Windows."),
    (os.path.join(SYSDRIVE, "System Volume Information"), "Puntos de restauración e índices del sistema."),
    (os.path.join(SYSDRIVE, "Recovery"), "Entorno de recuperación de Windows (para reparar el equipo)."),
    (os.path.join(SYSDRIVE, "pagefile.sys"), "Archivo de paginación (memoria virtual) en uso por Windows."),
    (os.path.join(SYSDRIVE, "hiberfil.sys"), "Archivo de hibernación. Para quitarlo usa 'powercfg /h off'."),
    (os.path.join(SYSDRIVE, "swapfile.sys"), "Archivo de intercambio de las apps de Windows."),
    (os.path.join(PROFILE, "NTUSER.DAT"), "Tu registro de usuario: sin él pierdes tu perfil de Windows."),
]

# Carpetas que nunca se eliminan como carpeta (su contenido sí puede revisarse según las demás reglas)
FOLDER_ROOTS = [
    (WINDIR, "Es la carpeta de Windows completa."),
    (_env("ProgramFiles", r"C:\Program Files"), "Contiene todos los programas instalados."),
    (_env("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Contiene todos los programas de 32 bits instalados."),
    (_env("ProgramData", r"C:\ProgramData"), "Datos compartidos de Windows y de los programas."),
    (os.path.dirname(PROFILE), "Contiene los perfiles de todos los usuarios."),
    (PROFILE, "Es tu carpeta de usuario completa."),
    (os.path.join(PROFILE, "AppData"), "Configuración de todos tus programas."),
    (os.path.join(PROFILE, "Desktop"), "Es tu Escritorio."),
    (os.path.join(PROFILE, "Documents"), "Es tu carpeta Documentos."),
    (os.path.join(PROFILE, "Downloads"), "Es tu carpeta Descargas."),
    (os.path.join(PROFILE, "Pictures"), "Es tu carpeta Imágenes."),
]

# ---------------------------------------------------------------- nivel 2: protegido salvo zonas de limpieza

PROTECTED = [
    (WINDIR, "Está dentro de la carpeta de Windows; borrar archivos de aquí puede dañar el sistema."),
    (_env("ProgramFiles", r"C:\Program Files"),
     "Es parte de un programa instalado. Para quitarlo usa el Desinstalador; borrar sus archivos lo deja roto."),
    (_env("ProgramFiles(x86)", r"C:\Program Files (x86)"),
     "Es parte de un programa instalado. Para quitarlo usa el Desinstalador; borrar sus archivos lo deja roto."),
    (_env("ProgramData", r"C:\ProgramData"),
     "Son datos compartidos de Windows o de programas (licencias, antivirus, configuración)."),
    (_env("APPDATA"), "Es configuración o datos de un programa; borrarlo puede hacerte perder ajustes o cuentas."),
    (_env("LOCALAPPDATA"), "Es configuración o datos de un programa; borrarlo puede hacerte perder ajustes o cuentas."),
]

# Zonas de limpieza revisadas dentro de lo protegido (Windows las regenera o son temporales)
CLEANUP_ZONES = [
    _W("Temp"), _W("SoftwareDistribution", "Download"), _W("Prefetch"), _W("Logs"), _W("Minidump"),
    _W("MEMORY.DMP"), _W("ServiceProfiles", "NetworkService", "AppData", "Local", "Microsoft", "Windows",
                         "DeliveryOptimization", "Cache"),
    os.path.join(_env("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows", "WER"),
    os.path.join(_env("ProgramData", r"C:\ProgramData"), "NVIDIA Corporation", "Downloader"),
    _env("TEMP"), os.path.join(_env("LOCALAPPDATA"), "Temp"),
    os.path.join(_env("LOCALAPPDATA"), "CrashDumps"),
    os.path.join(_env("LOCALAPPDATA"), "Microsoft", "Windows", "WER"),
    os.path.join(_env("LOCALAPPDATA"), "D3DSCache"),
]
_extra_zones = set()  # registradas por los módulos de limpieza (siguen sujetas al nivel 1)


def _list(pairs):
    return [(norm(p), why) for p, why in pairs if p]


_UNTOUCHABLE = _list(UNTOUCHABLE)
_ROOTS = _list(FOLDER_ROOTS)
_PROTECTED = _list(PROTECTED)
_ZONES = [norm(z) for z in CLEANUP_ZONES if z]


def allow_cleanup_zone(path):
    """Los módulos de limpieza declaran aquí sus carpetas de caché. Nunca abre nada del nivel 1."""
    p = norm(path)
    if any(_within(p, root) for root, _ in _UNTOUCHABLE):
        return False
    with _lock:
        _extra_zones.add(p)
    return True


class Blocked(PermissionError):
    """Operación bloqueada por la protección del sistema. str(e) es el motivo para el usuario."""


def check_path(path, is_dir=None):
    """Devuelve (permitido, motivo). Se evalúa la ruta escrita y la ruta real (enlaces/uniones)."""
    raw = os.path.normcase(os.path.abspath(os.path.expandvars(str(path)))).rstrip("\\")
    candidates = {raw, norm(path)}
    if is_dir is None:
        is_dir = os.path.isdir(path)
    for p in candidates:
        if re.fullmatch(r"[a-z]:", p):
            return False, "Es la raíz de una unidad completa; borrarla eliminaría todo su contenido."
        for root, why in _UNTOUCHABLE:
            if _within(p, root):
                return False, why
        if is_dir:
            for root, why in _ROOTS:
                if p == root:
                    return False, why
    zones = _ZONES + sorted(_extra_zones)
    for p in candidates:
        # dentro de una zona de limpieza se puede borrar; la carpeta de la zona en sí, no
        in_zone = any(_within(p, z) and not (p == z and is_dir) for z in zones)
        if in_zone:
            continue
        for root, why in _PROTECTED:
            if _within(p, root):
                return False, why
    return True, ""


def ensure_path(path, is_dir=None):
    ok, why = check_path(path, is_dir)
    if not ok:
        raise Blocked(f"{path}: {why}")


# ---------------------------------------------------------------- programas

PROTECTED_PROGRAMS = [
    (r"webview2", "Microsoft Edge WebView2 lo usan Windows y muchas apps (incluida esta) para mostrar su interfaz."),
    (r"visual c\+\+.*(redistributable|runtime)",
     "Las bibliotecas de Visual C++ las necesitan muchos programas y juegos para abrir."),
    (r"\.net (framework|runtime|desktop runtime)|microsoft \.net|asp\.net core",
     ".NET lo necesitan Windows y muchos programas para funcionar."),
    (r"windows app runtime|windowsappruntime|microsoft\.(ui\.xaml|vclibs|net\.native)",
     "Componente de Windows que usan las aplicaciones modernas."),
    (r"directx", "DirectX lo usan los juegos y programas con gráficos 3D."),
    (r"windows (sdk|software development kit)|windows driver kit", "Herramientas del sistema de Windows."),
    (r"^microsoft edge$", "Microsoft Edge es parte de Windows; otras funciones del sistema dependen de él."),
    (r"(graphics|display|audio|chipset|wlan|wi-?fi|bluetooth|ethernet|lan|serial io|management engine|"
     r"rapid storage|usb)\b.*\bdriver|driver\b.*(graphics|display|audio|chipset)|amd chipset|"
     r"nvidia (graphics|display|physx)|realtek.*(audio|ethernet|lan)|intel\(r\).*(driver|management)",
     "Es un controlador de hardware; quitarlo puede dejar sin imagen, sonido o red. Gestiona los "
     "controladores desde el Actualizador de controladores."),
]


def check_program(name, publisher="", location=""):
    n = (name or "").lower()
    for pat, why in PROTECTED_PROGRAMS:
        if re.search(pat, n):
            return False, why
    if location:
        loc = norm(location)
        for root, why in _UNTOUCHABLE:
            if _within(loc, root):
                return False, "Está instalado dentro de los archivos del sistema de Windows."
        if _within(loc, norm(WINDIR)):
            return False, "Es un componente instalado dentro de Windows."
    return True, ""


# ---------------------------------------------------------------- procesos y servicios

CRITICAL_PROCESSES = {
    "system": "Es el propio núcleo de Windows.",
    "registry": "Mantiene el registro de Windows en memoria.",
    "smss": "Administrador de sesiones; si se cierra, Windows se detiene (pantalla azul).",
    "csrss": "Subsistema de Windows; si se cierra, el equipo se bloquea con pantalla azul.",
    "wininit": "Inicia los servicios de Windows; si se cierra, el equipo se reinicia.",
    "winlogon": "Gestiona el inicio de sesión; si se cierra, se cierra tu sesión de golpe.",
    "services": "Administrador de servicios de Windows; si se cierra, el sistema falla.",
    "lsass": "Seguridad e inicio de sesión; si se cierra, Windows se reinicia.",
    "svchost": "Aloja servicios de Windows (red, audio, actualizaciones…).",
    "dwm": "Dibuja las ventanas en pantalla.",
    "fontdrvhost": "Carga las fuentes del sistema.",
    "memory compression": "Gestiona la memoria comprimida de Windows.",
    "secure system": "Seguridad basada en virtualización de Windows.",
    "lsaiso": "Protección de credenciales de Windows.",
    "msmpeng": "Antivirus Microsoft Defender en tiempo real.",
    "securityhealthservice": "Seguridad de Windows.",
    "sihost": "Infraestructura de la interfaz de Windows.",
    "ctfmon": "Entrada de teclado e idiomas.",
    "audiodg": "Motor de audio de Windows.",
    "spoolsv": "Cola de impresión.",
    "explorer": "Escritorio y barra de tareas; si lo cierras te quedas sin ellos hasta reiniciarlo.",
    "python": "PCLimpio se ejecuta con Python; finalizarlo cerraría esta misma aplicación.",
    "pythonw": "PCLimpio se ejecuta con Python; finalizarlo cerraría esta misma aplicación.",
}


def check_process(name):
    n = (name or "").lower().removesuffix(".exe")
    if n in CRITICAL_PROCESSES:
        return False, CRITICAL_PROCESSES[n]
    return True, ""


SECURITY_WORDS = r"(microsoft|windows) defender|windefend|msmpeng|antivirus|anti-malware|antimalware|bitdefender|kaspersky|eset|avast|avg|norton|" \
                 r"mcafee|malwarebytes|sophos|trend micro|panda|firewall|securityhealth"


def check_component(component):
    """Inicio, tareas y servicios: no se desactiva seguridad ni componentes de Windows."""
    text = " ".join(str(component.get(k, "")) for k in ("name", "company", "command", "location")).lower()
    if re.search(SECURITY_WORDS, text):
        return False, ("Es parte de tu antivirus o de la seguridad de Windows; desactivarlo deja el equipo "
                       "sin protección.")
    if component.get("type") == "servicio" and "microsoft" in str(component.get("company", "")).lower():
        return False, "Es un servicio de Windows."
    exe = component.get("exe") or ""
    if exe and component.get("type") != "inicio":
        ok, _ = check_path(exe, is_dir=False)
        if not ok and any(_within(norm(exe), r) for r, _ in _UNTOUCHABLE):
            return False, "Su programa está dentro de los archivos del sistema de Windows."
    return True, ""
