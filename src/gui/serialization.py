from __future__ import annotations

from dataclasses import fields
from typing import Any

from src.scanner.hardware import ScanResult
from src.scanner.updates import UpdateItem, UpdateScanResult


def hardware_from_dict(data: dict[str, Any]) -> ScanResult:
    result = ScanResult()
    for key in ("system", "cpu", "memory", "motherboard", "bios", "os_info"):
        setattr(result, key, data.get(key) or {})
    result.gpus = data.get("gpus") or []
    result.storage = data.get("storage") or []
    result.monitors = data.get("monitors") or []
    result.network = data.get("network") or []
    result.errors = data.get("errors") or []
    return result


def updates_from_dict(data: dict[str, Any]) -> UpdateScanResult:
    valid_fields = {field.name for field in fields(UpdateItem)}
    items = [
        UpdateItem(**{key: value for key, value in raw.items() if key in valid_fields})
        for raw in data.get("items") or []
        if isinstance(raw, dict)
    ]
    return UpdateScanResult(
        scanned_at=data.get("scanned_at", ""),
        items=items,
        summary=data.get("summary") or {},
        errors=data.get("errors") or [],
        bios_advisory=data.get("bios_advisory") or {},
        health=data.get("health") or {},
        version_checks=data.get("version_checks") or {},
    )
