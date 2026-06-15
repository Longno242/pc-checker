"""PowerShell-backed hardware discovery for Windows."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

from src.utils.powershell import run_json


@dataclass
class ScanResult:
    system: dict[str, Any] = field(default_factory=dict)
    cpu: dict[str, Any] = field(default_factory=dict)
    gpus: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    storage: list[dict[str, Any]] = field(default_factory=list)
    monitors: list[dict[str, Any]] = field(default_factory=list)
    motherboard: dict[str, Any] = field(default_factory=dict)
    bios: dict[str, Any] = field(default_factory=dict)
    network: list[dict[str, Any]] = field(default_factory=list)
    os_info: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class HardwareScanner:
    """Collects detailed PC specifications via WMI and native Windows APIs."""

    _VIRTUAL_GPU_MARKERS = (
        "META",
        "OCULUS",
        "VIRTUAL MONITOR",
        "VIRTUAL DISPLAY",
        "PARSEC VIRTUAL",
    )
    _VIRTUAL_PNP_PREFIXES = ("ROOT\\DISPLAY\\",)

    _SCAN_SCRIPT = r"""
$out = @{
    system = $null; cpu = $null; gpus = @(); memory = $null
    storage = @(); monitors = @(); motherboard = $null; bios = $null
    network = @(); os_info = $null
}

try {
    $cs = Get-CimInstance Win32_ComputerSystem
    $out.system = @{
        manufacturer = $cs.Manufacturer
        model = $cs.Model
        name = $cs.Name
        domain = $cs.Domain
        totalPhysicalMemoryGB = [math]::Round($cs.TotalPhysicalMemory / 1GB, 2)
        systemType = $cs.SystemType
        chassis = (Get-CimInstance Win32_SystemEnclosure | Select-Object -First 1).ChassisTypes
    }
} catch {}

try {
    $p = Get-CimInstance Win32_Processor | Select-Object -First 1
    $out.cpu = @{
        name = $p.Name.Trim()
        manufacturer = $p.Manufacturer
        cores = $p.NumberOfCores
        logicalProcessors = $p.NumberOfLogicalProcessors
        maxClockMHz = $p.MaxClockSpeed
        currentClockMHz = $p.CurrentClockSpeed
        architecture = $p.Architecture
        socket = $p.SocketDesignation
        l2CacheKB = $p.L2CacheSize
        l3CacheKB = $p.L3CacheSize
        virtualization = $p.VirtualizationFirmwareEnabled
    }
} catch {}

try {
    $out.gpus = @(Get-CimInstance Win32_VideoController | ForEach-Object {
        @{
            name = $_.Name
            driverVersion = $_.DriverVersion
            driverDate = if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { $null }
            vramMB = if ($_.AdapterRAM -and $_.AdapterRAM -gt 0) { [math]::Round($_.AdapterRAM / 1MB, 0) } else { $null }
            status = $_.Status
            pnpDeviceId = $_.PNPDeviceID
            videoProcessor = $_.VideoProcessor
            currentResolution = "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate)Hz"
        }
    })
} catch {}

try {
    $sticks = @(Get-CimInstance Win32_PhysicalMemory)
    $totalGB = [math]::Round(($sticks | Measure-Object -Property Capacity -Sum).Sum / 1GB, 2)
    $out.memory = @{
        totalGB = $totalGB
        slotsUsed = $sticks.Count
        maxSpeedMHz = ($sticks | Measure-Object -Property Speed -Maximum).Maximum
        type = ($sticks | Select-Object -First 1).MemoryType
        formFactor = ($sticks | Select-Object -First 1).FormFactor
        modules = @($sticks | ForEach-Object {
            @{
                manufacturer = $_.Manufacturer
                partNumber = ($_.PartNumber -replace '\s+$','')
                capacityGB = [math]::Round($_.Capacity / 1GB, 2)
                speedMHz = $_.Speed
                bankLabel = $_.BankLabel
                deviceLocator = $_.DeviceLocator
            }
        })
    }
} catch {}

