"""Online version checks for GPU drivers and BIOS firmware."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any


from src.utils.version import is_newer_version


def _fetch_json(url: str, timeout: int = 12) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "PCChecker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_text(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "PCChecker/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def check_nvidia_driver(gpu_name: str, current_version: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "current": current_version,
        "latest": None,
        "update_available": False,
        "url": "https://www.nvidia.com/en-us/drivers/",
    }
    if not current_version or "NVIDIA" not in (gpu_name or "").upper():
        return result

    gpu_query = gpu_name.replace("NVIDIA", "").replace("GeForce", "").strip()
    gpu_query = re.sub(r"\s+", "+", gpu_query)

    try:
        ps = (
            f"$gpu='{gpu_query}'; "
            "$url='https://gfwsl.geforce.com/services/control.php?version=1.0&language=en-US&gpu=' + "
            "[uri]::EscapeDataString($gpu.Replace('+',' ')) + '&OS=135&driverType=all'; "
            "(Invoke-RestMethod -Uri $url -TimeoutSec 12).IDS | ConvertTo-Json -Compress"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip())
            if isinstance(data, list) and data:
                latest = str(data[0].get("version") or data[0].get("Version") or "")
                if latest:
                    result["latest"] = latest
                    result["update_available"] = is_newer_version(latest, current_version)
                    result["url"] = "https://www.nvidia.com/en-us/drivers/"
                    return result
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError, ValueError):
        pass

    try:
        text = _fetch_text("https://www.nvidia.com/en-us/drivers/", timeout=10)
        match = re.search(r"(\d{3}\.\d{2,3})", text)
        if match:
            latest = match.group(1)
            result["latest"] = latest
            result["update_available"] = is_newer_version(latest, current_version)
    except OSError:
        pass

    return result


def check_bios_update(motherboard: dict[str, Any], bios: dict[str, Any]) -> dict[str, Any]:
    manufacturer = (bios.get("manufacturer") or motherboard.get("manufacturer") or "").lower()
    product = (motherboard.get("product") or "").strip()
    current = bios.get("version") or bios.get("name") or ""
    result: dict[str, Any] = {
        "current": current,
        "latest": None,
        "update_available": False,
        "url": _motherboard_url(manufacturer, product),
        "release_date": None,
    }
    if not product:
        return result

    if "asus" in manufacturer:
        return _check_asus_bios(product, current, result)
    if "msi" in manufacturer:
        result["url"] = f"https://www.msi.com/Motherboard/{urllib.parse.quote(product)}/support"
    if "gigabyte" in manufacturer:
        result["url"] = "https://www.gigabyte.com/Support"
    return result


def _motherboard_url(manufacturer: str, product: str) -> str:
    m = manufacturer.lower()
    q = urllib.parse.quote(f"{manufacturer} {product} BIOS")
    if "asus" in m:
        return f"https://www.asus.com/support/download-center/"
    if "msi" in m:
        return "https://www.msi.com/support/download"
    if "gigabyte" in m:
        return "https://www.gigabyte.com/Support"
    return f"https://www.google.com/search?q={q}"


def _check_asus_bios(product: str, current: str, result: dict[str, Any]) -> dict[str, Any]:
    model = product.replace(" ", "-")
    url = (
        "https://www.asus.com/support/api/product.asmx/GetPDBIOS?"
        f"CPU=Intel&Model={urllib.parse.quote(model)}&SLanguage=EN"
    )
    try:
        data = _fetch_json(url)
        obj = data.get("Result") or data.get("Obj") or data
        if isinstance(obj, dict):
            obj = obj.get("Obj") or obj
        if isinstance(obj, list) and obj:
            latest_entry = obj[0]
            latest_ver = str(latest_entry.get("Version") or latest_entry.get("VersionNum") or "")
            result["latest"] = latest_ver or None
            result["release_date"] = latest_entry.get("ReleaseDate")
            if latest_ver and current:
                cur_norm = re.sub(r"[^0-9.a-zA-Z]", "", current).upper()
                lat_norm = re.sub(r"[^0-9.a-zA-Z]", "", latest_ver).upper()
                result["update_available"] = lat_norm != cur_norm and lat_norm > cur_norm
            result["url"] = f"https://www.asus.com/motherboards/support-only/{urllib.parse.quote(model)}/helpdesk_bios/"
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return result


def check_motherboard_drivers(motherboard: dict[str, Any]) -> str:
    manufacturer = (motherboard.get("manufacturer") or "").lower()
    product = urllib.parse.quote(motherboard.get("product") or "")
    if "asus" in manufacturer:
        return f"https://www.asus.com/support/download-center/"
    if "msi" in manufacturer:
        return "https://www.msi.com/support/download"
    if "gigabyte" in manufacturer:
        return "https://www.gigabyte.com/Support"
    return f"https://www.google.com/search?q={urllib.parse.quote(manufacturer + ' ' + product + ' drivers')}"
