"""PC Checker desktop application."""

from __future__ import annotations

import os
import threading
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from src.export.report import export_html_report
from src.gui.serialization import hardware_from_dict, updates_from_dict
from src.gui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BACKGROUND,
    CARD,
    CARD_BORDER,
    DANGER,
    MUTED,
    SUCCESS,
    TEXT,
    WARNING,
    health_color,
)
from src.gui.widgets import DetailPanel, StatCard, UpdateCard
from src.scanner.hardware import HardwareScanner, ScanResult
from src.scanner.health import HealthResult, calculate_health
from src.scanner.monitoring import LiveMonitor
from src.scanner.updates import ScanControl, UpdateScanResult, UpdateScanner
from src.storage.persistence import AppSettings, ScanPersistence
from src.utils.formatters import fmt_gb, fmt_mhz, safe_str

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def open_url(url: str | None) -> None:
    if not url:
        return
    if url.startswith("ms-settings:"):
        os.startfile(url)  # type: ignore[attr-defined]
    else:
        webbrowser.open(url)


class PCCheckerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PC Checker")
        self.geometry("1220x820")
        self.minsize(980, 660)
        self.configure(fg_color=BACKGROUND)

        self.hw_scanner = HardwareScanner()
        self.update_scanner = UpdateScanner()
        self.persistence = ScanPersistence()
        self.settings = AppSettings.load()
        self.live_monitor = LiveMonitor()
        self.scan_control = ScanControl()

        self.hardware: ScanResult | None = None
        self.updates: UpdateScanResult | None = None
        self.health: HealthResult | None = None
        self.scanning = False
        self.monitor_job: str | None = None
        self.bios_url = ""

        self._build_layout()
        self._load_cached_scan()
        if self.settings.auto_scan_on_open:
            self.after(600, self.start_scan)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        self._build_header()
        self._build_tabs()
        self._start_live_monitor()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_block = ctk.CTkFrame(header, fg_color="transparent")
        title_block.pack(side="left", padx=24, pady=14)
        ctk.CTkLabel(title_block, text="PC Checker", font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(
            title_block,
            text="Hardware inventory, update status, and system health for Windows",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).pack(anchor="w")

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.pack(side="right", padx=16, pady=12)

        for text, width, color, command in (
            ("Export", 80, CARD_BORDER, self.export_report),
            ("History", 80, CARD_BORDER, self.show_history),
            ("Settings", 90, CARD_BORDER, self.show_settings),
            ("Cancel", 80, DANGER, self.cancel_scan),
            ("Skip WU", 80, CARD_BORDER, self.skip_windows_update),
        ):
            state = "disabled" if text in {"Cancel", "Skip WU"} else "normal"
            btn = ctk.CTkButton(controls, text=text, width=width, fg_color=color, hover_color=ACCENT, command=command, state=state)
            btn.pack(side="right", padx=4)
            if text == "Cancel":
                self.cancel_btn = btn
            elif text == "Skip WU":
                self.skip_wu_btn = btn
            elif text == "Export":
                self.export_btn = btn

        self.scan_btn = ctk.CTkButton(
            controls,
            text="Scan System",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            width=140,
            height=40,
            command=self.start_scan,
        )
        self.scan_btn.pack(side="right", padx=(8, 0))
        self.progress = ctk.CTkProgressBar(controls, width=180, progress_color=ACCENT)
        self.progress.pack(side="right", padx=(0, 8))
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(controls, text="Ready", font=ctk.CTkFont(size=12), text_color=MUTED, width=200)
        self.status_label.pack(side="right")

    def _build_tabs(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(12, 20))
        self.tabs = ctk.CTkTabview(body, fg_color=CARD, segmented_button_fg_color=BACKGROUND, segmented_button_selected_color=ACCENT)
        self.tabs.pack(fill="both", expand=True)

        tab_names = ("Overview", "Live", "CPU", "GPU", "Memory", "Storage", "Displays", "System", "Updates")
        for name in tab_names:
            setattr(self, f"tab_{name.lower()}", self.tabs.add(name))

        health_row = ctk.CTkFrame(self.tab_overview, fg_color="transparent")
        health_row.pack(fill="x", pady=(8, 8))
        self.card_health = StatCard(health_row, "System Health", "-", "Run a scan to calculate health score")
        self.card_health.pack(side="left", fill="x", expand=True, padx=6)

        self.cards_primary = self._card_grid(self.tab_overview)
        self.card_cpu, self.card_ram, self.card_gpu, self.card_os = self.cards_primary
        self.cards_secondary = self._card_grid(self.tab_overview, pady=(0, 8))
        self.card_storage, self.card_bios, self.card_updates, self.card_monitors = self.cards_secondary
        self.overview_detail = DetailPanel(self.tab_overview)
        self.overview_detail.pack(fill="both", expand=True)

        self.panel_live = DetailPanel(self.tab_live)
        self.panel_live.pack(fill="both", expand=True, padx=8, pady=8)
        self.panel_cpu = DetailPanel(self.tab_cpu)
        self.panel_cpu.pack(fill="both", expand=True, padx=8, pady=8)
        self.panel_gpu = DetailPanel(self.tab_gpu)
        self.panel_gpu.pack(fill="both", expand=True, padx=8, pady=8)
        self.panel_memory = DetailPanel(self.tab_memory)
        self.panel_memory.pack(fill="both", expand=True, padx=8, pady=8)
        self.panel_storage = DetailPanel(self.tab_storage)
        self.panel_storage.pack(fill="both", expand=True, padx=8, pady=8)
        self.panel_displays = DetailPanel(self.tab_displays)
        self.panel_displays.pack(fill="both", expand=True, padx=8, pady=8)
        self.panel_system = DetailPanel(self.tab_system)
        self.panel_system.pack(fill="both", expand=True, padx=8, pady=8)

        updates_header = ctk.CTkFrame(self.tab_updates, fg_color="transparent")
        updates_header.pack(fill="x", padx=8, pady=(8, 0))
        self.updates_summary = ctk.CTkLabel(
            updates_header, text="Run a scan to check for updates.", font=ctk.CTkFont(size=13), text_color=MUTED, anchor="w",
        )
        self.updates_summary.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            updates_header, text="Open BIOS page", fg_color=CARD_BORDER, hover_color=ACCENT, command=lambda: open_url(self.bios_url),
        ).pack(side="right")
        self.updates_scroll = ctk.CTkScrollableFrame(self.tab_updates, fg_color="transparent")
        self.updates_scroll.pack(fill="both", expand=True, padx=8, pady=8)

    def _card_grid(self, parent, pady=(8, 16)) -> tuple[StatCard, StatCard, StatCard, StatCard]:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=pady)
        for column in range(4):
            frame.grid_columnconfigure(column, weight=1)
        titles = ("Processor", "Memory", "Graphics", "Operating System") if pady[0] == 8 else ("Storage", "BIOS / Firmware", "Update Status", "Displays")
        cards = tuple(StatCard(frame, title) for title in titles)
        for index, card in enumerate(cards):
            card.grid(row=0, column=index, padx=6, pady=6, sticky="nsew")
        return cards

    def _start_live_monitor(self) -> None:
        self._refresh_live_stats()

    def _refresh_live_stats(self) -> None:
        stats = self.live_monitor.sample()
        self.panel_live.clear()
        self.panel_live.add_section("System")
        self.panel_live.add_row("CPU usage", f"{stats.cpu_percent:.0f}%" if stats.cpu_percent is not None else "-")
        self.panel_live.add_row("CPU frequency", fmt_mhz(stats.cpu_freq_mhz))
        self.panel_live.add_row("CPU temperature", f"{stats.cpu_temp_c:.0f} C" if stats.cpu_temp_c else "-")
        self.panel_live.add_row("RAM used", f"{stats.ram_used_gb}/{stats.ram_total_gb} GB" if stats.ram_used_gb else "-")
        if stats.gpu_name:
            self.panel_live.add_section("GPU")
            self.panel_live.add_row("Name", safe_str(stats.gpu_name))
            self.panel_live.add_row("Load", f"{stats.gpu_load_pct:.0f}%" if stats.gpu_load_pct is not None else "-")
            self.panel_live.add_row("Temperature", f"{stats.gpu_temp_c:.0f} C" if stats.gpu_temp_c is not None else "-")
            if stats.gpu_vram_used_mb and stats.gpu_vram_total_mb:
                self.panel_live.add_row("VRAM", f"{int(stats.gpu_vram_used_mb)} / {int(stats.gpu_vram_total_mb)} MB")
            self.panel_live.add_row("Clock", fmt_mhz(stats.gpu_clock_mhz))
        if stats.disk_read_mb_s is not None:
            self.panel_live.add_section("Disk I/O")
            self.panel_live.add_row("Read", f"{stats.disk_read_mb_s:.1f} MB/s")
            self.panel_live.add_row("Write", f"{stats.disk_write_mb_s:.1f} MB/s")
        for disk in stats.disks:
            self.panel_live.add_row(disk.get("mount", "Disk"), f"{disk.get('used_percent', 0):.0f}% used")
        self.monitor_job = self.after(2000, self._refresh_live_stats)

    def _on_close(self) -> None:
        if self.monitor_job:
            self.after_cancel(self.monitor_job)
        self.destroy()

    def set_status(self, message: str, progress: float | None = None) -> None:
        self.status_label.configure(text=message[:80])
        if progress is not None:
            self.progress.set(max(0.0, min(1.0, progress)))

    def cancel_scan(self) -> None:
        self.scan_control.cancel.set()
        self.set_status("Cancelling scan")

    def skip_windows_update(self) -> None:
        self.scan_control.skip_windows_update.set()
        self.set_status("Skipping Windows Update")

    def start_scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.scan_control = ScanControl()
        if self.settings.skip_windows_update:
            self.scan_control.skip_windows_update.set()
        self.scan_btn.configure(state="disabled", text="Scanning")
        self.cancel_btn.configure(state="normal")
        self.skip_wu_btn.configure(state="normal")
        self.set_status("Initializing", 0.02)

        def worker() -> None:
            try:
                hardware = self.hw_scanner.scan(
                    progress_callback=lambda msg, p: self.after(0, lambda m=msg, v=p: self.set_status(m, v * 0.45)),
                )
                if self.scan_control.cancelled():
                    return
                self.hardware = hardware
                self.after(0, lambda: self.render_hardware(hardware))

                updates = self.update_scanner.scan(
                    hardware=hardware,
                    progress_callback=lambda msg, p: self.after(0, lambda m=msg, v=p: self.set_status(m, 0.45 + v * 0.55)),
                    on_partial=lambda partial: self.after(0, lambda data=partial: self.render_updates(data, partial=True)),
                    control=self.scan_control,
                    skip_windows_update=self.settings.skip_windows_update,
                )
                if self.scan_control.cancelled():
                    return

                health = calculate_health(hardware, updates)
                updates.health = {
                    "score": health.score,
                    "grade": health.grade,
                    "issues": health.issues,
                    "breakdown": health.breakdown,
                }
                self.updates = updates
                self.health = health
                self.persistence.save_scan(hardware, updates, updates.health)
                self.after(0, lambda: self.render_updates(updates))
                self.after(0, lambda: self.render_health(health))
                self.after(0, lambda: self.set_status("Scan complete", 1.0))
            except Exception as exc:
                self.after(0, lambda: self.set_status(f"Error: {exc}", 0))
            finally:
                self.after(0, self._finish_scan)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_scan(self) -> None:
        self.scanning = False
        self.scan_btn.configure(state="normal", text="Scan System")
        self.cancel_btn.configure(state="disabled")
        self.skip_wu_btn.configure(state="disabled")

    def render_health(self, health: HealthResult) -> None:
        self.health = health
        self.card_health.set(
            f"{health.score}/100",
            health.grade,
            value_color=health_color(health.score),
        )
        if health.issues:
            self.card_health.sub_label.configure(text=health.issues[0])

    def _load_cached_scan(self) -> None:
        cached = self.persistence.load_last_scan()
        if not cached:
            self._show_welcome()
            return
        hardware = hardware_from_dict(cached.get("hardware") or {})
        updates = updates_from_dict(cached.get("updates") or {})
        self.hardware = hardware
        self.updates = updates
        self.render_hardware(hardware)
        self.render_updates(updates)
        health_data = cached.get("health") or updates.health
        if health_data:
            self.render_health(
                HealthResult(
                    score=int(health_data.get("score", 0)),
                    grade=str(health_data.get("grade", "")),
                    issues=list(health_data.get("issues") or []),
                    breakdown=dict(health_data.get("breakdown") or {}),
                )
            )
        saved_at = str(cached.get("saved_at", ""))[:16]
        self.set_status(f"Loaded cached scan ({saved_at})", 1.0)

    def _show_welcome(self) -> None:
        self.overview_detail.clear()
        self.overview_detail.add_section("Getting started")
        self.overview_detail.add_row("Scan", "Select Scan System to collect hardware and update data.")
        self.overview_detail.add_row("Settings", "Configure auto-scan and Windows Update behavior under Settings.")

    def render_hardware(self, hardware: ScanResult) -> None:
        cpu = hardware.cpu
        memory = hardware.memory
        os_info = hardware.os_info
        bios = hardware.bios
        gpu = hardware.gpus[0] if hardware.gpus else {}

        cpu_name = safe_str(cpu.get("name"), "Unknown CPU")
        self.card_cpu.set(
            cpu_name[:36] + ("..." if len(cpu_name) > 36 else ""),
            f"{cpu.get('cores', '?')} cores, {cpu.get('logicalProcessors', '?')} threads",
        )
        self.card_ram.set(fmt_gb(memory.get("totalGB")), f"{memory.get('slotsUsed', '?')} modules")
        gpu_name = safe_str(gpu.get("name"), "No GPU detected")
        vram = gpu.get("vramMB")
        self.card_gpu.set(gpu_name[:36], f"{int(vram)} MB VRAM" if vram else safe_str(gpu.get("driverVersion")))
        self.card_os.set(safe_str(os_info.get("caption"), "Windows"), f"Build {safe_str(os_info.get('build'))}")

        drives = [entry for entry in hardware.storage if entry.get("model")]
        total_gb = sum(float(entry.get("sizeGB", 0)) for entry in drives)
        self.card_storage.set(fmt_gb(total_gb), f"{len(drives)} drive(s)")
        self.card_bios.set(safe_str(bios.get("version") or bios.get("name"))[:28], safe_str(bios.get("manufacturer")))
        self.card_monitors.set(str(len(hardware.monitors)), "connected display(s)")

        self._render_cpu_tab(cpu)
        self._render_gpu_tab(hardware.gpus)
        self._render_memory_tab(memory)
        self._render_storage_tab(hardware.storage)
        self._render_displays_tab(hardware.monitors)
        self._render_system_tab(hardware)

        self.overview_detail.clear()
        self.overview_detail.add_section("Summary")
        self.overview_detail.add_row("System", f"{safe_str(hardware.system.get('manufacturer'))} {safe_str(hardware.system.get('model'))}")
        self.overview_detail.add_row("CPU", cpu_name)
        self.overview_detail.add_row("GPU", gpu_name)
        self.overview_detail.add_row("BIOS", f"{safe_str(bios.get('version'))} ({safe_str(bios.get('releaseDate'))})")

    def render_updates(self, updates: UpdateScanResult, partial: bool = False) -> None:
        if not updates.summary:
            updates.summary = {level: 0 for level in ("critical", "recommended", "optional", "info")}
            for item in updates.items:
                key = item.severity if item.severity in updates.summary else "info"
                updates.summary[key] += 1

        if partial:
            self.card_updates.set("Scanning", "Partial results available")
            summary = "Driver and BIOS checks complete. Windows Update still running."
        else:
            critical = updates.summary.get("critical", 0)
            recommended = updates.summary.get("recommended", 0)
            if critical:
                label, color = f"{critical} critical", DANGER
            elif recommended:
                label, color = f"{recommended} recommended", WARNING
            else:
                label, color = "Up to date", SUCCESS
            self.card_updates.set(label, "See Updates tab", value_color=color)
            summary = (
                f"Scanned {updates.scanned_at}. "
                f"{updates.summary.get('critical', 0)} critical, {updates.summary.get('recommended', 0)} recommended."
            )
            if updates.errors:
                summary += " Some checks reported warnings."

        self.updates_summary.configure(text=summary)
        self.bios_url = (
            (updates.bios_advisory or {}).get("support_url")
            or (updates.version_checks.get("bios") or {}).get("url")
            or ""
        )

        for child in self.updates_scroll.winfo_children():
            child.destroy()
        if not updates.items:
            message = "Waiting for Windows Update" if partial else "No update items found."
            ctk.CTkLabel(self.updates_scroll, text=message, text_color=MUTED).pack(pady=20)
            return

        order = {"critical": 0, "recommended": 1, "optional": 2, "info": 3}
        for item in sorted(updates.items, key=lambda entry: order.get(entry.severity, 9)):
            UpdateCard(self.updates_scroll, item, open_url).pack(fill="x", pady=6)

    def _render_cpu_tab(self, cpu: dict[str, Any]) -> None:
        self.panel_cpu.clear()
        self.panel_cpu.add_section("Processor")
        fields = (
            ("Name", "name"), ("Cores", "cores"), ("Threads", "logicalProcessors"),
            ("Max clock", "maxClockMHz"), ("Current clock", "currentClockMHz"), ("Socket", "socket"),
        )
        for label, key in fields:
            value = cpu.get(key)
            if key.endswith("MHz") and value:
                value = fmt_mhz(value)
            self.panel_cpu.add_row(label, safe_str(value))

    def _render_gpu_tab(self, gpus: list[dict[str, Any]]) -> None:
        self.panel_gpu.clear()
        for index, gpu in enumerate(gpus or [], start=1):
            self.panel_gpu.add_section(f"GPU {index}")
            for label, key in (
                ("Name", "name"), ("Driver", "driverVersion"), ("NVIDIA driver", "nvidiaDriver"),
                ("Driver date", "driverDate"), ("VRAM", "vramMB"), ("Temperature", "temperatureC"),
                ("Resolution", "currentResolution"),
            ):
                value = gpu.get(key)
                if key == "vramMB" and value:
                    value = f"{int(float(value))} MB"
                elif key == "temperatureC" and value is not None:
                    value = f"{value} C"
                if value is not None:
                    self.panel_gpu.add_row(label, safe_str(value))

    def _render_memory_tab(self, memory: dict[str, Any]) -> None:
        self.panel_memory.clear()
        self.panel_memory.add_section("Summary")
        self.panel_memory.add_row("Total", fmt_gb(memory.get("totalGB")))
        self.panel_memory.add_row("Speed", fmt_mhz(memory.get("maxSpeedMHz")))
        for index, module in enumerate(memory.get("modules") or [], start=1):
            self.panel_memory.add_section(f"Module {index}")
            self.panel_memory.add_row("Slot", safe_str(module.get("deviceLocator")))
            self.panel_memory.add_row("Capacity", fmt_gb(module.get("capacityGB")))

    def _render_storage_tab(self, storage: list[dict[str, Any]]) -> None:
        self.panel_storage.clear()
        logical_volumes: list[dict[str, Any]] = []
        for block in storage:
            if block.get("logicalVolumes"):
                logical_volumes = block["logicalVolumes"]
        for disk in [entry for entry in storage if entry.get("model")]:
            self.panel_storage.add_section(safe_str(disk.get("model")))
            self.panel_storage.add_row("Capacity", fmt_gb(disk.get("sizeGB")))
            self.panel_storage.add_row("Interface", safe_str(disk.get("interfaceType")))
            self.panel_storage.add_row("Health", safe_str(disk.get("healthStatus")))
            if disk.get("temperatureC") is not None:
                self.panel_storage.add_row("Temperature", f"{disk.get('temperatureC')} C")
            if disk.get("wearPercent") is not None:
                self.panel_storage.add_row("Wear", f"{disk.get('wearPercent')}%")
        if logical_volumes:
            self.panel_storage.add_section("Volumes")
            for volume in logical_volumes:
                self.panel_storage.add_row(
                    safe_str(volume.get("deviceId")),
                    f"{fmt_gb(volume.get('freeGB'))} free, {volume.get('usedPercent', 0)}% used",
                )

    def _render_displays_tab(self, monitors: list[dict[str, Any]]) -> None:
        self.panel_displays.clear()
        for index, monitor in enumerate(monitors or [], start=1):
            self.panel_displays.add_section(f"Display {index}")
            self.panel_displays.add_row("Name", safe_str(monitor.get("name")))
            self.panel_displays.add_row("Resolution", safe_str(monitor.get("resolution")))
            self.panel_displays.add_row("Refresh rate", f"{monitor.get('refreshHz')} Hz" if monitor.get("refreshHz") else "-")
            self.panel_displays.add_row("HDR", "Yes" if monitor.get("hdr") else "No" if "hdr" in monitor else "-")
            self.panel_displays.add_row("Connection", safe_str(monitor.get("connection")))

    def _render_system_tab(self, hardware: ScanResult) -> None:
        self.panel_system.clear()
        self.panel_system.add_section("Operating system")
        for label, key in (("OS", "caption"), ("Build", "build"), ("Last boot", "lastBoot")):
            self.panel_system.add_row(label, safe_str(hardware.os_info.get(key)))
        self.panel_system.add_section("Motherboard")
        for label, key in (("Manufacturer", "manufacturer"), ("Model", "product"), ("Version", "version")):
            self.panel_system.add_row(label, safe_str(hardware.motherboard.get(key)))
        self.panel_system.add_section("BIOS")
        for label, key in (("Version", "version"), ("Release date", "releaseDate"), ("Manufacturer", "manufacturer")):
            self.panel_system.add_row(label, safe_str(hardware.bios.get(key)))

    def export_report(self) -> None:
        if not self.hardware or not self.updates:
            messagebox.showinfo("Export", "Run a scan before exporting a report.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML report", "*.html")],
            initialfile=f"pc_checker_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
        )
        if not path:
            return
        export_html_report(self.hardware, self.updates, self.updates.health, path)
        messagebox.showinfo("Export", f"Report saved to:\n{path}")
        os.startfile(path)  # type: ignore[attr-defined]

    def show_history(self) -> None:
        entries = self.persistence.list_history()
        if not entries:
            messagebox.showinfo("History", "No saved scans found.")
            return

        window = ctk.CTkToplevel(self)
        window.title("Scan history")
        window.geometry("420x320")
        window.configure(fg_color=BACKGROUND)
        ctk.CTkLabel(window, text="Recent scans", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=12)
        scroll = ctk.CTkScrollableFrame(window, fg_color=CARD)
        scroll.pack(fill="both", expand=True, padx=16, pady=8)

        def load_entry(entry: dict[str, Any]) -> None:
            payload = ScanPersistence.load_history_file(entry["path"])
            if not payload:
                return
            self.hardware = hardware_from_dict(payload.get("hardware") or {})
            self.updates = updates_from_dict(payload.get("updates") or {})
            self.render_hardware(self.hardware)
            self.render_updates(self.updates)
            health_data = payload.get("health") or {}
            if health_data:
                self.render_health(
                    HealthResult(
                        score=int(health_data.get("score", 0)),
                        grade=str(health_data.get("grade", "")),
                        issues=list(health_data.get("issues") or []),
                    )
                )
            window.destroy()

        for entry in entries:
            label = entry.get("saved_at", "Unknown")
            score = entry.get("health_score")
            if score is not None:
                label = f"{label}  (health {score}/100)"
            ctk.CTkButton(scroll, text=label, anchor="w", fg_color=CARD_BORDER, hover_color=ACCENT, command=lambda e=entry: load_entry(e)).pack(fill="x", pady=4)

    def show_settings(self) -> None:
        window = ctk.CTkToplevel(self)
        window.title("Settings")
        window.geometry("420x220")
        window.configure(fg_color=BACKGROUND)
        ctk.CTkLabel(window, text="Settings", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=16)
        auto_scan = ctk.BooleanVar(value=self.settings.auto_scan_on_open)
        skip_wu = ctk.BooleanVar(value=self.settings.skip_windows_update)
        ctk.CTkCheckBox(window, text="Scan automatically when the application opens", variable=auto_scan).pack(anchor="w", padx=24, pady=8)
        ctk.CTkCheckBox(window, text="Skip Windows Update during scans", variable=skip_wu).pack(anchor="w", padx=24, pady=8)

        def save() -> None:
            self.settings.auto_scan_on_open = auto_scan.get()
            self.settings.skip_windows_update = skip_wu.get()
            self.settings.save()
            window.destroy()

        ctk.CTkButton(window, text="Save", fg_color=ACCENT, command=save).pack(pady=16)


def run_app() -> None:
    PCCheckerApp().mainloop()
