# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Historial de actividad: todo lo que PCLimpio borra o cambia queda anotado con fecha y hora.

Sirve para que el usuario vea exactamente qué hizo la app (y qué no hizo). Se guarda en un archivo
de texto (una línea JSON por acción) en la carpeta de datos de la app; nunca sale del equipo.
"""
import json
import os
import threading
import time

from .util import DATA_DIR

FILE = os.path.join(DATA_DIR, "actividad.jsonl")
_lock = threading.Lock()
MAX_DETAILS = 2000  # rutas guardadas por acción (para no crear un archivo gigante)


def record(section, summary, details=None, freed=0):
    """section: módulo ("Limpieza básica"…), summary: frase legible, details: lista de rutas/elementos."""
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "section": section, "summary": summary,
             "freed": int(freed or 0), "details": [str(d) for d in (details or [])][:MAX_DETAILS]}
    with _lock, open(FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read(limit=300):
    try:
        with open(FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines[-limit:]):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
