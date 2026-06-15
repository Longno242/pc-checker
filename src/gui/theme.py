ACCENT = "#6366f1"
ACCENT_HOVER = "#818cf8"
BACKGROUND = "#0f1117"
CARD = "#1a1d27"
CARD_BORDER = "#2a2f3f"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
SUCCESS = "#22c55e"
WARNING = "#f59e0b"
DANGER = "#ef4444"


def health_color(score: int) -> str:
    if score >= 90:
        return SUCCESS
    if score >= 75:
        return ACCENT_HOVER
    if score >= 60:
        return WARNING
    return DANGER
