from __future__ import annotations

import customtkinter as ctk

from src.gui.theme import ACCENT, ACCENT_HOVER, CARD, CARD_BORDER, MUTED, TEXT
from src.scanner.updates import UpdateItem
from src.utils.formatters import severity_color, severity_label


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title: str, value: str = "-", subtitle: str = "", **kwargs):
        super().__init__(master, fg_color=CARD, corner_radius=12, border_width=1, border_color=CARD_BORDER, **kwargs)
        ctk.CTkLabel(
            self, text=title.upper(), font=ctk.CTkFont(size=11, weight="bold"), text_color=MUTED,
        ).pack(anchor="w", padx=16, pady=(14, 4))
        self.value_label = ctk.CTkLabel(self, text=value, font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT)
        self.value_label.pack(anchor="w", padx=16)
        self.sub_label = ctk.CTkLabel(
            self, text=subtitle, font=ctk.CTkFont(size=12), text_color=MUTED, wraplength=280,
        )
        self.sub_label.pack(anchor="w", padx=16, pady=(2, 14))

    def set(self, value: str, subtitle: str = "", value_color: str | None = None) -> None:
        self.value_label.configure(text=value)
        if value_color:
            self.value_label.configure(text_color=value_color)
        if subtitle:
            self.sub_label.configure(text=subtitle)


class DetailPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

    def clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    def add_section(self, title: str) -> None:
        ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=15, weight="bold"), text_color=ACCENT,
        ).pack(anchor="w", pady=(16, 8))

    def add_row(self, label: str, value: str) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(
            row, text=label, font=ctk.CTkFont(size=13), text_color=MUTED, width=180, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            row, text=value, font=ctk.CTkFont(size=13), text_color=TEXT, anchor="w", wraplength=520,
        ).pack(side="left", fill="x", expand=True)


class UpdateCard(ctk.CTkFrame):
    def __init__(self, master, item: UpdateItem, open_url, **kwargs):
        super().__init__(master, fg_color=CARD, corner_radius=10, border_width=1, border_color=CARD_BORDER, **kwargs)
        badge_color = severity_color(item.severity)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            header,
            text=f"  {severity_label(item.severity)}  ",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=badge_color,
            corner_radius=6,
            text_color="#ffffff",
        ).pack(side="left")
        ctk.CTkLabel(header, text=item.category, font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left", padx=10)
        ctk.CTkLabel(
            self, text=item.title, font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT,
            wraplength=640, anchor="w", justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 4))
        if item.description:
            ctk.CTkLabel(
                self, text=item.description, font=ctk.CTkFont(size=12), text_color=MUTED,
                wraplength=640, anchor="w", justify="left",
            ).pack(anchor="w", padx=14, pady=(0, 4))

        meta: list[str] = []
        if item.current_version:
            meta.append(f"Installed: {item.current_version}")
        if item.available_version:
            meta.append(f"Available: {item.available_version}")
        if item.size_mb:
            meta.append(f"Size: {item.size_mb:.1f} MB")
        if meta:
            ctk.CTkLabel(self, text=" | ".join(meta), font=ctk.CTkFont(size=11), text_color=MUTED).pack(
                anchor="w", padx=14, pady=(0, 4),
            )
        if item.action:
            ctk.CTkLabel(
                self, text=item.action, font=ctk.CTkFont(size=12), text_color=ACCENT_HOVER,
                wraplength=640, anchor="w",
            ).pack(anchor="w", padx=14, pady=(0, 6))
        if item.action_url:
            actions = ctk.CTkFrame(self, fg_color="transparent")
            actions.pack(anchor="w", padx=14, pady=(0, 12))
            ctk.CTkButton(
                actions,
                text=item.action_label or "Open",
                width=140,
                height=28,
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
                command=lambda url=item.action_url: open_url(url),
            ).pack(side="left")
