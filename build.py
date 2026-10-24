# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Compila PCLimpio en un solo archivo PCLimpio.exe que funciona sin tener Python instalado.

Uso (con PyInstaller instalado):
    py -3 -m pip install pyinstaller
    py -3 build.py

Resultado: dist/PCLimpio.exe y dist/PCLimpio.exe.sha256 (huella para comprobar la descarga).
"""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.version import AUTHOR, COPYRIGHT, LICENSE, VERSION  # noqa: E402

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', '{author}'),
      StringStruct('FileDescription', 'PCLimpio - mantenimiento de Windows 100 % local'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'PCLimpio'),
      StringStruct('LegalCopyright', '{copyright} - Licencia {license}'),
      StringStruct('OriginalFilename', 'PCLimpio.exe'),
      StringStruct('ProductName', 'PCLimpio'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x040A, 1200])])
  ]
)
"""


def main():
    build = os.path.join(ROOT, "build")
    os.makedirs(build, exist_ok=True)
    nums = [int(x) for x in VERSION.split(".")] + [0] * (4 - len(VERSION.split(".")))
    vfile = os.path.join(build, "version_info.txt")
    with open(vfile, "w", encoding="utf-8") as f:
        f.write(VERSION_INFO.format(t=", ".join(map(str, nums[:4])), v=VERSION, author=AUTHOR,
                                    copyright=COPYRIGHT, license=LICENSE))
    icon = os.path.join(ROOT, "assets", "icon.ico")
    if not os.path.exists(icon):
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_icon.py")], check=True)
    cmd = [sys.executable, "-m", "PyInstaller", os.path.join(ROOT, "main.py"),
           "--name", "PCLimpio", "--onefile", "--noconsole", "--clean", "--noconfirm",
           "--icon", icon, "--version-file", vfile,
           "--add-data", f"{os.path.join(ROOT, 'ui')}{os.pathsep}ui",
           "--distpath", os.path.join(ROOT, "dist"), "--workpath", build, "--specpath", build]
    if os.path.exists(os.path.join(ROOT, "LICENSE")):  # la licencia viaja dentro del .exe
        cmd += ["--add-data", f"{os.path.join(ROOT, 'LICENSE')}{os.pathsep}."]
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = os.path.join(ROOT, "dist", "PCLimpio.exe")
    digest = hashlib.sha256(open(exe, "rb").read()).hexdigest()
    with open(exe + ".sha256", "w") as f:
        f.write(f"{digest}  PCLimpio.exe\n")
    print(f"\nListo: {exe} ({os.path.getsize(exe) / 2**20:.1f} MB)\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
