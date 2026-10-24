# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Analizador de disco: qué tipos de archivo, carpetas y archivos ocupan más, y archivos duplicados.

Mismo modelo que el Disk Analyzer de CCleaner: elegir unidades o carpetas, recorrer el árbol con filtros
(tamaño mínimo, ocultos, sistema, solo lectura, comprimidos, tipos), sumar bytes por categoría y, si se pide,
buscar duplicados. Los duplicados se confirman por contenido: mismo tamaño → hash parcial → hash completo.
"""
import hashlib
import heapq
import os
import time
from collections import defaultdict

from . import activity, explain, safety
from .util import (FILE_ATTRIBUTE_COMPRESSED, FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_READONLY,
                   FILE_ATTRIBUTE_REPARSE_POINT, FILE_ATTRIBUTE_SYSTEM, list_drives, log,
                   remove_file, send_to_recycle_bin)

CATEGORIES = {
    "video": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".3gp", ".ts", ".vob"},
    "picture": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".tif", ".tiff", ".webp", ".ico", ".raw", ".heic",
                ".psd", ".cr2", ".nef", ".arw", ".dng"},
    "music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus", ".aiff", ".mid"},
    "document": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".rtf", ".odt", ".ods", ".odp",
                 ".csv", ".epub", ".md", ".pages"},
    "application": {".exe", ".msi", ".dll", ".sys", ".msix", ".appx", ".bat", ".cmd", ".com", ".jar", ".apk"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".cab", ".iso", ".img", ".tgz", ".zst", ".vhd",
                ".vhdx", ".wim"},
}
CATEGORY_NAMES = {"video": "Video", "picture": "Imágenes", "music": "Música", "document": "Documentos",
                  "application": "Aplicaciones", "archive": "Comprimidos e imágenes de disco", "other": "Otros"}
_EXT = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}

TOP_FILES = 300
TOP_FOLDERS = 200
FOLDER_DEPTH = 4          # profundidad a la que se acumulan tamaños por carpeta
PARTIAL = 64 * 1024        # bytes leídos al inicio y al final para el hash parcial

_last_scan = {}            # resultado completo del último escaneo (para filtrar sin reescanear)

def protected(path):
    """Archivos de Windows o de programas: no se ofrecen como duplicados (sí cuentan en los tamaños)."""
    return not safety.check_path(path, is_dir=False)[0]


def category_of(name):
    return _EXT.get(os.path.splitext(name)[1].lower(), "other")


def drives():
    return list_drives()


def _excluded(attrs, opts):
    return ((opts.get("ignore_hidden") and attrs & FILE_ATTRIBUTE_HIDDEN)
            or (opts.get("ignore_system") and attrs & FILE_ATTRIBUTE_SYSTEM)
            or (opts.get("ignore_readonly") and attrs & FILE_ATTRIBUTE_READONLY)
            or (opts.get("ignore_compressed") and attrs & FILE_ATTRIBUTE_COMPRESSED))


def scan(job, items, opts):
    """items: lista de rutas raíz (unidades 'C:\\' o carpetas). opts: filtros, ver _excluded y min_size."""
    min_size = int(opts.get("min_size", 64 * 1024))
    ignore_types = set(opts.get("ignore_types", []))
    find_dupes = bool(opts.get("duplicates", True))
    by_cat = defaultdict(lambda: [0, 0])          # categoría -> [bytes, archivos]
    folder_size = defaultdict(int)
    top = []                                      # heap de (tamaño, ruta)
    by_size = defaultdict(list)                   # para duplicados
    scanned = errors = 0
    total_bytes = 0
    started = time.time()
    roots = [os.path.abspath(i) for i in items]
    for ri, root in enumerate(roots):
        root_depth = root.rstrip("\\").count("\\")
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                errors += 1
                continue
            with it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        errors += 1
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if not (opts.get("ignore_hidden") and attrs & FILE_ATTRIBUTE_HIDDEN) and \
                                not (opts.get("ignore_system") and attrs & FILE_ATTRIBUTE_SYSTEM):
                            stack.append(e.path)
                        continue
                    if _excluded(attrs, opts):
                        continue
                    cat = category_of(e.name)
                    if cat in ignore_types:
                        continue
                    size = st.st_size
                    scanned += 1
                    total_bytes += size
                    by_cat[cat][0] += size
                    by_cat[cat][1] += 1
                    # acumular en carpetas ancestro hasta FOLDER_DEPTH niveles bajo la raíz
                    parent = os.path.dirname(e.path)
                    depth = parent.rstrip("\\").count("\\") - root_depth
                    while depth > FOLDER_DEPTH:
                        parent = os.path.dirname(parent)
                        depth -= 1
                    while depth >= 1:
                        folder_size[parent] += size
                        parent = os.path.dirname(parent)
                        depth -= 1
                    if size >= min_size:
                        item = (size, e.path)
                        if len(top) < TOP_FILES:
                            heapq.heappush(top, item)
                        elif size > top[0][0]:
                            heapq.heapreplace(top, item)
                        if find_dupes and size > 0 and not protected(e.path):
                            by_size[size].append((e.path, st.st_ctime, st.st_mtime))
                    if scanned % 3000 == 0:
                        job.update(min(60, 60 * ri / len(roots) + 5), f"{scanned:,} archivos · {d}")
    job.update(60, "Ordenando resultados")
    job.update(60, "Explicando qué es cada cosa")
    files = []
    for s, p in sorted(top, reverse=True):
        ok, why = safety.check_path(p, is_dir=False)
        cat = category_of(p)
        files.append({"path": p, "size": s, "category": cat, "blocked": None if ok else why,
                      "info": explain.explain(p, False, cat)})
    folders = sorted(folder_size.items(), key=lambda kv: kv[1], reverse=True)[:TOP_FOLDERS]
    duplicates = _find_duplicates(job, by_size) if find_dupes else []
    for g in duplicates:
        g["info"] = explain.explain(g["files"][0]["path"], False, g["category"])
    result = {
        "roots": roots, "scanned": scanned, "errors": errors, "total_bytes": total_bytes,
        "seconds": round(time.time() - started, 1),
        "categories": [{"id": c, "name": CATEGORY_NAMES[c], "bytes": v[0], "files": v[1]}
                       for c, v in sorted(by_cat.items(), key=lambda kv: kv[1][0], reverse=True)],
        "top_files": files,
        "top_folders": [{"path": p, "size": s, "info": explain.explain(p, True)} for p, s in folders],
        "duplicates": duplicates,
        "duplicate_waste": sum(g["size"] * (len(g["files"]) - 1) for g in duplicates),
    }
    _last_scan.clear()
    _last_scan.update(result)
    log.info("Análisis de disco: %d archivos, %d bytes, %d grupos duplicados", scanned, total_bytes, len(duplicates))
    return result


def _hash(path, size, partial):
    h = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as f:
        if partial and size > 2 * PARTIAL:
            h.update(f.read(PARTIAL))
            f.seek(-PARTIAL, os.SEEK_END)
            h.update(f.read(PARTIAL))
        else:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
    return h.hexdigest()


def _group(paths, size, partial):
    groups = defaultdict(list)
    for p in paths:
        try:
            groups[_hash(p[0], size, partial)].append(p)
        except OSError:
            continue
    return [g for g in groups.values() if len(g) > 1]


def _find_duplicates(job, by_size):
    candidates = [(s, ps) for s, ps in by_size.items() if len(ps) > 1]
    candidates.sort(key=lambda x: x[0], reverse=True)
    out = []
    for i, (size, paths) in enumerate(candidates):
        if i % 20 == 0:
            job.update(60 + 40 * i / max(1, len(candidates)), f"Buscando duplicados ({i}/{len(candidates)})")
        for g in _group(paths, size, partial=True):
            for full in (_group(g, size, partial=False) if size > 2 * PARTIAL else [g]):
                full.sort(key=lambda p: p[1])  # el más antiguo primero (se conserva por defecto)
                out.append({"size": size, "category": category_of(full[0][0]),
                            "files": [{"path": p, "created": c, "modified": m} for p, c, m in full]})
    out.sort(key=lambda g: g["size"] * (len(g["files"]) - 1), reverse=True)
    return out


def delete(job, paths, permanent=False):
    """Elimina archivos elegidos por el usuario. Por defecto van a la Papelera (recuperables).

    Solo se aceptan rutas que aparecieron en el último análisis.
    """
    allowed = {f["path"] for f in _last_scan.get("top_files", [])}
    allowed |= {f["path"] for g in _last_scan.get("duplicates", []) for f in g["files"]}
    paths = [p for p in paths if p in allowed and os.path.isfile(p)]
    blocked = []
    for p in list(paths):
        ok, why = safety.check_path(p, is_dir=False)
        if not ok:
            blocked.append({"path": p, "reason": why})
            paths.remove(p)
    freed = sum(os.path.getsize(p) for p in paths)
    if permanent:
        failed = [p for p in paths if remove_file(p) is None]
    else:
        for i in range(0, len(paths), 50):
            job.update(i * 100 / max(1, len(paths)), "Moviendo a la Papelera")
            send_to_recycle_bin(paths[i:i + 50])
        failed = [p for p in paths if os.path.exists(p)]
    freed -= sum(os.path.getsize(p) for p in failed if os.path.exists(p))
    log.info("Analizador: %d archivos eliminados (%s), %d fallidos, %d bloqueados por protección",
             len(paths) - len(failed), "permanente" if permanent else "papelera", len(failed), len(blocked))
    done = [p for p in paths if p not in failed]
    if done or blocked:
        how = "borrados para siempre" if permanent else "movidos a la Papelera"
        activity.record("Analizador de disco", f"{len(done)} archivo(s) {how}",
                        done + [f"NO tocado (protegido): {b['path']}" for b in blocked], freed)
    return {"deleted": len(paths) - len(failed), "failed": failed, "freed": freed, "blocked": blocked}
