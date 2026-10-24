# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Pruebas de la protección del sistema: nada de Windows ni de programas se puede borrar o desactivar,
ni siquiera por las reglas internas de la app, y siempre se explica el motivo."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import activity, analyzer, cleaning, explain, optimizer, safety, software, util  # noqa: E402

activity.FILE = os.path.join(tempfile.gettempdir(), "pclimpio_prueba_actividad.jsonl")  # no ensuciar el historial real

WIN = os.environ.get("WINDIR", r"C:\Windows")
SYS32 = os.path.join(WIN, "System32")


class FakeJob:
    def update(self, *a, **k):
        pass

    def check(self):
        pass


def blocked(path, is_dir=None):
    return not safety.check_path(path, is_dir)[0]


class Paths(unittest.TestCase):
    def test_system32_and_core_blocked_with_reason(self):
        ok, why = safety.check_path(SYS32, is_dir=True)
        self.assertFalse(ok)
        self.assertIn("Windows deja de arrancar", why)
        for p in (os.path.join(SYS32, "ntoskrnl.exe"), os.path.join(SYS32, "drivers", "etc", "hosts"),
                  os.path.join(WIN, "SysWOW64", "kernel32.dll"), os.path.join(WIN, "WinSxS", "x"),
                  os.path.join(WIN, "explorer.exe"), r"C:\pagefile.sys", r"C:\Boot\BCD"):
            self.assertTrue(blocked(p), p)

    def test_tricky_spellings(self):
        self.assertTrue(blocked(os.path.join(WIN, "Temp", "..", "System32", "ntoskrnl.exe")))
        self.assertTrue(blocked(SYS32.upper() + "\\KERNEL32.DLL"))
        self.assertTrue(blocked("\\\\?\\" + os.path.join(SYS32, "kernel32.dll")))
        self.assertTrue(blocked(r"%WINDIR%\System32\kernel32.dll"))
        self.assertTrue(blocked(r"C:\PROGRA~1\Common Files\x.dll"))  # nombre corto 8.3 de Program Files

    def test_junction_to_system32_is_blocked(self):
        base = tempfile.mkdtemp(dir=os.path.expanduser("~"))
        link = os.path.join(base, "atajo")
        try:
            subprocess.run(["cmd", "/c", "mklink", "/J", link, SYS32], capture_output=True, check=True)
            self.assertTrue(blocked(os.path.join(link, "kernel32.dll"), is_dir=False))
        finally:
            subprocess.run(["cmd", "/c", "rmdir", link], capture_output=True)
            shutil.rmtree(base, ignore_errors=True)

    def test_roots_and_personal_folders_as_folders(self):
        for p in ("C:\\", "D:\\", WIN, os.environ["ProgramFiles"], os.path.expanduser("~"),
                  os.path.join(os.path.expanduser("~"), "Documents")):
            self.assertTrue(blocked(p, is_dir=True), p)

    def test_programs_and_appdata_protected_but_cleanup_zones_allowed(self):
        ok, why = safety.check_path(os.path.join(os.environ["ProgramFiles"], "Juego", "datos.pak"), False)
        self.assertFalse(ok)
        self.assertIn("Desinstalador", why)
        self.assertTrue(blocked(os.path.join(os.environ["APPDATA"], "Code", "User", "settings.json"), False))
        self.assertFalse(blocked(os.path.join(WIN, "Temp", "x.tmp"), False))
        self.assertFalse(blocked(os.path.join(os.environ["TEMP"], "x.tmp"), False))
        self.assertTrue(blocked(os.path.join(WIN, "Temp"), True))  # la carpeta de la zona en sí no

    def test_user_files_allowed(self):
        self.assertFalse(blocked(os.path.join(os.path.expanduser("~"), "Downloads", "a.zip"), False))
        self.assertFalse(blocked(r"D:\Fotos\a.jpg", False))

    def test_internal_rule_cannot_open_system32(self):
        self.assertFalse(safety.allow_cleanup_zone(os.path.join(SYS32, "drivers")))
        self.assertTrue(blocked(os.path.join(SYS32, "drivers", "x.sys"), False))


