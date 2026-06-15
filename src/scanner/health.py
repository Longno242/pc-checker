"""System health score from scan results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class HealthResult:
    score: int = 100
    grade: str = "Excellent"
    issues: list[str] = field(default_factory=list)
    breakdown: dict[str, int] = field(default_factory=dict)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return None


def calculate_health(hardware: Any, updates: Any) -> HealthResult:
    result = HealthResult()
    deductions: dict[str, int] = {}

    summary = getattr(updates, "summary", {}) or {}
    critical = int(summary.get("critical", 0))
    recommended = int(summary.get("recommended", 0))

    if critical:
        d = min(40, critical * 20)
        deductions["windows_critical"] = d
        result.issues.append(f"{critical} critical Windows update(s) pending")

    if recommended:
        d = min(25, recommended * 5)
        deductions["updates_recommended"] = d
        if recommended <= 3:
            result.issues.append(f"{recommended} recommended update(s)")

    for vol in _logical_volumes(hardware):
        used = float(vol.get("usedPercent") or 0)
        mount = vol.get("deviceId") or "Drive"
        if used >= 95:
            deductions[f"disk_{mount}"] = 20
            result.issues.append(f"{mount} is {used:.0f}% full — critically low space")
        elif used >= 90:
            deductions[f"disk_{mount}"] = 10
            result.issues.append(f"{mount} is {used:.0f}% full")

    bios = getattr(hardware, "bios", {}) or {}
    rel = _parse_date(bios.get("releaseDate"))
    if rel:
        age_years = (datetime.now() - rel).days / 365.25
        if age_years > 3:
            deductions["bios_age"] = 12
            result.issues.append(f"BIOS is {age_years:.1f} years old")
        elif age_years > 2:
            deductions["bios_age"] = 6

    for item in getattr(updates, "items", []) or []:
        title = (getattr(item, "title", "") or "").lower()
        if "nvidia" in title and "outdated" in title:
            deductions["gpu_driver"] = 15
            result.issues.append("GPU driver is behind latest")
            break
        if "bios" in title and getattr(item, "available_version", None):
            if "update available" in (getattr(item, "description", "") or "").lower():
                deductions["bios_update"] = 15
                result.issues.append("Newer BIOS version available")
                break

    for disk in _physical_disks(hardware):
        health = disk.get("healthStatus")
        if health and str(health).lower() not in ("healthy", "ok", "unknown", "n/a", "none"):
            deductions[f"smart_{disk.get('model', 'disk')}"] = 18
            result.issues.append(f"Drive {disk.get('model', '?')} health: {health}")

    for gpu in getattr(hardware, "gpus", []) or []:
        temp = gpu.get("temperatureC")
        if temp is not None and float(temp) >= 85:
            deductions["gpu_temp"] = 8
            result.issues.append(f"GPU running hot ({temp}°C)")

    total_deduction = min(85, sum(deductions.values()))
    result.breakdown = deductions
    result.score = max(15, 100 - total_deduction)

    if result.score >= 90:
        result.grade = "Excellent"
    elif result.score >= 75:
        result.grade = "Good"
    elif result.score >= 60:
        result.grade = "Fair"
    elif result.score >= 45:
        result.grade = "Needs attention"
    else:
        result.grade = "Poor"

    if not result.issues:
        result.issues.append("No major issues detected")

    return result


def _logical_volumes(hardware: Any) -> list[dict]:
    volumes: list[dict] = []
    for block in getattr(hardware, "storage", []) or []:
        if block.get("logicalVolumes"):
            volumes.extend(block["logicalVolumes"])
    return volumes


def _physical_disks(hardware: Any) -> list[dict]:
    return [d for d in getattr(hardware, "storage", []) or [] if d.get("model")]
