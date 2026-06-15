"""Windows Update and driver/firmware update discovery."""

from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from src.scanner.version_check import (
    check_bios_update,
    check_motherboard_drivers,
    check_nvidia_driver,
)
from src.utils.powershell import run_json_async


@dataclass
class UpdateItem:
    title: str
    category: str
    severity: str  # critical, recommended, optional, info
    description: str
    current_version: str | None = None
    available_version: str | None = None
    action: str = ""
    action_url: str | None = None
    action_label: str | None = None
    kb: str | None = None
    size_mb: float | None = None


@dataclass
class ScanControl:
    cancel: threading.Event = field(default_factory=threading.Event)
    skip_windows_update: threading.Event = field(default_factory=threading.Event)

    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def skip_wu(self) -> bool:
        return self.skip_windows_update.is_set()


@dataclass
class UpdateScanResult:
    items: list[UpdateItem] = field(default_factory=list)
    windows_updates: list[dict[str, Any]] = field(default_factory=list)
    driver_status: list[dict[str, Any]] = field(default_factory=list)
    bios_advisory: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    scanned_at: str = ""
    health: dict[str, Any] = field(default_factory=dict)
    version_checks: dict[str, Any] = field(default_factory=dict)


class UpdateScanner:
    """Checks Windows Update, driver ages, and firmware advisories."""

    WU_TIMEOUT_SEC = 60

    _COMBINED_WU_SCRIPT = r"""
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$searcher.Online = $true
try {
    $result = $searcher.Search("IsInstalled=0")
    $software = @()
    $drivers = @()
    foreach ($u in $result.Updates) {
        $kb = ($u.KBArticleIDs | Select-Object -First 1)
        $cats = @($u.Categories | ForEach-Object { $_.Name })
        $entry = @{
            title = $u.Title
            description = $u.Description
            kb = if ($kb) { "KB$kb" } else { $null }
            categories = $cats
            severity = if ($u.MsrcSeverity) { $u.MsrcSeverity } else { 'Unspecified' }
            sizeMB = [math]::Round($u.MaxDownloadSize / 1MB, 2)
            isMandatory = $u.IsMandatory
            rebootRequired = $u.RebootRequired
            updateType = [int]$u.Type
        }
        $isDriver = ($cats -contains 'Drivers') -or ($u.Title -like '*Driver Update*') -or ([int]$u.Type -eq 2)
        if ($isDriver) { $drivers += $entry } else { $software += $entry }
    }
    @{ software = $software; drivers = $drivers } | ConvertTo-Json -Depth 6 -Compress
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Compress
}
"""

    def scan(
        self,
        hardware: Any = None,
        progress_callback: Callable[[str, float], None] | None = None,
        on_partial: Callable[[UpdateScanResult], None] | None = None,
        control: ScanControl | None = None,
        skip_windows_update: bool = False,
    ) -> UpdateScanResult:
        ctrl = control or ScanControl()
        if skip_windows_update:
            ctrl.skip_windows_update.set()

        result = UpdateScanResult(scanned_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        if progress_callback:
            progress_callback("Analyzing installed drivers...", 0.2)
        if ctrl.cancelled():
            return result
        self._scan_drivers(result, hardware)

        if progress_callback:
            progress_callback("Checking latest GPU & BIOS versions online...", 0.35)
        if ctrl.cancelled():
            return result
        self._check_online_versions(result, hardware)

        if progress_callback:
            progress_callback("Evaluating BIOS / firmware status...", 0.45)
        if ctrl.cancelled():
            return result
        self._bios_advisory(result, hardware)

        if on_partial:
            on_partial(result)

        if not ctrl.skip_wu() and not ctrl.cancelled():
            if progress_callback:
                progress_callback("Checking Windows Update (may take up to 60s)...", 0.55)
            self._scan_windows_updates(result, progress_callback, ctrl)
        elif ctrl.skip_wu():
            result.errors.append("Windows Update skipped by user/settings.")

        if progress_callback:
            progress_callback("Building update report...", 1.0)
        self._build_summary(result)
        return result

    def scan_async(
        self,
        hardware: Any,
        on_complete: Callable[[UpdateScanResult], None],
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> threading.Thread:
        def worker():
            res = self.scan(hardware, progress_callback)
            on_complete(res)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return t

    def _run_ps(
        self,
        script: str,
        timeout: int = 90,
        progress_callback: Callable[[str, float], None] | None = None,
        progress: float = 0.0,
        progress_label: str = "Working",
        control: ScanControl | None = None,
    ) -> Any:
        def on_tick(elapsed: int) -> None:
            if progress_callback:
                progress_callback(f"{progress_label} ({elapsed}s)", progress)

        return run_json_async(
            script,
            timeout=timeout,
            on_tick=on_tick if progress_callback else None,
            is_cancelled=control.cancelled if control else None,
        )

    def _scan_windows_updates(
        self,
        result: UpdateScanResult,
        progress_callback: Callable[[str, float], None] | None = None,
        control: ScanControl | None = None,
    ) -> None:
        try:
            data = self._run_ps(
                self._COMBINED_WU_SCRIPT,
                timeout=self.WU_TIMEOUT_SEC,
                progress_callback=progress_callback,
                progress=0.65,
                progress_label="Checking Windows Update",
                control=control,
            )
            if isinstance(data, dict) and data.get("error"):
                result.errors.append(f"Windows Update: {data['error']}")
                return
            if not isinstance(data, dict):
                return

            software = data.get("software") or []
            drivers = data.get("drivers") or []
            if isinstance(software, dict):
                software = [software]
            if isinstance(drivers, dict):
                drivers = [drivers]

            result.windows_updates = software

            for u in software:
                if not isinstance(u, dict):
                    continue
                cats = u.get("categories") or []
                cat_str = ", ".join(cats) if cats else "Windows"
                severity = self._map_severity(u.get("severity"), u.get("isMandatory"))
                result.items.append(
                    UpdateItem(
                        title=u.get("title") or "Windows Update",
                        category=cat_str,
                        severity=severity,
                        description=(u.get("description") or "")[:300],
                        available_version=u.get("kb"),
                        action="Install via Windows Update",
                        action_url="ms-settings:windowsupdate",
                        action_label="Open Windows Update",
                        kb=u.get("kb"),
                        size_mb=u.get("sizeMB"),
                    )
                )

            for u in drivers:
                if not isinstance(u, dict):
                    continue
                title = u.get("title") or "Driver update"
                result.items.append(
                    UpdateItem(
                        title=title,
                        category="Driver Update (Windows Update)",
                        severity="recommended",
                        description=(u.get("description") or "Optional driver available via Windows Update.")[:300],
                        action="Settings → Windows Update → Advanced → Optional updates",
                        action_url="ms-settings:windowsupdate-optionalupdates",
                        action_label="Optional updates",
                        size_mb=u.get("sizeMB"),
                    )
                )
        except InterruptedError:
            result.errors.append("Windows Update check cancelled.")
        except subprocess.TimeoutExpired:
            result.errors.append(
                f"Windows Update did not respond within {self.WU_TIMEOUT_SEC}s — skipped. "
                "Driver and BIOS results above are still valid."
            )
        except Exception as exc:
            result.errors.append(f"Windows Update scan: {exc}")

    def _scan_drivers(self, result: UpdateScanResult, hardware: Any) -> None:
        """Analyze drivers from hardware scan data — avoids slow Win32_PnPSignedDriver WMI."""
        if not hardware:
            return

        cutoff = datetime.now() - timedelta(days=730)
        stale: list[tuple[int, UpdateItem]] = []
        driver_rows: list[dict[str, Any]] = []

        devices: list[tuple[str, str, str | None, str | None]] = []
        for gpu in hardware.gpus or []:
            devices.append((
                gpu.get("name") or "GPU",
                "DISPLAY",
                gpu.get("nvidiaDriver") or gpu.get("driverVersion"),
                gpu.get("driverDate"),
            ))
        for nic in hardware.network or []:
            devices.append((
                nic.get("name") or "Network adapter",
                "NET",
                nic.get("driverVersion"),
                nic.get("driverDate"),
            ))

        for device, device_class, version, date_raw in devices:
            if not version:
                continue
            driver_rows.append({
                "DeviceName": device,
                "DeviceClass": device_class,
                "DriverVersion": version,
                "DriverDate": date_raw,
            })
            driver_date = self._parse_driver_date(date_raw)
            if driver_date and driver_date < cutoff:
                age_days = (datetime.now() - driver_date).days
                stale.append((
                    age_days,
                    UpdateItem(
                        title=f"{device} — driver may be outdated",
                        category=f"{device_class.title()} Driver",
                        severity="recommended" if age_days > 1095 else "optional",
                        description=(
                            f"Installed driver dated {driver_date.strftime('%Y-%m-%d')} "
                            f"({age_days // 365}+ years old)."
                        ),
                        current_version=version,
                        action="Check Device Manager or manufacturer support site",
                    ),
                ))

        result.driver_status = driver_rows
        for _, item in sorted(stale, key=lambda pair: pair[0], reverse=True)[:8]:
            result.items.append(item)

        for gpu in hardware.gpus or []:
            name = gpu.get("name") or "GPU"
            ver = gpu.get("nvidiaDriver") or gpu.get("driverVersion")
            date = gpu.get("driverDate")
            if name and ver:
                result.items.append(
                    UpdateItem(
                        title=f"{name} — graphics driver",
                        category="GPU",
                        severity="info",
                        description=f"Current driver: {ver}" + (f" (dated {date})" if date else ""),
                        current_version=ver,
                        action=self._gpu_update_action(name),
                        action_url="https://www.nvidia.com/en-us/drivers/" if "NVIDIA" in name.upper() else None,
                        action_label="Download driver",
                    )
                )

    def _check_online_versions(self, result: UpdateScanResult, hardware: Any) -> None:
        if not hardware:
            return

        board = hardware.motherboard or {}
        bios = hardware.bios or {}
        mb_url = check_motherboard_drivers(board)
        result.version_checks["motherboard_drivers_url"] = mb_url

        for gpu in hardware.gpus or []:
            name = gpu.get("name") or ""
            current = gpu.get("nvidiaDriver") or gpu.get("driverVersion")
            if "NVIDIA" not in name.upper() or not current:
                continue
            nv = check_nvidia_driver(name, current)
            result.version_checks["nvidia"] = nv
            latest = nv.get("latest")
            if latest:
                desc = f"Installed: {current} · Latest: {latest}"
                severity = "recommended" if nv.get("update_available") else "info"
                title = f"{name} — {'driver update available' if nv.get('update_available') else 'driver up to date'}"
                result.items.append(
                    UpdateItem(
                        title=title,
                        category="GPU Driver Check",
                        severity=severity,
                        description=desc,
                        current_version=current,
                        available_version=latest,
                        action="Download from NVIDIA" if nv.get("update_available") else "You have the latest driver",
                        action_url=nv.get("url"),
                        action_label="Open NVIDIA drivers",
                    )
                )

        bios_check = check_bios_update(board, bios)
        result.version_checks["bios"] = bios_check
        if bios_check.get("latest"):
            current = bios_check.get("current") or "Unknown"
            latest = bios_check.get("latest")
            update_avail = bios_check.get("update_available")
            result.items.append(
                UpdateItem(
                    title=f"BIOS version check ({board.get('product', 'Motherboard')})",
                    category="Firmware",
                    severity="recommended" if update_avail else "info",
                    description=(
                        f"Installed: {current} · Latest online: {latest}"
                        + (f" ({bios_check.get('release_date')})" if bios_check.get("release_date") else "")
                    ),
                    current_version=current,
                    available_version=latest,
                    action="Download latest BIOS from manufacturer" if update_avail else "BIOS appears current",
                    action_url=bios_check.get("url"),
                    action_label="Open BIOS downloads",
                )
            )

        if board.get("product"):
            result.items.append(
                UpdateItem(
                    title=f"Motherboard drivers — {board.get('product')}",
                    category="Drivers",
                    severity="info",
                    description="Download chipset, LAN, audio and other drivers for your board.",
                    action="Open manufacturer driver page",
                    action_url=mb_url,
                    action_label="Open driver page",
                )
            )

    def _bios_advisory(self, result: UpdateScanResult, hardware: Any) -> None:
        bios = getattr(hardware, "bios", None) or {}
        board = getattr(hardware, "motherboard", None) or {}
        system = getattr(hardware, "system", None) or {}

        manufacturer = (
            bios.get("manufacturer")
            or board.get("manufacturer")
            or system.get("manufacturer")
            or "Unknown"
        )
        version = bios.get("version") or bios.get("name") or "Unknown"
        release = bios.get("releaseDate")

        advisory = {
            "manufacturer": manufacturer,
            "current_version": version,
            "release_date": release,
            "support_url": self._manufacturer_bios_url(manufacturer, system.get("model")),
            "notes": [],
        }

        if release:
            try:
                rel_date = datetime.strptime(release[:10], "%Y-%m-%d")
                age_years = (datetime.now() - rel_date).days / 365.25
                if age_years > 2:
                    advisory["notes"].append(
                        f"BIOS release is {age_years:.1f} years old — check {manufacturer} for security and compatibility updates."
                    )
                    result.items.append(
                        UpdateItem(
                            title=f"BIOS / UEFI firmware ({manufacturer})",
                            category="Firmware",
                            severity="recommended" if age_years > 3 else "optional",
                            description=f"Current: {version} ({release}). Firmware updates can fix stability, security, and CPU support.",
                            current_version=version,
                            action=f"Visit manufacturer support → enter serial/model → compare latest BIOS",
                        )
                    )
                else:
                    advisory["notes"].append("BIOS appears relatively recent — still verify against manufacturer latest.")
            except ValueError:
                advisory["notes"].append("Could not parse BIOS release date — verify manually on manufacturer site.")

        fw_updates = [
            i for i in result.items
            if any(k in (i.title or "").lower() for k in ("firmware", "bios", "uefi", "system firmware"))
        ]
        if fw_updates:
            advisory["notes"].append("Windows Update lists firmware-related updates — review the Updates tab.")

        result.bios_advisory = advisory

        result.items.append(
            UpdateItem(
                title="BIOS update checklist",
                category="Firmware",
                severity="info",
                description=(
                    "Before updating BIOS: plug into power, back up important data, "
                    "do not interrupt the flash. Use only your OEM's official tool."
                ),
                current_version=version,
                action=advisory.get("support_url") or "Open your PC/motherboard maker support page",
                action_url=result.version_checks.get("bios", {}).get("url") or advisory.get("support_url"),
                action_label="Open BIOS page",
            )
        )

    def _build_summary(self, result: UpdateScanResult) -> None:
        counts = {"critical": 0, "recommended": 0, "optional": 0, "info": 0}
        for item in result.items:
            key = item.severity if item.severity in counts else "info"
            counts[key] += 1
        result.summary = counts

    @staticmethod
    def _parse_driver_date(raw: Any) -> datetime | None:
        if not raw:
            return None
        if isinstance(raw, str):
            for fmt in (
                "/Date(%f)/",
                "/Date(%f)%",
                "%Y-%m-%d",
                "%m/%d/%Y",
            ):
                if fmt.startswith("/Date"):
                    m = re.search(r"/Date\((\d+)", raw)
                    if m:
                        ts = int(m.group(1)) / 1000
                        return datetime.fromtimestamp(ts)
                else:
                    try:
                        return datetime.strptime(raw[:10], fmt[:8] if "%" in fmt else fmt)
                    except ValueError:
                        continue
        return None

    @staticmethod
    def _map_severity(msrc: str | None, mandatory: bool | None) -> str:
        if mandatory:
            return "critical"
        if not msrc:
            return "recommended"
        m = msrc.lower()
        if "critical" in m:
            return "critical"
        if "important" in m:
            return "recommended"
        return "optional"

    @staticmethod
    def _gpu_update_action(gpu_name: str) -> str:
        upper = gpu_name.upper()
        if "NVIDIA" in upper:
            return "Download latest Game Ready driver from nvidia.com/drivers"
        if "AMD" in upper or "RADEON" in upper:
            return "Download latest Adrenalin driver from amd.com/support"
        if "INTEL" in upper:
            return "Download Intel Arc / graphics driver from intel.com/download-center"
        return "Check GPU manufacturer website for latest driver"

    @staticmethod
    def _manufacturer_bios_url(manufacturer: str, model: str | None) -> str:
        m = (manufacturer or "").lower()
        if "dell" in m:
            return "https://www.dell.com/support/home/drivers"
        if "hp" in m or "hewlett" in m:
            return "https://support.hp.com/drivers"
        if "lenovo" in m:
            return "https://support.lenovo.com/us/en/downloads"
        if "asus" in m:
            return "https://www.asus.com/support/download-center/"
        if "msi" in m:
            return "https://www.msi.com/support/download"
        if "gigabyte" in m:
            return "https://www.gigabyte.com/Support"
        if "acer" in m:
            return "https://www.acer.com/us-en/support"
        return "https://www.google.com/search?q=" + (manufacturer or "PC") + "+BIOS+update"
