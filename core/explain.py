# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Traduce rutas técnicas a lenguaje cotidiano: qué es, si se puede borrar y qué conviene hacer.

Pensado para personas sin conocimientos técnicos. Cada resultado tiene:
  title          nombre amigable ("Actualizaciones de Windows ya descargadas")
  what           qué es, en una frase sin tecnicismos
  verdict        "borrar" | "limpiar" | "revisar" | "tuyo" | "no"
  verdict_label  el veredicto en palabras
  advice         qué hacer, en una frase
  page           (opcional) sección de la app donde se resuelve de forma segura
"""
import os
import re
import time
import winreg

from . import safety

VERDICTS = {
    "borrar": "Puedes borrarlo",
    "limpiar": "Seguro: límpialo con la app",
    "revisar": "Revisa antes de borrar",
    "tuyo": "Es tuyo: decide tú",
    "no": "No lo borres",
}

# (nombre, posesivo con su género)
TYPE_NAMES = {
    "video": ("Video", "tuyo"), "picture": ("Imagen", "tuya"), "music": ("Audio", "tuyo"),
    "document": ("Documento", "tuyo"), "application": ("Programa", "tuyo"),
    "archive": ("Archivo comprimido", "tuyo"), "other": ("Archivo", "tuyo"),
}


def E(v):
    return os.path.normcase(os.path.expandvars(v)).rstrip("\\")


HOME = os.path.normcase(os.path.expanduser("~"))
SYSROOT = E("%SYSTEMDRIVE%")

# Lugares conocidos: (ruta, título, qué es, veredicto, consejo, página)
PLACES = [
    (r"%WINDIR%\SoftwareDistribution\Download", "Actualizaciones de Windows ya descargadas",
     "Copias de actualizaciones que Windows ya instaló.", "limpiar",
     "Límpialo desde Limpieza avanzada. Si Windows las necesita otra vez, las vuelve a descargar.", "advanced"),
    (r"%WINDIR%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization",
     "Copias de actualizaciones para compartir",
     "Windows guarda pedazos de actualizaciones para pasárselos a otros equipos y descargar más rápido.",
     "limpiar", "Límpialo desde Limpieza avanzada; no afecta a tus archivos ni a Windows.", "advanced"),
    (r"%WINDIR%\Temp", "Archivos temporales de Windows",
     "Archivos que Windows y los programas usan un momento y luego olvidan borrar.", "limpiar",
     "Límpialo desde Limpieza básica.", "basic"),
    (r"%TEMP%", "Archivos temporales",
     "Archivos que los programas usan un momento y luego olvidan borrar.", "limpiar",
     "Límpialo desde Limpieza básica.", "basic"),
    (r"%WINDIR%\Prefetch", "Datos para abrir programas más rápido",
     "Windows anota cómo abre cada programa para acelerarlo la próxima vez.", "revisar",
     "No hace falta borrarlo: ocupa poco y se vuelve a crear.", "advanced"),
    (r"%WINDIR%\Logs", "Registros de Windows", "Notas internas que Windows escribe sobre lo que hace.", "limpiar",
     "Los antiguos se limpian desde Limpieza avanzada.", "advanced"),
    (r"%WINDIR%\Minidump", "Informes de fallos de Windows",
     "Se crean cuando el equipo se cuelga o se reinicia solo; sirven para averiguar la causa.", "limpiar",
     "Si tu equipo funciona bien, bórralos desde Limpieza básica.", "basic"),
    (r"%LOCALAPPDATA%\CrashDumps", "Informes de fallos de programas",
     "Se crean cuando un programa se cierra de golpe.", "limpiar", "Bórralos desde Limpieza básica.", "basic"),
    (r"%LOCALAPPDATA%\Microsoft\Windows\Explorer", "Miniaturas de imágenes",
     "Vistas previas de fotos y videos para que las carpetas carguen rápido.", "limpiar",
     "Se vuelven a crear solas; límpialas desde Limpieza básica.", "basic"),
    (r"%WINDIR%\Installer", "Instaladores guardados por Windows",
     "Windows los usa para reparar o desinstalar programas.", "no",
     "Si se borran, después no podrás desinstalar ni reparar algunos programas.", None),
    (r"%ProgramData%\Package Cache", "Instaladores guardados de programas",
     "Copias que los programas necesitan para actualizarse o desinstalarse.", "no", "Déjalo como está.", None),
    (r"%SYSTEMDRIVE%\$Recycle.Bin", "Papelera de reciclaje", "Archivos que ya borraste y siguen en la Papelera.",
     "limpiar", "Vacía la Papelera desde Limpieza básica (revisa antes que no haya nada importante).", "basic"),
    (r"%SYSTEMDRIVE%\System Volume Information", "Puntos de restauración",
     "Copias que permiten devolver Windows a como estaba si algo falla.", "no",
     "Déjalo como está; es tu red de seguridad.", None),
    (r"%SYSTEMDRIVE%\AMD", "Restos del instalador de AMD",
     "Archivos que dejó el instalador de controladores de AMD después de instalar.", "limpiar",
     "Ya no se usan; límpialos desde Limpieza avanzada → Restos de instaladores de controladores.", "advanced"),
    (r"%SYSTEMDRIVE%\NVIDIA", "Restos del instalador de NVIDIA",
     "Archivos que dejó el instalador de controladores de NVIDIA después de instalar.", "limpiar",
     "Ya no se usan; límpialos desde Limpieza avanzada → Restos de instaladores de controladores.", "advanced"),
    (os.path.join("%USERPROFILE%", "Saved Games"), "Partidas guardadas",
     "Aquí muchos juegos guardan tus partidas.", "no", "Si lo borras pierdes tu progreso en esos juegos.", None),
]
PLACES = [(E(p), *rest) for p, *rest in PLACES]

SPECIAL_FILES = {
    "pagefile.sys": ("Memoria de apoyo de Windows",
                     "Windows lo usa como memoria extra cuando la RAM no alcanza.", "no", "Es necesario; no se puede borrar."),
    "hiberfil.sys": ("Archivo de hibernación",
                     "Guarda lo que tenías abierto cuando el equipo hiberna.", "no", "Es necesario para hibernar."),
    "swapfile.sys": ("Memoria de apoyo de las apps",
                     "Windows lo usa para las aplicaciones de la Tienda.", "no", "Es necesario; no se puede borrar."),
    "memory.dmp": ("Informe de un fallo grave de Windows",
                   "Se creó cuando el equipo se colgó con pantalla azul.", "limpiar",
                   "Si tu equipo funciona bien, bórralo desde Limpieza básica."),
}

GPU_CACHE_WORDS = {"dxcache", "glcache", "d3dscache", "dxccache", "shadercache", "grshadercache"}

CACHE_WORDS = {"cache", "cache_data", "code cache", "gpucache", "cache2", "shadercache", "grshadercache",
               "dxcache", "d3dscache", "glcache", "dxccache", "httpcache", "cachestorage", "cacheddata",
               "_cacache", "startupcache"}

USER_FOLDERS = {"downloads": "Descargas", "desktop": "Escritorio", "documents": "Documentos",
                "pictures": "Imágenes", "videos": "Videos", "music": "Música", "onedrive": "OneDrive"}

GAME_DOC_FOLDERS = {"electronic arts", "my games", "rockstar games", "ubisoft", "saved games", "square enix",
                    "bioware", "paradox interactive", "klei", "battlefield", "call of duty"}

VENDOR_DIRS = {"google", "microsoft", "mozilla", "bravesoftware", "adobe", "nvidia", "nvidia corporation", "amd",
               "packages", "programs", "electronic arts", "ea games", "common files", "ubisoft", "epic games"}

PRETTY = {"discord": "Discord", "spotify": "Spotify", "code": "Visual Studio Code", "chrome": "Google Chrome",
          "edge": "Microsoft Edge", "firefox": "Firefox", "brave-browser": "Brave", "teams": "Microsoft Teams",
          "msteams": "Microsoft Teams", "steam": "Steam", "zoom": "Zoom", "whatsapp": "WhatsApp",
          "telegram desktop": "Telegram", "npm-cache": "npm", "pip": "Python", "docker": "Docker",
          "slack": "Slack", "onedrive": "OneDrive", "nvidia corporation": "NVIDIA", "nvidia": "NVIDIA",
          "amd": "AMD", "bravesoftware": "Brave", "terminal server client": "Escritorio remoto",
          "microsoft terminal server client": "Escritorio remoto", "electronic arts": "Electronic Arts", "ea games": "EA Games"}


def _pretty(name):
    if name.lower() in PRETTY:
        return PRETTY[name.lower()]
    name = re.sub(r"[_\-]+", " ", name).strip()
    return name[:1].upper() + name[1:]


def _within(p, root):
    return p == root or p.startswith(root + "\\")


# ---------------------------------------------------------------- a qué programa pertenece

_programs = {"t": 0, "map": []}


def _program_locations():
    """(ruta_instalación, nombre) de los programas instalados, de la ruta más larga a la más corta."""
    if time.time() - _programs["t"] < 300:
        return _programs["map"]
    out = []
    key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                       (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY), (winreg.HKEY_CURRENT_USER, 0)):
        try:
            root = winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view)
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
                        name = winreg.QueryValueEx(k, "DisplayName")[0]
                        loc = winreg.QueryValueEx(k, "InstallLocation")[0].strip('" ')
                except OSError:
                    continue
                if name and loc and len(loc) > 3:
                    out.append((os.path.normcase(loc).rstrip("\\"), name.strip()))
    out.sort(key=lambda x: len(x[0]), reverse=True)
    _programs.update(t=time.time(), map=out)
    return out


def owner_program(p):
    for loc, name in _program_locations():
        if _within(p, loc):
            return name
    return None


def _segment_owner(orig, p, root):
    """Nombre de la app a partir de la carpeta que sigue a root, respetando mayúsculas de la ruta original."""
    rest = orig[len(root):].strip("\\").split("\\")
    if not rest or not rest[0]:
        return None
    first = rest[0]
    if first.lower() in VENDOR_DIRS and len(rest) > 1:
        second = rest[1]
        if first.lower() == "packages":
            return _pretty(second.split("_")[0].split(".")[-1])
        if first.lower() in ("programs", "common files"):
            return _pretty(second)
        vendor, product = _pretty(first), _pretty(second)
        if vendor.lower().split()[0] in product.lower():
            return product  # "Google\Chrome" → "Google Chrome", no "Google Google Chrome"
        return f"{vendor} {product}"
    return _pretty(first)


def _owner(orig, p, roots):
    prog = owner_program(p)
    if prog:
        return prog
    for r in roots:
        if _within(p, r):
            return _segment_owner(orig, p, r)
    return None


def _uninstall_advice(prog):
    ok, _ = safety.check_program(prog)
    if not ok or re.search(r"edge|webview", prog, re.I):
        return f"{prog} es necesario para Windows o para otros programas; déjalo como está."
    if re.search(r"update", prog, re.I):
        return f"Mantiene un programa al día y se gestiona solo; se quita al desinstalar ese programa."
    return f"Si ya no usas {prog}, desinstálalo desde Programas instalados; así se borra completo y bien."


# ---------------------------------------------------------------- explicación

def _r(title, what, verdict, advice, page=None):
    return {"title": title, "what": what, "verdict": verdict, "verdict_label": VERDICTS[verdict],
            "advice": advice, "page": page}


def _by_type(orig, category, where):
    """Explicación según el tipo de archivo (para archivos personales o sueltos)."""
    name = os.path.basename(orig)
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if ext in (".vhd", ".vhdx", ".vmdk", ".vdi"):
        return _r("Disco virtual", "Un disco completo guardado dentro de un archivo (máquinas virtuales, Linux en "
                  "Windows o Docker).", "revisar",
                  "Si no sabes qué es, no lo borres: alguna herramienta instalada podría depender de él.")
    if ext in (".pst", ".ost"):
        return _r("Correos de Outlook", "Aquí están guardados tus correos de Outlook.", "no",
                  "No lo borres a menos que tengas copia; perderías tus correos.")
    if ext in (".exe", ".msi", ".msix") and where == "downloads":
        return _r("Instalador descargado", f"El programa de instalación «{name}» que bajaste de Internet.", "borrar",
                  "Si ya instalaste ese programa, el instalador ya no hace falta.")
    if ext in (".iso", ".img"):
        return _r("Imagen de disco", "Es como un CD o DVD guardado en un archivo (suele servir para instalar algo).",
                  "revisar", "Si ya instalaste o usaste lo que contenía, puedes borrarla.")
    if category == "archive":
        return _r("Archivo comprimido", f"«{name}» guarda otros archivos dentro, como una carpeta empaquetada.",
                  "revisar", "Si ya lo descomprimiste y tienes los archivos, puedes borrarlo.")
    if ext in (".bak", ".old", ".backup"):
        return _r("Copia de seguridad antigua", f"Una copia vieja de un archivo («{name}»).", "revisar",
                  "Si el archivo original está bien, normalmente puedes borrarla.")
    if ext in (".tmp", ".temp"):
        return _r("Archivo temporal", "Un programa lo usó un momento y lo dejó olvidado.", "borrar",
                  "Puedes borrarlo si ningún programa lo está usando.")
    if ext == ".log":
        return _r("Registro de un programa", "Notas internas que un programa escribe sobre lo que hace.", "borrar",
                  "Normalmente se puede borrar sin problema.")
    if ext in (".dmp", ".mdmp"):
        return _r("Informe de un fallo", "Se creó cuando un programa se cerró de golpe.", "borrar",
                  "Si ese programa ya funciona bien, puedes borrarlo.")
    if "cache" in low:
        return _r("Archivo de caché", "Copia temporal que un programa o juego guarda para cargar más rápido.",
                  "revisar", "Suele volver a crearse solo. Cierra el programa o juego antes de borrarlo.")
    label, mine = TYPE_NAMES.get(category, TYPE_NAMES["other"])
    return _r(f"{label} {mine}", f"«{name}» es un archivo personal.", "tuyo",
              "Solo tú sabes si lo necesitas. Si dudas, cópialo a una memoria USB o disco externo antes de borrarlo.")


def explain(path, is_dir=False, category="other"):
    orig = os.path.abspath(path).rstrip("\\")
    p = os.path.normcase(orig)
    allowed, _ = safety.check_path(path, is_dir)
    info = _explain(orig, p, is_dir, category)
    if not allowed and info["verdict"] in ("borrar", "tuyo", "revisar"):
        # Seguro en sí, pero la app solo lo borra desde su limpieza (que sabe hacerlo sin romper nada)
        if info["verdict"] == "borrar":
            info.update(verdict="limpiar", verdict_label=VERDICTS["limpiar"])
        else:
            info.update(verdict="no", verdict_label=VERDICTS["no"])
    info["protected"] = not allowed
    return info


def _explain(orig, p, is_dir, category):
    base = os.path.basename(p)
    if not is_dir and base in SPECIAL_FILES:
        t, w, v, a = SPECIAL_FILES[base]
        return _r(t, w, v, a, "basic" if v == "limpiar" else None)
    if re.fullmatch(r"[a-z]:", p):
        return _r(f"Unidad {orig.upper()}", "Un disco completo.", "no", "Revisa sus carpetas por separado.")
    if p == os.path.dirname(HOME):
        return _r("Carpetas de los usuarios del equipo", "Aquí está la carpeta personal de cada usuario.", "no",
                  "Revisa tus carpetas (Descargas, Documentos…) por separado.")

    for root, title, what, verdict, advice, page in PLACES:
        if _within(p, root):
            return _r(title, what, verdict, advice, page)

    appdata = [E("%LOCALAPPDATA%"), E("%APPDATA%"), os.path.join(HOME, "appdata", "locallow")]
    progfiles = [E("%ProgramFiles%"), E("%ProgramFiles(x86)%")]

    segments = p.split("\\")
    if any(s in GPU_CACHE_WORDS for s in segments):
        vendor = next((PRETTY[s] for s in segments if s in ("nvidia", "amd")), None)
        return _r(f"Caché de gráficos{' de ' + vendor if vendor else ''}",
                  "Tu tarjeta gráfica guarda aquí efectos ya preparados para que juegos y programas carguen más rápido.",
                  "limpiar", "Se vuelve a crear sola. Límpiala desde Limpieza básica → Caché de sombreadores.", "basic")

    # Cachés de cualquier programa: se regeneran solas
    if any(s in CACHE_WORDS for s in segments):
        owner = _owner(orig, p, appdata + progfiles + [E("%ProgramData%")])
        who = f" de {owner}" if owner else ""
        return _r(f"Caché{who}", f"Copias temporales que {owner or 'un programa'} guarda para cargar más rápido.",
                  "limpiar", "Se vuelve a crear sola. Las de los navegadores y apps conocidas se limpian desde "
                  "Limpieza básica o avanzada; las demás no hace falta tocarlas.", "basic")

    m = re.search(r"\\steamapps\\common\\([^\\]+)", p)
    if m:
        game = orig[m.start(1):m.end(1)]
        return _r(f"Juego «{game}» (Steam)", f"Archivos del juego {game}.", "no",
                  "Si ya no lo juegas, desinstálalo desde Steam; así se borra completo y bien.")

    if _within(p, E("%WINDIR%")):
        return _r("Archivo de Windows", "Forma parte del sistema operativo.", "no",
                  "Windows lo necesita para funcionar. No hace falta tocarlo.")

    for pf in progfiles:
        if p == pf:
            return _r("Programas instalados", "Aquí están todos tus programas.", "no",
                      "Para liberar espacio, desinstala los que no uses desde Programas instalados.", "software")
        if _within(p, pf):
            prog = _owner(orig, p, [pf]) or "un programa"
            if is_dir and not owner_program(p):
                return _r(f"Programas de {prog}", f"Carpeta con programas instalados de {prog}.", "no",
                          "Desinstala desde Programas instalados los que ya no uses.", "software")
            return _r(f"Parte del programa «{prog}»", f"Es un archivo que {prog} necesita para funcionar.", "no",
                      _uninstall_advice(prog), "software")

    if _within(p, E("%ProgramData%")):
        owner = _owner(orig, p, [E("%ProgramData%")])
        return _r(f"Datos compartidos de {owner}" if owner else "Datos compartidos de programas",
                  "Configuración, licencias o datos que el programa comparte entre usuarios.", "no",
                  _uninstall_advice(owner) if owner else "Déjalo como está.", "software")

    for root in appdata:
        if _within(p, root):
            if p.endswith((".vhdx", ".vhd")):
                info = _by_type(orig, category, "appdata")
                info["verdict"], info["verdict_label"] = "no", VERDICTS["no"]
                return info
            owner = _owner(orig, p, [root]) or "un programa"
            installed = owner_program(p)
            tail = (_uninstall_advice(installed) if installed
                    else "Si ya no usas ese programa, desinstálalo desde Programas instalados.")
            return _r(f"Datos de {owner}", f"Aquí {owner} guarda tu configuración, sesiones o datos.", "no",
                      f"Si lo borras a mano puedes perder tus ajustes o tu sesión. {tail}", "software")

    if _within(p, HOME):
        rest = orig[len(HOME):].strip("\\").split("\\")
        folder = rest[0].lower() if rest and rest[0] else ""
        if p == HOME:
            return _r("Tu carpeta personal", "Contiene todos tus documentos, descargas, fotos y configuración.", "no",
                      "Revisa sus carpetas por separado.")
        if folder == "documents" and len(rest) > 1 and rest[1].lower() in GAME_DOC_FOLDERS:
            game = rest[2] if len(rest) > 2 else rest[1]
            if is_dir or "cache" not in base:
                return _r(f"Partidas y ajustes de «{game}»",
                          "Aquí el juego guarda tus partidas, mods y configuración.", "no",
                          "Si lo borras pierdes tu progreso en el juego.")
        if folder in USER_FOLDERS:
            pretty = USER_FOLDERS[folder]
            if is_dir:
                if len(rest) == 1:
                    return _r(f"Tu carpeta {pretty}", f"Todo lo que tienes en {pretty}.", "tuyo",
                              "Ábrela y revisa qué ya no necesitas.")
                return _r(f"Carpeta «{os.path.basename(orig)}» en {pretty}", "Una carpeta tuya.", "tuyo",
                          "Ábrela para ver qué contiene antes de decidir.")
            info = _by_type(orig, category, folder)
            if folder == "onedrive":
                info["advice"] = "Ojo: si lo borras aquí, también se borra de tu OneDrive. " + info["advice"]
            return info
        if is_dir:
            return _r(f"Carpeta «{os.path.basename(orig)}»", "Una carpeta dentro de tu usuario.", "revisar",
                      "Ábrela para ver qué contiene antes de decidir.")
        return _by_type(orig, category, "home")

    # Fuera de tus carpetas, en el disco de Windows: probablemente de algún programa
    if _within(p, SYSROOT):
        prog = owner_program(p)
        if prog:
            return _r(f"Parte del programa «{prog}»", f"Es un archivo que {prog} necesita para funcionar.", "no",
                      _uninstall_advice(prog), "software")
        if is_dir:
            return _r(f"Carpeta «{os.path.basename(orig)}»", "Está fuera de tus carpetas personales; "
                      "puede ser de un programa.", "revisar", "Si no sabes de dónde salió, mejor no la borres.")
        info = _by_type(orig, category, "system-drive")
        if info["verdict"] == "tuyo":
            info.update(title=TYPE_NAMES.get(category, TYPE_NAMES["other"])[0], verdict="revisar",
                        verdict_label=VERDICTS["revisar"],
                        what=f"«{os.path.basename(orig)}» está fuera de tus carpetas personales; puede ser de un programa.",
                        advice="Si no sabes de dónde salió, mejor no lo borres.")
        return info

    # Otras unidades (D:, USB…): normalmente archivos del usuario
    if is_dir:
        return _r(f"Carpeta «{os.path.basename(orig)}»", "Una carpeta de tus discos.", "tuyo",
                  "Ábrela para ver qué contiene antes de decidir.")
    return _by_type(orig, category, "other")
