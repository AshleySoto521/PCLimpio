# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Pruebas de la lógica pura y de los módulos sobre carpetas temporales (no tocan el sistema)."""
import os
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import activity, analyzer, cleaning, jobs, recovery, registry_clean, software  # noqa: E402

activity.FILE = os.path.join(tempfile.gettempdir(), "pclimpio_prueba_actividad.jsonl")  # no ensuciar el historial real


class FakeJob:
    cancelled = False

    def update(self, *a, **k):
        pass

    def check(self):
        pass


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


class WingetParser(unittest.TestCase):
    def test_english_table(self):
        out = ("\r   - \r   \\ \rName             Id                        Version      Available   Source\r\n"
               "--------------------------------------------------------------------------\r\n"
               "App Installer    Microsoft.AppInstaller    1.29.379.0   1.29.380    winget\r\n"
               "Terminal Windows Microsoft.WindowsTerminal 1.24.12741.0 1.25.2733.0 winget\r\n"
               "2 upgrades available.\r\n")
        rows = software.parse_winget_table(out)
        self.assertEqual([r["id"] for r in rows], ["Microsoft.AppInstaller", "Microsoft.WindowsTerminal"])
        self.assertEqual(rows[1]["name"], "Terminal Windows")
        self.assertEqual(rows[1]["available"], "1.25.2733.0")

    def test_spanish_headers(self):
        out = ("Nombre   Id              Versión Disponible Origen\n"
               "------------------------------------------------\n"
               "Node.js  OpenJS.NodeJS   26.12.0 26.12.1    winget\n")
        self.assertEqual(software.parse_winget_table(out)[0]["version"], "26.12.0")

    def test_no_updates(self):
        self.assertEqual(software.parse_winget_table("No se encontraron actualizaciones."), [])


class CommandParsing(unittest.TestCase):
    def test_quoted(self):
        self.assertEqual(registry_clean.exe_from_command('"C:\\Program Files\\App\\app.exe" --min'),
                         "C:\\Program Files\\App\\app.exe")

    def test_unquoted_with_spaces(self):
        self.assertEqual(registry_clean.exe_from_command("C:\\Program Files\\App\\app.exe /background"),
                         "C:\\Program Files\\App\\app.exe")

    def test_rundll32_uses_dll(self):
        self.assertEqual(registry_clean.exe_from_command("rundll32.exe C:\\x\\lib.dll,Entry"), "C:\\x\\lib.dll")

    def test_system_commands_ignored(self):
        self.assertEqual(registry_clean.exe_from_command("MsiExec.exe /X{1234}"), "")
        self.assertEqual(registry_clean.exe_from_command("notepad.exe"), "")


class RegistryFix(unittest.TestCase):
    KEY = r"Software\PCLimpioPrueba"

    def tearDown(self):
        import winreg
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.KEY)
        except OSError:
            pass

    def test_fix_backs_up_then_deletes_and_restores(self):
        import shutil
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.KEY) as k:
            winreg.SetValueEx(k, "Roto", 0, winreg.REG_SZ, r"C:\no\existe.exe")
            winreg.SetValueEx(k, "Bueno", 0, winreg.REG_SZ, "x")
        iid = f"{winreg.HKEY_CURRENT_USER}|0|{self.KEY}|Roto|value"
        self.assertEqual(registry_clean.fix(FakeJob(), [iid])["fixed"], 0)  # no salió en un análisis
        registry_clean._last_ids.add(iid)  # como si el análisis la hubiera encontrado
        r = registry_clean.fix(FakeJob(), [iid])
        self.assertEqual(r["fixed"], 1, r)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as k:
            self.assertEqual(winreg.QueryValueEx(k, "Bueno")[0], "x")
            with self.assertRaises(FileNotFoundError):
                winreg.QueryValueEx(k, "Roto")
        self.assertTrue(registry_clean.restore_backup(os.path.basename(r["backup"]))["restored"])
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY) as k:
            self.assertEqual(winreg.QueryValueEx(k, "Roto")[0], r"C:\no\existe.exe")
        shutil.rmtree(r["backup"])


class StartupToggle(unittest.TestCase):
    def test_disable_and_enable_via_startup_approved(self):
        import winreg
        from core import optimizer
        name = "PCLimpioPruebaInicio"
        cid = f"run|{winreg.HKEY_CURRENT_USER}|0|Run|{name}"
        optimizer._last_overview["Prueba"] = [{"id": cid, "type": "inicio", "name": name}]  # como tras analizar
        try:
            optimizer.set_component(cid, False)
            self.assertFalse(optimizer._approved_enabled(winreg.HKEY_CURRENT_USER, "Run", name))
            optimizer.set_component(cid, True)
            self.assertTrue(optimizer._approved_enabled(winreg.HKEY_CURRENT_USER, "Run", name))
        finally:
            optimizer._last_overview.pop("Prueba", None)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, optimizer.APPROVED + r"\Run", 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, name)


