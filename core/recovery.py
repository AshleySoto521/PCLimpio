# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Recuperación de archivos.

1. Papelera de reciclaje: lee los índices $I de cada unidad y restaura el $R a su ruta original.
2. Escaneo profundo NTFS (requiere administrador): lee la tabla $MFT del volumen en bruto y lista los
   registros de archivo marcados como no usados (archivos borrados). Con el mapa de clústeres ($Bitmap)
   se estima si sus datos siguen intactos o ya fueron sobrescritos, como hacen las herramientas tipo Recuva.
   La recuperación copia los clústeres a OTRA unidad para no sobrescribir lo que se quiere salvar.
"""
import datetime
import os
import shutil
import struct

from . import activity, safety
from .analyzer import category_of
from .util import is_admin, log, run

# ---------------------------------------------------------------- Papelera


def _user_sid():
    _, out = run(["whoami", "/user", "/fo", "csv", "/nh"], timeout=15)
    parts = out.strip().split('","')
    return parts[-1].strip('"\r\n ') if parts else ""


def filetime_to_iso(ft):
    if not ft:
        return ""
    try:
        dt = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=ft // 10)
        return dt.replace(tzinfo=datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    except (OverflowError, ValueError):
        return ""


def parse_index_file(data):
    """Interpreta un archivo $I de la Papelera (Vista/7 = versión 1, Windows 10+ = versión 2)."""
    version, size, ft = struct.unpack_from("<qqq", data, 0)
    if version == 1:
        name = data[24:24 + 520].decode("utf-16le", "replace").split("\0")[0]
    elif version == 2:
        n = struct.unpack_from("<i", data, 24)[0]
        name = data[28:28 + n * 2].decode("utf-16le", "replace").rstrip("\0")
    else:
        raise ValueError(f"Versión de $I desconocida: {version}")
    return {"original": name, "size": size, "deleted": filetime_to_iso(ft)}


def recycle_bin_items():
    sid = _user_sid()
    items = []
    from .util import list_drives
    for d in list_drives():
        folder = os.path.join(d["root"], "$Recycle.Bin", sid)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            if not n.startswith("$I"):
                continue
            ipath = os.path.join(folder, n)
            rpath = os.path.join(folder, "$R" + n[2:])
            try:
                with open(ipath, "rb") as f:
                    info = parse_index_file(f.read())
            except (OSError, ValueError, struct.error):
                continue
            if not os.path.exists(rpath):
                continue
            info.update({"id": ipath, "is_dir": os.path.isdir(rpath), "name": os.path.basename(info["original"]),
                         "category": category_of(info["original"])})
            items.append(info)
    items.sort(key=lambda i: i["deleted"], reverse=True)
    return {"items": items}


def _free_name(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base} (recuperado {n}){ext}"):
        n += 1
    return f"{base} (recuperado {n}){ext}"


def restore_from_bin(index_paths):
    done, errors = [], []
    for ipath in index_paths:
        if "$recycle.bin" not in ipath.lower() or not os.path.basename(ipath).startswith("$I"):
            errors.append({"id": ipath, "error": "Ruta inválida"})
            continue
        rpath = os.path.join(os.path.dirname(ipath), "$R" + os.path.basename(ipath)[2:])
        try:
            with open(ipath, "rb") as f:
                dest = _free_name(parse_index_file(f.read())["original"])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(rpath, dest)
            os.remove(ipath)
            done.append(dest)
        except (OSError, ValueError) as e:
            errors.append({"id": ipath, "error": str(e)})
    log.info("Restaurados de la Papelera: %d, errores: %d", len(done), len(errors))
    if done:
        activity.record("Recuperación de archivos", f"{len(done)} elemento(s) restaurados de la Papelera", done)
    return {"restored": done, "errors": errors}


# ---------------------------------------------------------------- NTFS en bruto

def decode_runs(b):
    """Decodifica la lista de 'data runs' de un atributo no residente → [(lcn | None, nº clústeres)]."""
    runs, pos, lcn = [], 0, 0
    while pos < len(b) and b[pos] != 0:
        h = b[pos]
        ln, of = h & 0xF, h >> 4
        pos += 1
        length = int.from_bytes(b[pos:pos + ln], "little")
        pos += ln
        if of == 0:
            runs.append((None, length))  # tramo disperso (ceros)
        else:
            lcn += int.from_bytes(b[pos:pos + of], "little", signed=True)
            pos += of
            runs.append((lcn, length))
    return runs


def apply_fixup(rec):
    """Restaura los dos últimos bytes de cada bloque (Update Sequence Array). Devuelve None si el registro está dañado."""
    usa_ofs, usa_count = struct.unpack_from("<HH", rec, 4)
    if usa_count < 2:
        return rec
    stride = len(rec) // (usa_count - 1)
    usn = rec[usa_ofs:usa_ofs + 2]
    rec = bytearray(rec)
    for i in range(1, usa_count):
        pos = i * stride - 2
        if rec[pos:pos + 2] != usn:
            return None
        rec[pos:pos + 2] = rec[usa_ofs + 2 * i:usa_ofs + 2 * i + 2]
    return bytes(rec)


def parse_record(rec):
    """Extrae nombre, padre, fechas y $DATA de un registro MFT ya corregido."""
    flags = struct.unpack_from("<H", rec, 0x16)[0]
    base_ref = struct.unpack_from("<Q", rec, 0x20)[0]
    seq = struct.unpack_from("<H", rec, 0x10)[0]
    out = {"in_use": bool(flags & 1), "is_dir": bool(flags & 2), "extension": base_ref != 0, "seq": seq,
           "name": None, "parent": None, "parent_seq": None, "ns": 9, "created": 0, "modified": 0,
           "size": 0, "resident": None, "runs": None, "attr_list": False}
    pos = struct.unpack_from("<H", rec, 0x14)[0]
    while pos + 16 <= len(rec):
        atype, alen = struct.unpack_from("<II", rec, pos)
        if atype == 0xFFFFFFFF or alen == 0 or pos + alen > len(rec):
            break
        nonres = rec[pos + 8]
        name_len = rec[pos + 9]
        if atype == 0x10 and not nonres:
            off = struct.unpack_from("<H", rec, pos + 0x14)[0]
            out["created"], out["modified"] = struct.unpack_from("<QQ", rec, pos + off)
        elif atype == 0x20:
            out["attr_list"] = True
        elif atype == 0x30 and not nonres:
            off = pos + struct.unpack_from("<H", rec, pos + 0x14)[0]
            parent_ref = struct.unpack_from("<Q", rec, off)[0]
            ns = rec[off + 0x41]
            nlen = rec[off + 0x40]
            if ns != 2 and (out["name"] is None or out["ns"] == 2 or ns < out["ns"]):  # evitar nombres 8.3
                out["name"] = rec[off + 0x42:off + 0x42 + nlen * 2].decode("utf-16le", "replace")
                out["parent"] = parent_ref & 0xFFFFFFFFFFFF
                out["parent_seq"] = parent_ref >> 48
                out["ns"] = ns
            elif out["name"] is None:
                out["name"] = rec[off + 0x42:off + 0x42 + nlen * 2].decode("utf-16le", "replace")
                out["parent"] = parent_ref & 0xFFFFFFFFFFFF
                out["parent_seq"] = parent_ref >> 48
                out["ns"] = ns
        elif atype == 0x80 and name_len == 0:
            if nonres:
                start_vcn = struct.unpack_from("<Q", rec, pos + 0x10)[0]
                if start_vcn == 0:
                    roff = struct.unpack_from("<H", rec, pos + 0x20)[0]
                    out["size"] = struct.unpack_from("<Q", rec, pos + 0x30)[0]
                    out["runs"] = decode_runs(rec[pos + roff:pos + alen])
            else:
                clen = struct.unpack_from("<I", rec, pos + 0x10)[0]
                coff = struct.unpack_from("<H", rec, pos + 0x14)[0]
                out["resident"] = rec[pos + coff:pos + coff + clen]
                out["size"] = clen
        pos += alen
    return out


def clusters_in_use(bitmap, runs):
    """Cuenta cuántos clústeres de los tramos están marcados como ocupados en $Bitmap → (ocupados, total)."""
    used = total = 0
    for lcn, length in runs or []:
        if lcn is None or length <= 0:
            continue
        total += length
        first, end = lcn >> 3, (lcn + length + 7) >> 3
        bits = int.from_bytes(bitmap[first:end], "little") >> (lcn & 7)
        used += (bits & ((1 << length) - 1)).bit_count()
    return used, total


class NtfsVolume:
    def __init__(self, letter):
        self.letter = letter.upper()[0]
        self.fd = os.open(rf"\\.\{self.letter}:", os.O_RDONLY | getattr(os, "O_BINARY", 0))
        self.sector = 512
        boot = self.read(0, 512)
        if boot[3:11] != b"NTFS    ":
            self.close()
            raise ValueError(f"La unidad {self.letter}: no es NTFS")
        self.sector = struct.unpack_from("<H", boot, 0x0B)[0]
        self.cluster = self.sector * boot[0x0D]
        self.total_clusters = struct.unpack_from("<Q", boot, 0x28)[0] // boot[0x0D]
        mft_lcn = struct.unpack_from("<Q", boot, 0x30)[0]
        cpr = struct.unpack_from("<b", boot, 0x40)[0]
        self.rec_size = cpr * self.cluster if cpr > 0 else 2 ** (-cpr)
        rec0 = parse_record(apply_fixup(self.read(mft_lcn * self.cluster, self.rec_size)))
        self.mft_runs = rec0["runs"]
        self.mft_size = rec0["size"]
        self.bitmap = None

    def read(self, offset, size):
        start = offset - offset % self.sector
        end = offset + size
        end += (-end) % self.sector
        os.lseek(self.fd, start, os.SEEK_SET)
        chunks, remaining = [], end - start
        while remaining > 0:
            data = os.read(self.fd, min(remaining, 4 * 1024 * 1024))
            if not data:
                break
            chunks.append(data)
            remaining -= len(data)
        buf = b"".join(chunks)
        return buf[offset - start:offset - start + size]

    def read_runs(self, runs, size, out=None):
        """Lee (o escribe en el archivo out) los clústeres de una lista de tramos, truncando a size."""
        left, parts = size, []
        for lcn, length in runs:
            if left <= 0:
                break
            nbytes = min(length * self.cluster, left)
            done = 0
            while done < nbytes:
                step = min(nbytes - done, 4 * 1024 * 1024)
                data = b"\0" * step if lcn is None else self.read(lcn * self.cluster + done, step)
                if out:
                    out.write(data)
                else:
                    parts.append(data)
                done += step
            left -= nbytes
        return None if out else b"".join(parts)

    def records(self):
        """Itera (número_de_registro, bytes) por toda la $MFT siguiendo sus tramos."""
        recno = 0
        per_chunk = max(1, (4 * 1024 * 1024) // self.rec_size)
        total = self.mft_size // self.rec_size
        for lcn, length in self.mft_runs:
            if lcn is None:
                recno += length * self.cluster // self.rec_size
                continue
            run_bytes = length * self.cluster
            done = 0
            while done < run_bytes and recno < total:
                step = min(run_bytes - done, per_chunk * self.rec_size)
                data = self.read(lcn * self.cluster + done, step)
                for i in range(0, len(data), self.rec_size):
                    yield recno, data[i:i + self.rec_size]
                    recno += 1
                done += step

    def load_bitmap(self):
        rec = parse_record(apply_fixup(self._record_raw(6)))
        self.bitmap = self.read_runs(rec["runs"], rec["size"]) if rec["runs"] else rec["resident"]

    def _record_raw(self, n):
        target = n * self.rec_size
        vcn_bytes = 0
        for lcn, length in self.mft_runs:
            run_bytes = length * self.cluster
            if target < vcn_bytes + run_bytes:
                return self.read(lcn * self.cluster + (target - vcn_bytes), self.rec_size)
            vcn_bytes += run_bytes
        raise ValueError("Registro fuera de la MFT")

    def clusters_in_use(self, runs):
        return clusters_in_use(self.bitmap, runs)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


_deep = {"drive": None, "files": []}


def _state(vol, info):
    if info["resident"] is not None:
        return "excelente"
    if not info["runs"]:
        return "vacío" if info["size"] == 0 else "irrecuperable"
    if sum(n for _, n in info["runs"]) > 2_000_000:  # >8 GB con clúster de 4 KB: estimación rápida
        return "desconocido"
    used, total = vol.clusters_in_use(info["runs"])
    if total == 0 or used == 0:
        return "excelente"
    return "sobrescrito" if used == total else "parcial"


def deep_scan(job, letter):
    if not is_admin():
        raise PermissionError("El escaneo profundo necesita ejecutar la app como administrador")
    vol = NtfsVolume(letter)
    try:
        job.update(2, "Leyendo mapa de clústeres ($Bitmap)")
        vol.load_bitmap()
        total = vol.mft_size // vol.rec_size
        names = {}       # registro de carpeta -> (nombre, padre) para reconstruir rutas
        deleted = []
        for recno, raw in vol.records():
            if recno % 20000 == 0:
                job.update(5 + 85 * recno / max(1, total), f"Registro {recno:,} de {total:,} · {len(deleted)} borrados")
            if raw[:4] != b"FILE":
                continue
            flags = raw[0x16]
            in_use, is_dir = flags & 1, flags & 2
            if in_use and not is_dir:
                continue  # archivos vivos: no hace falta analizarlos
            rec = apply_fixup(raw)
            if rec is None:
                continue
            info = parse_record(rec)
            if info["extension"] or info["name"] is None:
                continue
            if is_dir:
                names[recno] = (info["name"], info["parent"])
                continue
            info["recno"] = recno
            deleted.append(info)
        job.update(90, "Reconstruyendo rutas y evaluando estado")

        def path_of(recno):
            parts, cur, guard = [], recno, 0
            while cur != 5 and guard < 64:  # 5 = carpeta raíz del volumen
                entry = names.get(cur)
                if not entry:
                    parts.append("[carpeta desconocida]")
                    break
                parts.append(entry[0])
                cur = entry[1]
                guard += 1
            return f"{vol.letter}:\\" + "\\".join(reversed(parts))

        files = []
        for info in deleted:
            folder = path_of(info["parent"])
            files.append({"id": info["recno"], "name": info["name"], "folder": folder, "size": info["size"],
                          "modified": filetime_to_iso(info["modified"]), "created": filetime_to_iso(info["created"]),
                          "state": _state(vol, info), "category": category_of(info["name"]),
                          "runs": info["runs"], "resident": info["resident"].hex() if info["resident"] else None,
                          "fragmented": info["attr_list"]})
        files.sort(key=lambda f: f["modified"], reverse=True)
        _deep.update({"drive": vol.letter, "files": files, "cluster": vol.cluster})
        log.info("Escaneo profundo %s: %d archivos borrados", vol.letter, len(files))
        counts = {}
        for f in files:
            counts[f["state"]] = counts.get(f["state"], 0) + 1
        return {"drive": vol.letter, "total": len(files), "states": counts}
    finally:
        vol.close()


def deep_results(text="", category="", state="", limit=1000, min_size=0):
    text = text.lower()
    out = []
    for f in _deep["files"]:
        if text and text not in f["name"].lower() and text not in f["folder"].lower():
            continue
        if category and f["category"] != category:
            continue
        if state and f["state"] != state:
            continue
        if f["size"] < min_size:
            continue
        out.append({k: v for k, v in f.items() if k not in ("runs", "resident")})
        if len(out) >= limit:
            break
    return {"drive": _deep["drive"], "files": out, "total": len(_deep["files"])}


def recover(job, ids, dest):
    drive = _deep["drive"]
    if not drive:
        raise ValueError("Primero ejecuta un escaneo profundo")
    dest = os.path.abspath(dest)
    if dest[0].upper() == drive:
        raise ValueError("Guarda los archivos recuperados en OTRA unidad para no sobrescribir los datos borrados")
    ok, why = safety.check_path(os.path.join(dest, "recuperado.tmp"), is_dir=False)
    if not ok:
        raise safety.Blocked(f"No se guardan archivos recuperados en {dest}: {why}")
    os.makedirs(dest, exist_ok=True)
    by_id = {f["id"]: f for f in _deep["files"]}
    vol = NtfsVolume(drive)
    done, errors = [], []
    try:
        for i, rid in enumerate(ids):
            f = by_id.get(int(rid))
            if not f:
                continue
            job.update(i * 100 / max(1, len(ids)), f"Recuperando {f['name']}")
            target = _free_name(os.path.join(dest, f["name"]))
            try:
                with open(target, "wb") as out:
                    if f["resident"] is not None:
                        out.write(bytes.fromhex(f["resident"]))
                    elif f["runs"]:
                        vol.read_runs(f["runs"], f["size"], out)
                done.append({"name": f["name"], "path": target, "state": f["state"]})
            except OSError as e:
                errors.append({"name": f["name"], "error": str(e)})
    finally:
        vol.close()
    log.info("Recuperados %d archivos en %s", len(done), dest)
    if done:
        activity.record("Recuperación de archivos", f"{len(done)} archivo(s) recuperados en {dest}",
                        [d["path"] for d in done])
    return {"recovered": done, "errors": errors, "dest": dest}
