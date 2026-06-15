"""Local config, last-scan cache, and scan history."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "PCChecker"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    auto_scan_on_open: bool = False
    skip_windows_update: bool = False

    @classmethod
    def load(cls) -> AppSettings:
        path = _app_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                auto_scan_on_open=bool(data.get("auto_scan_on_open", False)),
                skip_windows_update=bool(data.get("skip_windows_update", False)),
            )
        except (json.JSONDecodeError, OSError):
            return cls()

    def save(self) -> None:
        path = _app_dir() / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "auto_scan_on_open": self.auto_scan_on_open,
                    "skip_windows_update": self.skip_windows_update,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


@dataclass
class ScanPersistence:
    MAX_HISTORY = 5

    @staticmethod
    def _serialize_updates(updates: Any) -> dict[str, Any]:
        if updates is None:
            return {}
        items = []
        for item in getattr(updates, "items", []) or []:
            items.append(asdict(item) if hasattr(item, "__dataclass_fields__") else item)
        return {
            "scanned_at": getattr(updates, "scanned_at", ""),
            "items": items,
            "summary": getattr(updates, "summary", {}),
            "errors": getattr(updates, "errors", []),
            "bios_advisory": getattr(updates, "bios_advisory", {}),
            "health": getattr(updates, "health", {}),
            "version_checks": getattr(updates, "version_checks", {}),
        }

    @staticmethod
    def _serialize_hardware(hw: Any) -> dict[str, Any]:
        if hw is None:
            return {}
        return {
            "system": hw.system,
            "cpu": hw.cpu,
            "gpus": hw.gpus,
            "memory": hw.memory,
            "storage": hw.storage,
            "monitors": hw.monitors,
            "motherboard": hw.motherboard,
            "bios": hw.bios,
            "network": hw.network,
            "os_info": hw.os_info,
            "errors": hw.errors,
        }

    def save_scan(self, hardware: Any, updates: Any, health: dict[str, Any] | None = None) -> None:
        payload = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "hardware": self._serialize_hardware(hardware),
            "updates": self._serialize_updates(updates),
            "health": health or getattr(updates, "health", {}) or {},
        }
        last_path = _app_dir() / "last_scan.json"
        last_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        history_dir = _app_dir() / "history"
        history_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (history_dir / f"scan_{stamp}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

        files = sorted(history_dir.glob("scan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[self.MAX_HISTORY :]:
            try:
                old.unlink()
            except OSError:
                pass

    def load_last_scan(self) -> dict[str, Any] | None:
        path = _app_dir() / "last_scan.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list_history(self) -> list[dict[str, Any]]:
        history_dir = _app_dir() / "history"
        if not history_dir.exists():
            return []
        entries: list[dict[str, Any]] = []
        for path in sorted(history_dir.glob("scan_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries.append(
                    {
                        "path": str(path),
                        "saved_at": data.get("saved_at", path.stem),
                        "health_score": (data.get("health") or {}).get("score"),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue
        return entries[: self.MAX_HISTORY]

    @staticmethod
    def load_history_file(path: str) -> dict[str, Any] | None:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