class RecycleIndex(unittest.TestCase):
    def test_version2(self):
        name = "C:\\Users\\x\\doc.txt"
        data = struct.pack("<qqqi", 2, 1234, 133000000000000000, len(name) + 1) + (name + "\0").encode("utf-16le")
        info = recovery.parse_index_file(data)
        self.assertEqual(info["original"], name)
        self.assertEqual(info["size"], 1234)
        self.assertTrue(info["deleted"].startswith("2022"))

    def test_version1(self):
        name = "D:\\foto.jpg"
        data = struct.pack("<qqq", 1, 99, 0) + name.encode("utf-16le").ljust(520, b"\0")
        self.assertEqual(recovery.parse_index_file(data)["original"], name)


class NtfsStructures(unittest.TestCase):
    def test_data_runs(self):
        # 0x21: 1 byte de longitud, 2 de desplazamiento; luego un tramo negativo y uno disperso
        runs = recovery.decode_runs(bytes([0x21, 0x10, 0x00, 0x01, 0x11, 0x08, 0xF0, 0x01, 0x04, 0x00]))
        self.assertEqual(runs, [(256, 16), (240, 8), (None, 4)])

    def test_bitmap_count(self):
        bitmap = bytes([0b11110000, 0xFF, 0x00])
        self.assertEqual(recovery.clusters_in_use(bitmap, [(0, 4)]), (0, 4))
        self.assertEqual(recovery.clusters_in_use(bitmap, [(4, 8)]), (8, 8))
        self.assertEqual(recovery.clusters_in_use(bitmap, [(14, 6), (None, 3)]), (2, 6))

    def test_record_with_fixup(self):
        rec = bytearray(1024)
        rec[0:4] = b"FILE"
        struct.pack_into("<HH", rec, 4, 0x30, 3)          # USA en 0x30, 3 entradas (2 bloques de 512)
        struct.pack_into("<H", rec, 0x10, 7)             # secuencia
        struct.pack_into("<H", rec, 0x14, 0x38)          # primer atributo
        struct.pack_into("<H", rec, 0x16, 0)             # no en uso = borrado
        rec[0x30:0x36] = b"\x05\x00\xAA\xBB\xCC\xDD"     # USN=5 y bytes originales
        pos = 0x38
        name = "borrado.txt"
        fn = bytearray(0x42 + len(name) * 2)
        struct.pack_into("<Q", fn, 0, (3 << 48) | 1234)
        fn[0x40] = len(name)
        fn[0x41] = 1
        fn[0x42:] = name.encode("utf-16le")
        attr = bytearray(0x18) + fn
        attr += b"\0" * (-len(attr) % 8)
        struct.pack_into("<IIBB", attr, 0, 0x30, len(attr), 0, 0)
        struct.pack_into("<IH", attr, 0x10, len(fn), 0x18)
        rec[pos:pos + len(attr)] = attr
        pos += len(attr)
        content = b"hola mundo"
        data = bytearray(0x18) + content
        data += b"\0" * (-len(data) % 8)
        struct.pack_into("<IIBB", data, 0, 0x80, len(data), 0, 0)
        struct.pack_into("<IH", data, 0x10, len(content), 0x18)
        rec[pos:pos + len(data)] = data
        pos += len(data)
        struct.pack_into("<I", rec, pos, 0xFFFFFFFF)
        rec[510:512] = b"\x05\x00"
        rec[1022:1024] = b"\x05\x00"
        fixed = recovery.apply_fixup(bytes(rec))
        self.assertEqual(fixed[510:512], b"\xAA\xBB")
        self.assertEqual(fixed[1022:1024], b"\xCC\xDD")
        info = recovery.parse_record(fixed)
        self.assertFalse(info["in_use"])
        self.assertEqual(info["name"], name)
        self.assertEqual(info["parent"], 1234)
        self.assertEqual(info["resident"], content)

    def test_bad_fixup_rejected(self):
        rec = bytearray(1024)
        struct.pack_into("<HH", rec, 4, 0x30, 3)
        rec[0x30:0x32] = b"\x05\x00"
        rec[510:512] = b"\x09\x09"
        self.assertIsNone(recovery.apply_fixup(bytes(rec)))


