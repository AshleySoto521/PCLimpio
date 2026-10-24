# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Actualizador de controladores.

- Inventario local de controladores (Win32_PnPSignedDriver) con antigüedad y dispositivos con error.
- Búsqueda de controladores nuevos con el agente de Windows Update que ya trae Windows
  (mismo catálogo que usa el propio Windows; no hay servicios de terceros).
- Antes de instalar: punto de restauración y copia de seguridad de los controladores actuales (pnputil).
"""
import datetime
import os
import time

from . import activity
from .util import BACKUP_DIR, as_list, is_admin, log, run, run_ps

OLD_YEARS = 3


def inventory(job):
    job.update(10, "Leyendo controladores instalados")
    drivers = as_list(run_ps(
        "Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -and $_.DriverVersion } | "
        "ForEach-Object { [pscustomobject]@{ device=$_.DeviceName; cls=$_.DeviceClass; version=$_.DriverVersion; "
        "date=$(if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') }); provider=$_.DriverProviderName; "
        "maker=$_.Manufacturer; inf=$_.InfName; signed=$_.IsSigned; id=$_.DeviceID } }", timeout=180))
    job.update(60, "Buscando dispositivos con problemas")
    problems = as_list(run_ps(
        "Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | ForEach-Object { "
        "[pscustomobject]@{ device=$_.Name; code=$_.ConfigManagerErrorCode; id=$_.DeviceID; cls=$_.PNPClass } }",
        timeout=120))
    limit = datetime.date.today().replace(year=datetime.date.today().year - OLD_YEARS).isoformat()
    for d in drivers:
        prov = (d.get("provider") or "").lower()
        d["old"] = bool(d.get("date")) and d["date"] < limit and "microsoft" not in prov
        d["cls_plain"] = CLASS_PLAIN.get((d.get("cls") or "").upper(), "Otros componentes")
    for pr in problems:
        pr["plain"], pr["fix"] = CODE_PLAIN.get(pr.get("code"), ("Windows indica un problema con este dispositivo.",
                                                                 "Prueba a reiniciar el equipo; si sigue, busca actualizaciones."))
    drivers.sort(key=lambda d: (not d["old"], d.get("cls") or "", d.get("device") or ""))
    return {"drivers": drivers, "problems": problems, "old_years": OLD_YEARS, "admin": is_admin()}


# Tipos de dispositivo en palabras de todos los días
CLASS_PLAIN = {
    "DISPLAY": "Tarjeta gráfica (imagen)", "MONITOR": "Pantallas", "MEDIA": "Sonido",
    "AUDIOENDPOINT": "Altavoces y micrófonos", "NET": "Internet y red", "BLUETOOTH": "Bluetooth",
    "USB": "Puertos USB", "HIDCLASS": "Teclado, ratón y controles", "KEYBOARD": "Teclado", "MOUSE": "Ratón",
    "DISKDRIVE": "Discos", "HDC": "Discos", "SCSIADAPTER": "Discos", "VOLUME": "Discos", "CDROM": "Lector de CD/DVD",
    "PRINTER": "Impresoras", "PRINTQUEUE": "Impresoras", "IMAGE": "Cámaras y escáneres", "CAMERA": "Cámaras",
    "BIOMETRIC": "Huella o reconocimiento facial", "BATTERY": "Batería", "PROCESSOR": "Procesador",
    "SYSTEM": "Partes internas del equipo", "SOFTWARECOMPONENT": "Complementos de controladores",
    "SOFTWAREDEVICE": "Complementos de controladores", "FIRMWARE": "Firmware del equipo",
    "SECURITYDEVICES": "Seguridad del equipo", "SENSOR": "Sensores", "PORTS": "Puertos",
}

# Códigos de error de Windows explicados: (qué pasa, qué hacer)
CODE_PLAIN = {
    1: ("No está bien configurado.", "Busca actualizaciones de controladores aquí arriba."),
    3: ("Su controlador puede estar dañado.", "Busca actualizaciones de controladores; si no hay, reinstálalo desde la web del fabricante."),
    10: ("No pudo arrancar.", "Reinicia el equipo. Si sigue igual, busca una actualización del controlador."),
    12: ("Choca con otro dispositivo.", "Reinicia el equipo; si sigue, desconecta el dispositivo y vuelve a conectarlo."),
    14: ("Necesita que reinicies el equipo.", "Reinicia el equipo."),
    18: ("Hay que volver a instalar su controlador.", "Busca actualizaciones de controladores aquí arriba."),
    22: ("Está desactivado.", "Si lo usas, actívalo desde el Administrador de dispositivos de Windows."),
    24: ("No está conectado o le falta el controlador.", "Revisa que esté bien conectado."),
    28: ("No tiene controlador instalado: puede que no funcione.", "Busca actualizaciones de controladores aquí arriba."),
    31: ("No funciona bien con su controlador actual.", "Busca actualizaciones de controladores aquí arriba."),
    43: ("Windows lo detuvo porque dio un error.", "Desconéctalo y vuelve a conectarlo; si sigue, actualiza su controlador."),
    45: ("No está conectado ahora mismo.", "Es normal si lo desconectaste; no hace falta hacer nada."),
    52: ("Su controlador no tiene una firma válida.", "Instala el controlador oficial desde Windows Update o la web del fabricante."),
}


SEARCH = r"""
$s = New-Object -ComObject Microsoft.Update.Session
$s.ClientApplicationID = 'PCLimpio'
$r = $s.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
foreach ($u in $r.Updates) { [pscustomobject]@{ id=$u.Identity.UpdateID; title=$u.Title; model=$u.DriverModel;
  cls=$u.DriverClass; provider=$u.DriverProvider; date=$(if ($u.DriverVerDate) { $u.DriverVerDate.ToString('yyyy-MM-dd') });
  size=$u.MaxDownloadSize } }
