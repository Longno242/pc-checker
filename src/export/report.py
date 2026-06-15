"""HTML report export."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any


def export_html_report(
    hardware: Any,
    updates: Any,
    health: dict[str, Any] | None,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    hw = hardware
    upd = updates
    h = health or {}
    score = h.get("score", "—")
    grade = h.get("grade", "—")
    issues = h.get("issues") or []

    def esc(val: Any) -> str:
        return html.escape(str(val if val is not None else "—"))

    rows = []
    if hw:
        rows.append(("CPU", esc((hw.cpu or {}).get("name"))))
        rows.append(("GPU", esc((hw.gpus[0] if hw.gpus else {}).get("name"))))
        rows.append(("RAM", esc((hw.memory or {}).get("totalGB")) + " GB"))
        rows.append(("BIOS", esc((hw.bios or {}).get("version"))))
        rows.append(("OS", esc((hw.os_info or {}).get("caption"))))

    update_rows = ""
    for item in getattr(upd, "items", []) or []:
        update_rows += (
            f"<tr><td>{esc(getattr(item, 'severity', ''))}</td>"
            f"<td>{esc(getattr(item, 'title', ''))}</td>"
            f"<td>{esc(getattr(item, 'description', ''))}</td></tr>"
        )

    issue_list = "".join(f"<li>{esc(i)}</li>" for i in issues)

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>PC Checker Report — {esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</title>
<style>
body {{ font-family: Segoe UI, sans-serif; background:#0f1117; color:#e2e8f0; margin:2rem; }}
.card {{ background:#1a1d27; border:1px solid #2a2f3f; border-radius:12px; padding:1.25rem; margin-bottom:1rem; }}
h1,h2 {{ color:#818cf8; }}
.score {{ font-size:2.5rem; font-weight:bold; }}
table {{ width:100%; border-collapse:collapse; }}
td,th {{ border-bottom:1px solid #2a2f3f; padding:8px; text-align:left; vertical-align:top; }}
.muted {{ color:#94a3b8; }}
</style>
</head>
<body>
<h1>PC Checker Report</h1>
<p class="muted">Generated {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</p>

<div class="card">
<h2>Health Score</h2>
<div class="score">{esc(score)}/100 — {esc(grade)}</div>
<ul>{issue_list}</ul>
</div>

<div class="card">
<h2>System Summary</h2>
<table>
{"".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k,v in rows)}
</table>
</div>

<div class="card">
<h2>Updates &amp; Advisories</h2>
<table>
<tr><th>Severity</th><th>Title</th><th>Details</th></tr>
{update_rows or "<tr><td colspan='3'>No items</td></tr>"}
</table>
</div>
</body>
</html>"""
    path.write_text(content, encoding="utf-8")
    return path
