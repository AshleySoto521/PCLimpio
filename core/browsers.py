# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Localiza navegadores instalados y sus perfiles (Chromium y Firefox)."""
import glob
import os

from .util import expand

# data: carpeta con perfiles (historial, cookies...). cache: dónde guarda la caché (puede ser otra carpeta).
# flat=True: la carpeta ya es el perfil (Opera).
CHROMIUM = [
    {"id": "chrome", "name": "Google Chrome", "process": "chrome.exe",
     "data": r"%LOCALAPPDATA%\Google\Chrome\User Data"},
    {"id": "edge", "name": "Microsoft Edge", "process": "msedge.exe",
     "data": r"%LOCALAPPDATA%\Microsoft\Edge\User Data"},
    {"id": "brave", "name": "Brave", "process": "brave.exe",
     "data": r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data"},
    {"id": "vivaldi", "name": "Vivaldi", "process": "vivaldi.exe",
     "data": r"%LOCALAPPDATA%\Vivaldi\User Data"},
    {"id": "opera", "name": "Opera", "process": "opera.exe", "flat": True,
     "data": r"%APPDATA%\Opera Software\Opera Stable", "cache": r"%LOCALAPPDATA%\Opera Software\Opera Stable"},
    {"id": "operagx", "name": "Opera GX", "process": "opera.exe", "flat": True,
     "data": r"%APPDATA%\Opera Software\Opera GX Stable", "cache": r"%LOCALAPPDATA%\Opera Software\Opera GX Stable"},
]

FIREFOX = {"id": "firefox", "name": "Mozilla Firefox", "process": "firefox.exe",
           "data": r"%APPDATA%\Mozilla\Firefox\Profiles", "cache": r"%LOCALAPPDATA%\Mozilla\Firefox\Profiles"}


def chromium_profiles(b):
    """Devuelve [(perfil_datos, perfil_cache)] de un navegador Chromium instalado."""
    data = expand(b["data"])
    if not os.path.isdir(data):
        return []
    if b.get("flat"):
        return [(data, expand(b.get("cache", b["data"])))]
    profiles = []
    for name in os.listdir(data):
        p = os.path.join(data, name)
        if (name == "Default" or name.startswith("Profile ")) and os.path.isdir(p):
            profiles.append((p, p))
    return profiles


def firefox_profiles():
    data = expand(FIREFOX["data"])
    cache = expand(FIREFOX["cache"])
    out = []
    for p in glob.glob(os.path.join(data, "*")):
        if os.path.isdir(p):
            out.append((p, os.path.join(cache, os.path.basename(p))))
    return out


def installed():
    """Lista de navegadores con al menos un perfil: dicts con id, name, process, kind, profiles."""
    result = []
    for b in CHROMIUM:
        profs = chromium_profiles(b)
        if profs:
            result.append({**b, "kind": "chromium", "profiles": profs})
    profs = firefox_profiles()
    if profs:
        result.append({**FIREFOX, "kind": "firefox", "profiles": profs})
    return result
