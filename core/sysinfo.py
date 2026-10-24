# Copyright (C) 2026 ashleysoto521
# SPDX-License-Identifier: GPL-3.0-or-later
# PCLimpio es software libre: puedes redistribuirlo y modificarlo bajo la licencia GNU GPL v3 o posterior.
"""Herramienta de información del sistema: hardware y software consultados por WMI/CIM (solo lectura)."""
import html
import os
import time

from .util import DATA_DIR, as_list, run_ps

SCRIPT = r"""
$os  = Get-CimInstance Win32_OperatingSystem
$cs  = Get-CimInstance Win32_ComputerSystem
$bios = Get-CimInstance Win32_BIOS
$bb  = Get-CimInstance Win32_BaseBoard
$disks = foreach ($d in Get-PhysicalDisk) {
  $r = $d | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
  [pscustomobject]@{ name=$d.FriendlyName; media=[string]$d.MediaType; bus=[string]$d.BusType; size=$d.Size;
    health=[string]$d.HealthStatus; status=[string]$d.OperationalStatus; serial=$d.SerialNumber;
    firmware=$d.FirmwareVersion; temperature=$r.Temperature; wear=$r.Wear; hours=$r.PowerOnHours }
}
$batt = Get-CimInstance Win32_Battery
$bstatic = Get-CimInstance -Namespace root\wmi -ClassName BatteryStaticData -ErrorAction SilentlyContinue
$bfull = Get-CimInstance -Namespace root\wmi -ClassName BatteryFullChargedCapacity -ErrorAction SilentlyContinue
$mon = Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue | ForEach-Object {
  [pscustomobject]@{ maker=(-join ($_.ManufacturerName | Where-Object {$_} | ForEach-Object {[char]$_}));
                     model=(-join ($_.UserFriendlyName | Where-Object {$_} | ForEach-Object {[char]$_})) } }
[pscustomobject]@{
  os = [pscustomobject]@{ name=$os.Caption; version=$os.Version; build=$os.BuildNumber; arch=$os.OSArchitecture;
        installed=$os.InstallDate.ToString('yyyy-MM-dd'); boot=$os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm');
        user=$env:USERNAME; computer=$env:COMPUTERNAME; ramFree=$os.FreePhysicalMemory*1KB }
  system = [pscustomobject]@{ maker=$cs.Manufacturer; model=$cs.Model; ram=$cs.TotalPhysicalMemory;
        board=("$($bb.Manufacturer) $($bb.Product)").Trim(); bios=("$($bios.Manufacturer) $($bios.SMBIOSBIOSVersion)").Trim();
        biosDate=$(if ($bios.ReleaseDate) { $bios.ReleaseDate.ToString('yyyy-MM-dd') }); serial=$bios.SerialNumber }
  cpu = @(Get-CimInstance Win32_Processor | ForEach-Object { [pscustomobject]@{ name=$_.Name.Trim(); cores=$_.NumberOfCores;
        threads=$_.NumberOfLogicalProcessors; mhz=$_.MaxClockSpeed; l2=$_.L2CacheSize; l3=$_.L3CacheSize;
        socket=$_.SocketDesignation; load=$_.LoadPercentage } })
  memory = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { [pscustomobject]@{ slot=$_.DeviceLocator;
        size=$_.Capacity; speed=$_.ConfiguredClockSpeed; maker=$_.Manufacturer; part=([string]$_.PartNumber).Trim() } })
  gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object { [pscustomobject]@{ name=$_.Name;
        driver=$_.DriverVersion; driverDate=$(if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') });
        res=$(if ($_.CurrentHorizontalResolution) { "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate) Hz" }) } })
  monitors = @($mon)
  disks = @($disks)
  volumes = @(Get-Volume | Where-Object DriveLetter | ForEach-Object { [pscustomobject]@{ letter=[string]$_.DriveLetter;
        label=$_.FileSystemLabel; fs=$_.FileSystem; size=$_.Size; free=$_.SizeRemaining; health=[string]$_.HealthStatus } })
  network = @(Get-NetAdapter | Where-Object Status -eq 'Up' | ForEach-Object { $ip = Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue;
        [pscustomobject]@{ name=$_.Name; desc=$_.InterfaceDescription; mac=$_.MacAddress; speed=$_.LinkSpeed; ip=($ip.IPAddress -join ', ') } })
  audio = @(Get-CimInstance Win32_SoundDevice | ForEach-Object { $_.Name })
  battery = $(if ($batt) { [pscustomobject]@{ name=$batt.Name; charge=$batt.EstimatedChargeRemaining;
        design=($bstatic | Select-Object -First 1).DesignedCapacity; full=($bfull | Select-Object -First 1).FullChargedCapacity } })
}
"""

SECTIONS = [("os", "Sistema operativo"), ("system", "Equipo"), ("cpu", "Procesador"), ("memory", "Memoria RAM"),
            ("gpu", "Gráficos"), ("monitors", "Monitores"), ("disks", "Discos físicos"), ("volumes", "Unidades"),
            ("network", "Red"), ("audio", "Audio"), ("battery", "Batería")]


def _drop_empty(v):
    """En PowerShell un $(if …) sin resultado se serializa como {}; lo convertimos en None."""
    if isinstance(v, dict):
        return {k: _drop_empty(x) for k, x in v.items()} or None
    if isinstance(v, list):
        return [_drop_empty(x) for x in v]
    return v


def collect(job):
    job.update(10, "Consultando el hardware (puede tardar unos segundos)")
    data = _drop_empty(run_ps(SCRIPT, timeout=180)) or {}
    for key in ("cpu", "memory", "gpu", "monitors", "disks", "volumes", "network", "audio"):
        data[key] = as_list(data.get(key))
    bat = data.get("battery")
    if bat and bat.get("design") and bat.get("full"):
        bat["health"] = round(100 * bat["full"] / bat["design"])
    return data


def export_html(data):
    """Guarda un informe HTML en la carpeta de datos de la app y devuelve la ruta."""
    def rows(obj):
        if isinstance(obj, dict):
            return "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>"
                           for k, v in obj.items() if v not in (None, ""))
        return f"<tr><td>{html.escape(str(obj))}</td></tr>"

    parts = [f"<h1>Informe del sistema — {time.strftime('%Y-%m-%d %H:%M')}</h1>"]
    for key, title in SECTIONS:
        val = data.get(key)
        if not val:
            continue
        parts.append(f"<h2>{title}</h2>")
        for item in (val if isinstance(val, list) else [val]):
            parts.append(f"<table>{rows(item)}</table>")
    doc = ("<!doctype html><meta charset='utf-8'><title>Informe del sistema</title><style>"
           "body{font-family:Segoe UI,sans-serif;margin:24px;color:#222}table{border-collapse:collapse;margin:8px 0}"
           "th,td{border:1px solid #ddd;padding:4px 8px;text-align:left}th{background:#f4f4f4}</style>"
           + "".join(parts))
    folder = os.path.join(DATA_DIR, "informes")  # carpeta local (Documentos puede estar sincronizado con la nube)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"Informe_sistema_{time.strftime('%Y%m%d_%H%M')}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