class CleaningRules(unittest.TestCase):
    def test_iter_files_age_and_pattern(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "a.tmp"), b"x" * 10)
            write(os.path.join(d, "sub", "b.log"), b"y" * 20)
            write(os.path.join(d, "nuevo.tmp"), b"z")
            old = time.time() - 3 * 86400
            for p in ("a.tmp", os.path.join("sub", "b.log")):
                os.utime(os.path.join(d, p), (old, old))
            t = cleaning.T(d, min_age_h=24)
            self.assertEqual(sorted(os.path.basename(p) for p, _ in cleaning.iter_files(t)), ["a.tmp", "b.log"])
            t = cleaning.T(d, ("*.log",))
            self.assertEqual([s for _, s in cleaning.iter_files(t)], [20])
            t = cleaning.T(d, recursive=False)
            self.assertEqual(len(list(cleaning.iter_files(t))), 2)

    def test_clean_deletes_and_skips_locked(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "x", "a.tmp"), b"a" * 100)
            write(os.path.join(d, "b.tmp"), b"b" * 50)
            locked = open(os.path.join(d, "b.tmp"), "rb")  # abierto: Windows no deja borrarlo
            rule = dict(id="t", name="prueba", group="g", level="basica", default=True, desc="",
                        targets=[cleaning.T(d)])
            original = cleaning.all_rules
            cleaning.all_rules = lambda: [rule]
            try:
                a = cleaning.analyze(FakeJob(), ["t"])
                self.assertEqual((a["rules"][0]["files"], a["total_bytes"]), (2, 150))
                r = cleaning.clean(FakeJob(), ["t"])
            finally:
                cleaning.all_rules = original
                locked.close()
            self.assertEqual(r["total_freed"], 100)
            self.assertEqual(r["rules"][0]["failed"], 1)
            self.assertFalse(os.path.exists(os.path.join(d, "x")))  # carpeta vacía eliminada
            self.assertTrue(os.path.exists(os.path.join(d, "b.tmp")))

    def test_all_rules_well_formed(self):
        for r in cleaning._static_rules():
            self.assertIn(r["level"], ("basica", "avanzada"))
            self.assertTrue(r.get("special") or r["targets"], r["id"])


HERE = os.path.expanduser("~")  # fuera de AppData (ahí no se buscan duplicados); se borra al terminar


class Analyzer(unittest.TestCase):
    def test_protected_folders(self):
        self.assertTrue(analyzer.protected(os.path.expandvars(r"%WINDIR%\System32\x.dll")))
        self.assertTrue(analyzer.protected(os.path.expandvars(r"%APPDATA%\App\config.bin")))
        self.assertFalse(analyzer.protected(os.path.expandvars(r"%LOCALAPPDATA%\Temp\a.bin")))  # zona de limpieza
        self.assertFalse(analyzer.protected(r"D:\Fotos\a.jpg"))

    def test_scan_categories_and_duplicates(self):
        with tempfile.TemporaryDirectory(dir=HERE) as d:
            big = os.urandom(300 * 1024)
            write(os.path.join(d, "fotos", "a.jpg"), big)
            write(os.path.join(d, "copia", "a (1).jpg"), big)
            write(os.path.join(d, "otro.jpg"), big[:-1] + bytes([big[-1] ^ 1]))  # mismo tamaño, otro contenido
            write(os.path.join(d, "video.mp4"), b"v" * 500 * 1024)
            write(os.path.join(d, "nota.txt"), b"hola")
            res = analyzer.scan(FakeJob(), [d], {"min_size": 1024, "duplicates": True})
            self.assertEqual(res["scanned"], 5)
            cats = {c["id"]: c["bytes"] for c in res["categories"]}
            self.assertEqual(cats["picture"], 3 * 300 * 1024)
            self.assertEqual(cats["video"], 500 * 1024)
            self.assertEqual(res["top_files"][0]["path"], os.path.join(d, "video.mp4"))
            self.assertEqual(len(res["duplicates"]), 1)
            names = sorted(os.path.basename(f["path"]) for f in res["duplicates"][0]["files"])
            self.assertEqual(names, ["a (1).jpg", "a.jpg"])
            self.assertEqual(res["duplicate_waste"], 300 * 1024)
            folders = {os.path.basename(f["path"]): f["size"] for f in res["top_folders"]}
            self.assertEqual(folders["fotos"], 300 * 1024)

    def test_delete_only_scanned_paths(self):
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "grande.bin"), b"x" * 4096)
            write(os.path.join(d, "fuera.bin"), b"y")
            analyzer.scan(FakeJob(), [d], {"min_size": 2048, "duplicates": False})
            r = analyzer.delete(FakeJob(), [os.path.join(d, "fuera.bin"), os.path.join(d, "grande.bin")],
                                permanent=True)
            self.assertEqual(r["deleted"], 1)
            self.assertTrue(os.path.exists(os.path.join(d, "fuera.bin")))
            self.assertFalse(os.path.exists(os.path.join(d, "grande.bin")))


class Jobs(unittest.TestCase):
    def test_job_lifecycle_and_cancel(self):
        j = jobs.start("t", lambda job: 42)
        for _ in range(50):
            if j.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual((j.status, j.result), ("done", 42))

        def slow(job):
            while True:
                job.update(1, "x")
                time.sleep(0.01)
        j = jobs.start("slow", slow)
        j.cancel()
        for _ in range(100):
            if j.status != "running":
                break
            time.sleep(0.02)
        self.assertEqual(j.status, "cancelled")


if __name__ == "__main__":
    unittest.main(verbosity=2)
