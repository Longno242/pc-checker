"""Live CPU/GPU/disk telemetry."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore


@dataclass
class LiveStats:
    cpu_percent: float | None = None
    cpu_freq_mhz: float | None = None
    cpu_temp_c: float | None = None
    gpu_name: str | None = None
    gpu_load_pct: float | None = None
    gpu_temp_c: float | None = None
    gpu_vram_used_mb: float | None = None
    gpu_vram_total_mb: float | None = None
    gpu_clock_mhz: float | None = None
    ram_used_gb: float | None = None
    ram_total_gb: float | None = None
    disk_read_mb_s: float | None = None
    disk_write_mb_s: float | None = None
    disks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class LiveMonitor:
    _last_disk_io: tuple[int, int, float] | None = None

    def sample(self) -> LiveStats:
        stats = LiveStats()
        if psutil:
            self._sample_psutil(stats)
        self._sample_nvidia(stats)
        self._sample_disk_smart(stats)
        return stats

    @staticmethod
    def _sample_psutil(stats: LiveStats) -> None:
        assert psutil is not None
        try:
            stats.cpu_percent = psutil.cpu_percent(interval=0.2)
            freq = psutil.cpu_freq()
            if freq:
                stats.cpu_freq_mhz = freq.current
            mem = psutil.virtual_memory()
            stats.ram_total_gb = round(mem.total / (1024**3), 2)
            stats.ram_used_gb = round(mem.used / (1024**3), 2)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures() or {}
                for key in ("coretemp", "cpu-thermal", "acpitz"):
                    if key in temps and temps[key]:
                        stats.cpu_temp_c = temps[key][0].current
                        break
            io1 = psutil.disk_io_counters()
            now = time.time()
            if io1 and LiveMonitor._last_disk_io:
                prev_r, prev_w, prev_t = LiveMonitor._last_disk_io
                dt = max(now - prev_t, 0.001)
                stats.disk_read_mb_s = round((io1.read_bytes - prev_r) / dt / (1024**2), 2)
                stats.disk_write_mb_s = round((io1.write_bytes - prev_w) / dt / (1024**2), 2)
            if io1:
                LiveMonitor._last_disk_io = (io1.read_bytes, io1.write_bytes, now)
        except Exception as exc:
            stats.errors.append(f"psutil: {exc}")

    @staticmethod
    def _sample_nvidia(stats: LiveStats) -> None:
        try:
            proc = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,clocks.gr",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return
            parts = [p.strip() for p in proc.stdout.strip().splitlines()[0].split(",")]
            if len(parts) >= 6:
                stats.gpu_name = parts[0]
                stats.gpu_load_pct = float(parts[1])
                stats.gpu_temp_c = float(parts[2])
                stats.gpu_vram_used_mb = float(parts[3])
                stats.gpu_vram_total_mb = float(parts[4])
                stats.gpu_clock_mhz = float(parts[5])
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass

    @staticmethod
    def _sample_disk_smart(stats: LiveStats) -> None:
        if not psutil:
            return
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    stats.disks.append(
                        {
                            "mount": part.mountpoint,
                            "used_percent": usage.percent,
                            "free_gb": round(usage.free / (1024**3), 2),
                        }
                    )
                except PermissionError:
                    continue
        except Exception:
            pass
