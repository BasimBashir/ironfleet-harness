# mcp/harness/module_e/export_calendar.py — M9: .ics deadline export.
# Hand-written iCalendar (no icalendar dep): one VEVENT per deadline row, written
# to a LOCAL file only — no cloud, no egress (D-P8). The path must resolve inside
# the matter workspace (or the given workspace root); ".." escapes are refused.
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from harness.lifecycle import dossier as _dossier


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _safe_path(path: str, base_dir: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        raise RuntimeError("export path must be absolute (local file only)")
    try:
        p.resolve().relative_to(Path(base_dir).resolve())
    except ValueError:
        raise RuntimeError(f"export path {path!r} escapes {base_dir} — refused")
    return p


def export_ics(con, matter: str, path: str, *, base_dir: str | Path) -> dict:
    """Write deadlines of `matter` as VEVENTs to the local file `path`.
    Platform variant: reads the SQL dossier; `base_dir` contains the path."""
    out_path = _safe_path(path, base_dir)
    rows = _dossier.read(con, matter, "deadlines")["deadlines"]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ironfleet-legal//M9//EN",
             "CALSCALE:GREGORIAN"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for i, r in enumerate(rows):
        due = str(r["due"]).replace("-", "")
        desc = _esc(f"{r.get('rule', '')} | {r.get('missed_consequence') or ''}".strip(" |"))
        lines += ["BEGIN:VEVENT",
                  f"UID:{matter}-{r.get('deadline_id', i)}-{due}@ironfleet",
                  f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{due}",
                  f"SUMMARY:{_esc(str(r.get('what', 'deadline')))}",
                  f"DESCRIPTION:{desc}",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return {"path": str(out_path), "events": len(rows)}
