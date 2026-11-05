# src/harness/service/personas.py — /persona new as a plain function (M3).
"""Appends the validated row to personas.yaml; the mount regen rides the next
sync_mount. Moved from tui.py's _persona_new; ValueError on a bad row is the
caller's (the TUI records and echoes it)."""
from __future__ import annotations

from pathlib import Path

import yaml

from harness.session.commands import build_persona_row, parse_persona_new

PERSONAS_YAML = Path(__file__).resolve().parents[3] / "data" / "module-e" / "personas.yaml"


def add_persona(args: str, path: Path = PERSONAS_YAML) -> str:
    """/persona new's one-line form: name|description|tools|prompt.
    Returns the new persona's name; raises ValueError on a bad row (nothing
    is written in that case)."""
    name, desc, allowed, prompt = parse_persona_new(args)
    row = build_persona_row(name, desc, allowed, prompt)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["personas"].append(row)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return name