try {
    $out.storage = @(Get-CimInstance Win32_DiskDrive | ForEach-Object {
        @{
            model = $_.Model.Trim()
            interfaceType = $_.InterfaceType
            mediaType = $_.MediaType
            sizeGB = [math]::Round($_.Size / 1GB, 2)
            serialNumber = ($_.SerialNumber -replace '\s+$','')
            firmwareRevision = $_.FirmwareRevision
            status = $_.Status
            partitions = $_.Partitions
        }
    })
    $logical = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
        @{
            deviceId = $_.DeviceID
            label = $_.VolumeName
            fileSystem = $_.FileSystem
            sizeGB = [math]::Round($_.Size / 1GB, 2)
            freeGB = [math]::Round($_.FreeSpace / 1GB, 2)
            usedPercent = if ($_.Size -gt 0) { [math]::Round((1 - $_.FreeSpace / $_.Size) * 100, 1) } else { 0 }
        }
    })
    $out.storage += @{ logicalVolumes = $logical }
} catch {}

try {
    $out.monitors = @(Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue | ForEach-Object {
        $name = -join ($_.UserFriendlyName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ })
        $serial = -join ($_.SerialNumberID | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ })
        $manufacturer = -join ($_.ManufacturerName | Where-Object { $_ -ne 0 } | ForEach-Object { [char]$_ })
        @{
            name = if ($name) { $name.Trim([char]0) } else { 'Unknown Display' }
            manufacturer = if ($manufacturer) { $manufacturer.Trim([char]0) } else { $null }
            serial = if ($serial) { $serial.Trim([char]0) } else { $null }
            instance = $_.InstanceName
        }
    })
    if ($out.monitors.Count -eq 0) {
        Add-Type @"
using System; using System.Runtime.InteropServices;
public class DisplayEnum {
    [DllImport("user32.dll")] public static extern bool EnumDisplayDevices(string lpDevice, uint iDevNum, ref DISPLAY_DEVICE lpDisplayDevice, uint dwFlags);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)] public struct DISPLAY_DEVICE {
        public int cb; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceString;
        public int StateFlags; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceKey;
    }
}
"@
        $i = 0
        while ($true) {
            $dd = New-Object DisplayEnum+DISPLAY_DEVICE
            $dd.cb = [System.Runtime.InteropServices.Marshal]::SizeOf($dd)
            if (-not [DisplayEnum]::EnumDisplayDevices($null, $i, [ref]$dd, 0)) { break }
            if ($dd.StateFlags -band 0x00000001) {
                $out.monitors += @{ name = $dd.DeviceString; deviceId = $dd.DeviceID; source = 'EnumDisplayDevices' }
            }
            $i++
        }
    }
} catch {}

try {
    $bb = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
    $out.motherboard = @{
        manufacturer = $bb.Manufacturer
        product = $bb.Product
        version = $bb.Version
        serialNumber = $bb.SerialNumber
    }
} catch {}

try {
    $b = Get-CimInstance Win32_BIOS | Select-Object -First 1
    $out.bios = @{
        manufacturer = $b.Manufacturer
        name = $b.Name
        version = $b.SMBIOSBIOSVersion
        releaseDate = if ($b.ReleaseDate) { $b.ReleaseDate.ToString('yyyy-MM-dd') } else { $null }
        serialNumber = $b.SerialNumber
        smbiosVersion = $b.SMBIOSMajorVersion.ToString() + '.' + $b.SMBIOSMinorVersion.ToString()
    }
} catch {}

try {
    $out.network = @(Get-CimInstance Win32_NetworkAdapter -Filter "PhysicalAdapter=True AND NOT Description LIKE '%Virtual%'" |
        Where-Object { $_.NetEnabled -eq $true -or $_.NetConnectionStatus -eq 2 } |
        ForEach-Object {
            @{
                name = $_.Name
                manufacturer = $_.Manufacturer
                macAddress = $_.MACAddress
                speedMbps = if ($_.Speed) { [math]::Round($_.Speed / 1000000, 0) } else { $null }
                driverVersion = $_.DriverVersion
                driverDate = if ($_.DriverDate) { $_.DriverDate.ToString('yyyy-MM-dd') } else { $null }
            }
        })
} catch {}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $out.os_info = @{
        caption = $os.Caption
        version = $os.Version
        build = $os.BuildNumber
        architecture = $os.OSArchitecture
        installDate = if ($os.InstallDate) { $os.InstallDate.ToString('yyyy-MM-dd') } else { $null }
        lastBoot = if ($os.LastBootUpTime) { $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm') } else { $null }
        registeredUser = $os.RegisteredUser
    }
} catch {}

