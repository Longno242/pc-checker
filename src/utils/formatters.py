"""Shared formatting helpers."""

from __future__ import annotations

from typing import Any


def fmt_gb(value: Any, suffix: str = " GB") -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.1f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def fmt_mhz(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,} MHz"
    except (TypeError, ValueError):
        return str(value)


def safe_str(value: Any, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return str(value).strip()


def severity_color(severity: str) -> str:
    return {
        "critical": "#ef4444",
        "recommended": "#f59e0b",
        "optional": "#3b82f6",
        "info": "#64748b",
    }.get(severity, "#64748b")


def severity_label(severity: str) -> str:
    return {
        "critical": "Critical",
        "recommended": "Recommended",
        "optional": "Optional",
        "info": "Info",
    }.get(severity, severity.title())