class LowLevelDeletes(unittest.TestCase):
    """El bloqueo es de la app, no del sistema de permisos: aplica aunque el archivo SÍ se pudiera borrar."""

    def setUp(self):
        self.dir = os.path.join(os.environ["APPDATA"], "PCLimpioPruebaProtegida")
        os.makedirs(self.dir, exist_ok=True)
        self.file = os.path.join(self.dir, "config.json")
        with open(self.file, "w") as f:
            f.write("{}")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_remove_file_refuses_even_if_os_would_allow(self):
        with self.assertRaises(safety.Blocked) as ctx:
            util.remove_file(self.file)
        self.assertIn("configuración", str(ctx.exception))
        self.assertTrue(os.path.exists(self.file))

    def test_recycle_bin_refuses(self):
        with self.assertRaises(safety.Blocked):
            util.send_to_recycle_bin([self.file])
        self.assertTrue(os.path.exists(self.file))

    def test_remove_file_system32(self):
        with self.assertRaises(safety.Blocked) as ctx:
            util.remove_file(os.path.join(SYS32, "drivers", "etc", "hosts"))
        self.assertIn("System32", str(ctx.exception))

    def test_cleaning_rule_pointing_to_system32_deletes_nothing(self):
        rule = dict(id="mala", name="regla mal escrita", group="g", level="basica", default=True, desc="",
                    targets=[cleaning.T(os.path.join(SYS32, "drivers", "etc"), ("hosts",), recursive=False)])
        original = cleaning.all_rules
        cleaning.all_rules = lambda: [rule]
        try:
            r = cleaning.clean(FakeJob(), ["mala"])
        finally:
            cleaning.all_rules = original
        self.assertEqual(r["total_freed"], 0)
        self.assertIn("protegidos", r["rules"][0]["note"])
        self.assertTrue(os.path.exists(os.path.join(SYS32, "drivers", "etc", "hosts")))

    def test_analyzer_reports_blocked_with_reason(self):
        analyzer._last_scan.clear()
        analyzer._last_scan["top_files"] = [{"path": self.file}]
        r = analyzer.delete(FakeJob(), [self.file], permanent=True)
        self.assertEqual(r["deleted"], 0)
        self.assertEqual(r["blocked"][0]["path"], self.file)
        self.assertTrue(r["blocked"][0]["reason"])
        self.assertTrue(os.path.exists(self.file))


class ProgramsProcessesServices(unittest.TestCase):
    def test_programs(self):
        for name in ("Microsoft Edge WebView2 Runtime", "Microsoft Visual C++ 2015-2022 Redistributable (x64)",
                     "Microsoft .NET Desktop Runtime - 8.0.11", "NVIDIA Graphics Driver 581.57",
                     "Realtek Audio Driver", "AMD Chipset Software", "Microsoft Edge"):
            ok, why = safety.check_program(name)
            self.assertFalse(ok, name)
            self.assertTrue(why)
        self.assertTrue(safety.check_program("Obsidian")[0])
        self.assertTrue(safety.check_program("Los Sims 4", "Electronic Arts", r"C:\Program Files\EA Games")[0])

    def test_uninstall_blocked_before_running_anything(self):
        with self.assertRaises(safety.Blocked):
            software.uninstall("appx|Microsoft.WindowsAppRuntime.1.6_6000.1.0_x64__8wekyb3d8bbwe")

    def test_processes(self):
        for p in ("csrss", "lsass.exe", "winlogon", "svchost", "explorer", "MsMpEng"):
            self.assertFalse(safety.check_process(p)[0], p)
        with self.assertRaises(safety.Blocked):
            optimizer.end_process("csrss")
        self.assertTrue(safety.check_process("chrome")[0])

    def test_security_and_windows_components(self):
        self.assertFalse(safety.check_component({"type": "inicio", "name": "SecurityHealth"})[0])
        self.assertFalse(safety.check_component({"type": "servicio", "name": "Bitdefender App Service",
                                                 "company": "Bitdefender"})[0])
        self.assertFalse(safety.check_component({"type": "servicio", "name": "x", "company": "Microsoft Corporation"})[0])
        self.assertTrue(safety.check_component({"type": "inicio", "name": "Steam", "company": "Valve"})[0])
        self.assertTrue(safety.check_component({"type": "inicio", "name": "AMD Crash Defender", "company": "AMD"})[0])

    def test_disabling_protected_component_raises(self):
        optimizer._last_overview.clear()
        optimizer._last_overview["Seguridad"] = [{"id": "service|WinDefend", "type": "servicio",
                                                  "name": "Microsoft Defender Antivirus", "company": "Microsoft"}]
        with self.assertRaises(safety.Blocked):
            optimizer.set_component("service|WinDefend", False)
        optimizer._last_overview.clear()