$out | ConvertTo-Json -Depth 8 -Compress
"""

    def scan(self, progress_callback=None) -> ScanResult:
        result = ScanResult()
        if progress_callback:
            progress_callback("Querying hardware via WMI...", 0.1)
        try:
            data = run_json(self._SCAN_SCRIPT)
            if isinstance(data, dict):
                result.system = data.get("system") or {}
                result.cpu = data.get("cpu") or {}
                result.gpus = self._filter_gpus(data.get("gpus") or [])
                result.memory = data.get("memory") or {}
                raw_storage = data.get("storage") or []
                result.storage = [s for s in raw_storage if isinstance(s, dict)]
                result.monitors = data.get("monitors") or []
                result.motherboard = data.get("motherboard") or {}
                result.bios = data.get("bios") or {}
                result.network = data.get("network") or []
                result.os_info = data.get("os_info") or {}
        except Exception as exc:
            result.errors.append(f"Hardware scan failed: {exc}")

        if progress_callback:
            progress_callback("Enriching GPU data...", 0.6)
        self._enrich_gpu(result)
        if progress_callback:
            progress_callback("Reading display modes...", 0.75)
        self._enrich_displays(result)
        if progress_callback:
            progress_callback("Reading drive health...", 0.9)
        self._enrich_storage_health(result)
        if progress_callback:
            progress_callback("Hardware scan complete.", 1.0)
        return result

    @staticmethod
    def _is_virtual_gpu(gpu: dict[str, Any]) -> bool:
        name = (gpu.get("name") or "").upper()
        pnp = (gpu.get("pnpDeviceId") or "").upper()
        if any(marker in name for marker in HardwareScanner._VIRTUAL_GPU_MARKERS):
            return True
        if any(pnp.startswith(prefix) for prefix in HardwareScanner._VIRTUAL_PNP_PREFIXES):
            return True
        return False

    @classmethod
    def _filter_gpus(cls, gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
        physical = [gpu for gpu in gpus if not cls._is_virtual_gpu(gpu)]
        chosen = physical if physical else gpus

        def sort_key(gpu: dict[str, Any]) -> tuple[int, str]:
            name = (gpu.get("name") or "").upper()
            pnp = (gpu.get("pnpDeviceId") or "").upper()
            priority = 0
            if pnp.startswith("PCI\\"):
                priority += 100
            if any(tag in name for tag in ("NVIDIA", "AMD", "RADEON", "INTEL ARC")):
                priority += 50
            return (-priority, name)

        return sorted(chosen, key=sort_key)

    @staticmethod
    def _enrich_gpu(result: ScanResult) -> None:
        nvidia_gpus = [gpu for gpu in result.gpus if "NVIDIA" in (gpu.get("name") or "").upper()]
        if not nvidia_gpus:
            return

        try:
            nv = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if nv.returncode != 0 or not nv.stdout.strip():
                return

            for line in nv.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 4:
                    continue
                smi_name, driver, vram, temp = parts[0], parts[1], parts[2], parts[3]
                target = next(
                    (gpu for gpu in nvidia_gpus if smi_name.upper() in (gpu.get("name") or "").upper()),
                    nvidia_gpus[0],
                )
                target["nvidiaDriver"] = driver
                target["vramMB"] = float(vram)
                target["temperatureC"] = float(temp)
                target["source"] = "nvidia-smi"
                break
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass

    _DISPLAY_SCRIPT = r"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class NativeDisplay {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)] public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
        public short dmSpecVersion; public short dmDriverVersion; public short dmSize; public short dmDriverExtra;
        public int dmFields; public int dmPositionX; public int dmPositionY; public int dmDisplayOrientation;
        public int dmDisplayFixedOutput; public short dmColor; public short dmDuplex; public short dmYResolution;
        public short dmTTHierarchy; public short dmTTOption; public short dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
        public short dmLogPixels; public int dmBitsPerPel; public int dmPelsWidth; public int dmPelsHeight;
        public int dmDisplayFlags; public int dmDisplayFrequency; public int dmICMMethod; public int dmICMIntent;
        public int dmMediaType; public int dmDitherType; public int dmReserved1; public int dmReserved2;
        public int dmPanningWidth; public int dmPanningHeight;
    }
    [DllImport("user32.dll")] public static extern bool EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);
    [DllImport("user32.dll")] public static extern bool EnumDisplayDevices(string lpDevice, uint iDevNum, ref DISPLAY_DEVICE lpDisplayDevice, uint dwFlags);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)] public struct DISPLAY_DEVICE {
        public int cb; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceString;
        public int StateFlags; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string DeviceKey;
    }
}
"@
$displays = @()
$i = 0
while ($true) {
    $dd = New-Object NativeDisplay+DISPLAY_DEVICE
    $dd.cb = [Runtime.InteropServices.Marshal]::SizeOf($dd)
    if (-not [NativeDisplay]::EnumDisplayDevices($null, $i, [ref]$dd, 0)) { break }
    if ($dd.StateFlags -band 1) {
        $dm = New-Object NativeDisplay+DEVMODE
        $dm.dmSize = [Runtime.InteropServices.Marshal]::SizeOf($dm)
        [NativeDisplay]::EnumDisplaySettings($dd.DeviceName, -1, [ref]$dm) | Out-Null
        $conn = if ($dd.DeviceID -match 'DISPLAY') { if ($dd.DeviceID -match 'HDMI|HDA') {'HDMI'} elseif ($dd.DeviceID -match 'DP|DisplayPort') {'DisplayPort'} else {'Unknown'} } else {'Internal'}
        $displays += @{
            name = $dd.DeviceString
            deviceId = $dd.DeviceID
            resolution = "$($dm.dmPelsWidth)x$($dm.dmPelsHeight)"
            refreshHz = $dm.dmDisplayFrequency
            hdr = [bool]($dm.dmDisplayFlags -band 0x00000002)
            connection = $conn
            primary = [bool]($dd.StateFlags -band 0x4)
        }
    }
    $i++
}
$displays | ConvertTo-Json -Depth 4 -Compress
"""

    _STORAGE_HEALTH_SCRIPT = r"""
$rows = @()
Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
    $pd = $_
    $rel = $null
    try { $rel = Get-StorageReliabilityCounter -PhysicalDisk $pd -ErrorAction SilentlyContinue } catch {}
    $rows += @{
        friendlyName = $pd.FriendlyName
        model = $pd.Model
        mediaType = $pd.MediaType
        healthStatus = $pd.HealthStatus
        operationalStatus = $pd.OperationalStatus
        temperature = if ($rel) { $rel.Temperature } else { $null }
        wear = if ($rel) { $rel.Wear } else { $null }
        powerOnHours = if ($rel) { $rel.PowerOnHours } else { $null }
        sizeGB = [math]::Round($pd.Size / 1GB, 2)
    }
}
$rows | ConvertTo-Json -Depth 4 -Compress
"""

    @staticmethod
    def _merge_monitors(existing: list[dict[str, Any]], modes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not modes:
            return existing
        if not existing:
            return modes
        merged: list[dict[str, Any]] = []
        for i, mon in enumerate(existing):
            extra = modes[i] if i < len(modes) else {}
            merged.append({**mon, **{k: v for k, v in extra.items() if v is not None}})
        for extra in modes[len(existing) :]:
            merged.append(extra)
        return merged

    def _enrich_displays(self, result: ScanResult) -> None:
        try:
            data = run_json(self._DISPLAY_SCRIPT, timeout=20)
            modes = data if isinstance(data, list) else ([data] if data else [])
            result.monitors = self._merge_monitors(result.monitors, modes)
        except Exception as exc:
            result.errors.append(f"Display modes: {exc}")

    def _enrich_storage_health(self, result: ScanResult) -> None:
        try:
            data = run_json(self._STORAGE_HEALTH_SCRIPT, timeout=25)
            health_rows = data if isinstance(data, list) else ([data] if data else [])
            by_model = {(r.get("model") or r.get("friendlyName") or "").strip().upper(): r for r in health_rows if isinstance(r, dict)}
            for disk in result.storage:
                if not disk.get("model"):
                    continue
                key = disk.get("model", "").strip().upper()
                match = by_model.get(key)
                if not match:
                    for k, row in by_model.items():
                        if key in k or k in key:
                            match = row
                            break
                if match:
                    disk["healthStatus"] = match.get("healthStatus")
                    disk["temperatureC"] = match.get("temperature")
                    disk["wearPercent"] = match.get("wear")
                    disk["powerOnHours"] = match.get("powerOnHours")
                    disk["operationalStatus"] = match.get("operationalStatus")
        except Exception as exc:
            result.errors.append(f"Drive health: {exc}")