"""


def search_updates(job):
    job.update(10, "Consultando Windows Update (puede tardar varios minutos)")
    updates = as_list(run_ps(SEARCH, timeout=900))
    for u in updates:
        u["cls_plain"] = CLASS_PLAIN.get((u.get("cls") or "").upper(), "Otro componente del equipo")
    return {"updates": updates}


def _restore_point():
    code, out = run(["powershell", "-NoProfile", "-Command",
                     "Checkpoint-Computer -Description 'PCLimpio - antes de actualizar controladores' "
                     "-RestorePointType MODIFY_SETTINGS -ErrorAction Stop"], timeout=300)
    return code == 0, out.strip()


def backup_drivers(job=None):
    folder = os.path.join(BACKUP_DIR, "controladores_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    if job:
        job.update(None, "Copiando controladores actuales")
    code, out = run(["pnputil", "/export-driver", "*", folder], timeout=1800)
    return {"ok": code == 0, "folder": folder, "message": out.strip()[-500:]}


def install_updates(job, update_ids, make_restore_point=True, make_backup=True):
    if not is_admin():
        raise PermissionError("Instalar controladores requiere ejecutar la app como administrador")
    notes = []
    if make_restore_point:
        job.update(5, "Creando punto de restauración")
        ok, msg = _restore_point()
        notes.append("Punto de restauración creado" if ok else f"Sin punto de restauración: {msg[:200]}")
    if make_backup:
        job.update(10, "Respaldando controladores")
        b = backup_drivers(job)
        notes.append(f"Copia de controladores en {b['folder']}" if b["ok"] else "No se pudo respaldar")
    job.update(20, "Descargando e instalando")
    ids = ",".join(f"'{i}'" for i in update_ids if all(c in "0123456789abcdef-" for c in i.lower()))
    script = rf"""
$want = @({ids})
$s = New-Object -ComObject Microsoft.Update.Session
$s.ClientApplicationID = 'PCLimpio'
$r = $s.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
$c = New-Object -ComObject Microsoft.Update.UpdateColl
foreach ($u in $r.Updates) {{ if ($want -contains $u.Identity.UpdateID) {{ [void]$c.Add($u) }} }}
if ($c.Count -eq 0) {{ return [pscustomobject]@{{ installed=0; reboot=$false; results=@() }} }}
$d = $s.CreateUpdateDownloader(); $d.Updates = $c; [void]$d.Download()
$i = $s.CreateUpdateInstaller(); $i.Updates = $c; $res = $i.Install()
$out = for ($k = 0; $k -lt $c.Count; $k++) {{ [pscustomobject]@{{ title=$c.Item($k).Title;
  code=$res.GetUpdateResult($k).ResultCode }} }}
[pscustomobject]@{{ installed=$c.Count; reboot=$res.RebootRequired; results=@($out) }}
"""
    res = run_ps(script, timeout=3600) or {}
    labels = {2: "Instalado", 3: "Instalado con errores", 4: "Falló", 5: "Cancelado"}
    for r in as_list(res.get("results")):
        r["status"] = labels.get(r.get("code"), "Desconocido")
    log.info("Controladores instalados: %s", res)
    activity.record("Actualizador de controladores", f"{len(as_list(res.get('results')))} controlador(es) instalados",
                    [f"{r.get('title')}: {r.get('status')}" for r in as_list(res.get("results"))] + notes)
    return {"results": as_list(res.get("results")), "reboot": res.get("reboot", False), "notes": notes}
