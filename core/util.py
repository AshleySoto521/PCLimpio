# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Utilidades compartidas: rutas, tamaños, PowerShell, permisos y Papelera de reciclaje."""
import ctypes
import ctypes.wintypes as wt
import json
import logging
import os
import stat
import subprocess
import sys
import time

from . import safety

APP_NAME = "PCLimpio"
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
LOG_DIR = os.path.join(DATA_DIR, "logs")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

log = logging.getLogger(APP_NAME)
if not log.handlers:
    _h = logging.FileHandler(os.path.join(LOG_DIR, "pclimpio.log"), encoding="utf-8")
    _h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s [%(module)s] %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)

CREATE_NO_WINDOW = 0x08000000
FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_COMPRESSED = 0x800
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def expand(path):
    return os.path.normpath(os.path.expandvars(path))


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


# Empaquetada como .exe (PyInstaller) o ejecutada con Python
FROZEN = getattr(sys, "frozen", False)
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts):
    """Ruta a archivos de la app (la interfaz). En el .exe se extraen a una carpeta temporal."""
    base = getattr(sys, "_MEIPASS", APP_ROOT)
    return os.path.join(base, *parts)


def app_command(*args):
    """(programa, argumentos) para volver a lanzar PCLimpio: el .exe o pythonw + main.py."""
    if FROZEN:
        return sys.executable, list(args)
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    return exe, [os.path.join(APP_ROOT, "main.py"), *args]


def relaunch_as_admin(extra_args=()):
    """Vuelve a lanzar la app con elevación (UAC). Devuelve True si Windows aceptó la petición."""
    exe, args = app_command(*extra_args)
    params = " ".join(f'"{a}"' for a in args)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def run(cmd, timeout=600, shell=False):
    """Ejecuta un comando sin ventana. Devuelve (código, salida combinada)."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, shell=shell,
                           creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return -1, "Tiempo de espera agotado"
    except OSError as e:
        return -1, str(e)
    out = p.stdout + (b"\n" + p.stderr if p.stderr else b"")
    for enc in ("utf-8", "cp850", "mbcs"):
        try:
            return p.returncode, out.decode(enc)
        except UnicodeDecodeError:
            continue
    return p.returncode, out.decode("utf-8", "replace")


def run_ps(script, timeout=300):
    """Ejecuta un script de PowerShell y devuelve su salida JSON ya decodificada (o None)."""
    wrapped = ("$ErrorActionPreference='SilentlyContinue';"
               "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
               f"$__r = & {{ {script} }}; if ($null -ne $__r) {{ $__r | ConvertTo-Json -Depth 6 -Compress }}")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", wrapped], capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        log.warning("PowerShell agotó el tiempo: %s", script[:120])
        return None
    text = p.stdout.decode("utf-8", "replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("Salida no JSON de PowerShell: %s", text[:300])
        return None


def as_list(value):
    """ConvertTo-Json devuelve un objeto suelto cuando hay un solo elemento."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def running_processes():
    """Nombres (en minúsculas) de los procesos en ejecución."""
    _, out = run(["tasklist", "/FO", "CSV", "/NH"], timeout=30)
    names = set()
    for line in out.splitlines():
        if line.startswith('"'):
            names.add(line.split('","')[0].strip('"').lower())
    return names


def close_processes(names, force=False, wait=8):
    """Cierra procesos por nombre (primero de forma ordenada) y espera a que terminen."""
    for name in names:
        cmd = ["taskkill", "/IM", name, "/T"] + (["/F"] if force else [])
        run(cmd, timeout=30)
    deadline = time.time() + wait
    while time.time() < deadline:
        if not (set(n.lower() for n in names) & running_processes()):
            return True
        time.sleep(0.5)
    if not force:
        return close_processes(names, force=True, wait=4)
    return False


def file_attrs(st):
    return getattr(st, "st_file_attributes", 0)


def is_reparse(entry):
    try:
        return entry.is_symlink() or bool(file_attrs(entry.stat(follow_symlinks=False)) & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def remove_file(path):
    """Borra un archivo (quitando solo-lectura si hace falta). Devuelve bytes liberados o None si falla.

    Lanza safety.Blocked si la ruta está protegida (aunque la app sea administrador).
    """
    safety.ensure_path(path, is_dir=False)
    try:
        size = os.path.getsize(path)
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)
        return size
    except OSError:
        return None


def remove_empty_dirs(root):
    """Elimina subcarpetas vacías bajo root (sin borrar root)."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root or not safety.check_path(dirpath, is_dir=True)[0]:
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:
            pass


# ---------------------------------------------------------------- Papelera de reciclaje (shell32)

class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wt.HWND), ("wFunc", wt.UINT), ("pFrom", wt.LPCWSTR), ("pTo", wt.LPCWSTR),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wt.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wt.LPCWSTR)]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400


def recycle_bin_info(root=None):
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(root, ctypes.byref(info)) != 0:
        return 0, 0
    return info.i64Size, info.i64NumItems


def empty_recycle_bin():
    size, _ = recycle_bin_info()
    flags = 0x1 | 0x2 | 0x4  # sin confirmación, sin progreso, sin sonido
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    return size if hr in (0, -2147418113) else 0  # E_UNEXPECTED = papelera ya vacía


def send_to_recycle_bin(paths):
    """Mueve archivos a la Papelera (se pueden recuperar). Devuelve True si no hubo errores.

    Lanza safety.Blocked si alguna ruta está protegida; en ese caso no se mueve ninguna.
    """
    paths = [os.path.abspath(p) for p in paths if os.path.exists(p)]
    for p in paths:
        safety.ensure_path(p)
    if not paths:
        return True
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(paths) + "\0\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


# ---------------------------------------------------------------- Unidades

def list_drives():
    """Unidades con letra: tipo, sistema de archivos, capacidad y espacio libre."""
    k32 = ctypes.windll.kernel32
    buf = ctypes.create_unicode_buffer(512)
    k32.GetLogicalDriveStringsW(512, buf)
    types = {2: "extraíble", 3: "local", 4: "red", 5: "cd/dvd", 6: "ram"}
    drives = []
    for root in buf[:].split("\0"):
        if not root:
            continue
        dtype = k32.GetDriveTypeW(root)
        if dtype not in (2, 3):
            continue
        label = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        serial = wt.DWORD()
        k32.GetVolumeInformationW(root, label, 261, ctypes.byref(serial), None, None, fs, 261)
        free, total = ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if not k32.GetDiskFreeSpaceExW(root, None, ctypes.byref(total), ctypes.byref(free)):
            continue
        drives.append({"root": root, "letter": root[0], "label": label.value or "Disco local",
                       "type": types.get(dtype, "otro"), "fs": fs.value, "total": total.value,
                       "free": free.value, "used": total.value - free.value})
    return drives