class Explanations(unittest.TestCase):
    """Lo que ve un usuario sin conocimientos técnicos: qué es y si se puede borrar."""

    def ex(self, path, is_dir=False, cat="other"):
        return explain.explain(os.path.expandvars(path), is_dir, cat)

    def test_example_from_user_delivery_optimization(self):
        e = self.ex(r"%WINDIR%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization"
                    r"\Cache\7b4dd9a6-884a-4393-868b-e9950521e253\content.bin")
        self.assertEqual(e["title"], "Copias de actualizaciones para compartir")
        self.assertEqual(e["verdict"], "limpiar")
        self.assertEqual(e["page"], "advanced")
        self.assertNotIn("\\", e["what"] + e["advice"])  # sin rutas técnicas en la explicación

    def test_system_and_programs_say_no_with_reason(self):
        self.assertEqual(self.ex(r"%WINDIR%\System32\kernel32.dll")["verdict"], "no")
        e = self.ex(r"%ProgramFiles%\MiJuego\datos.pak")
        self.assertEqual(e["verdict"], "no")
        self.assertIn("desinstálalo", e["advice"])

    def test_edge_is_never_suggested_for_uninstall(self):
        e = self.ex(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.dll")
        self.assertNotIn("desinstálalo", e["advice"])

    def test_personal_files(self):
        dl = os.path.join(os.path.expanduser("~"), "Downloads")
        self.assertEqual(explain.explain(os.path.join(dl, "setup.exe"), False, "application")["verdict"], "borrar")
        self.assertEqual(explain.explain(os.path.join(dl, "fotos.zip"), False, "archive")["verdict"], "revisar")
        pic = os.path.join(os.path.expanduser("~"), "Pictures", "boda.jpg")
        e = explain.explain(pic, False, "picture")
        self.assertEqual((e["title"], e["verdict"]), ("Imagen tuya", "tuyo"))

    def test_caches_and_temp_are_safe(self):
        self.assertEqual(self.ex(r"%TEMP%\abc.tmp")["verdict"], "limpiar")
        e = self.ex(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Cache\Cache_Data\data_1")
        self.assertIn(e["verdict"], ("limpiar", "borrar"))
        self.assertNotIn("Google Google", e["title"])

    def test_every_verdict_has_label_and_advice(self):
        for path in (r"%WINDIR%\Temp\x", r"C:\pagefile.sys", r"%APPDATA%\Discord\settings.json", r"D:\Videos\v.mp4"):
            e = self.ex(path)
            self.assertTrue(e["title"] and e["what"] and e["advice"] and e["verdict_label"], path)


class ActivityLog(unittest.TestCase):
    def test_record_and_read_newest_first(self):
        if os.path.exists(activity.FILE):
            os.remove(activity.FILE)
        activity.record("Prueba", "primero")
        activity.record("Prueba", "segundo", ["a", "b"], 10)
        entries = activity.read()
        self.assertEqual([e["summary"] for e in entries], ["segundo", "primero"])
        self.assertEqual(entries[0]["details"], ["a", "b"])
        self.assertEqual(entries[0]["freed"], 10)

    def test_blocked_attempt_is_logged_as_not_touched(self):
        target = os.path.join(SYS32, "drivers", "etc", "hosts")
        analyzer._last_scan.clear()
        analyzer._last_scan["top_files"] = [{"path": target}]
        analyzer.delete(FakeJob(), [target], permanent=True)
        last = activity.read(1)[0]
        self.assertIn("NO tocado (protegido)", last["details"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
