# src/harness/module_e/skills.py
from __future__ import annotations
import re
from pathlib import Path
import yaml

_NAME = re.compile(r"^[a-z0-9-]+$")

def normalise_skill_md(raw: str, dir_name: str) -> str:
    """Normalise frontmatter to what opencode 1.18.25's skill loader requires: `name` matching
    the directory (lowercase alphanumeric + hyphens) and a description long enough for the model
    to trigger on. The real corpus writes descriptions as YAML block scalars (`description: >`
    with indented continuations), so the description is VALIDATED via yaml.safe_load — a
    line-split would measure the literal `>`. The description text is never rewritten; only a
    missing `name:` is inserted and CRLF is normalised to LF (these are normalised documents,
    not byte-parity artifacts)."""
    if not _NAME.match(dir_name):
        raise ValueError(f"{dir_name}: directory name is not a valid skill name")
    raw = raw.replace("\r\n", "\n")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{dir_name}: no frontmatter block")
    fm = yaml.safe_load(parts[1])
    if not isinstance(fm, dict):
        raise ValueError(f"{dir_name}: frontmatter is not a mapping")
    desc = str(fm.get("description", "")).strip()
    if len(desc) < 20:
        raise ValueError(f"{dir_name}: description too short to trigger on ({len(desc)}c)")
    fm_name = fm.get("name")
    if fm_name is not None and str(fm_name).strip() != dir_name:
        raise ValueError(f"{dir_name}: frontmatter name {fm_name!r} disagrees with the directory")
    lines, seen_name = parts[1].splitlines(), False
    for i, line in enumerate(lines):
        if line.strip().startswith("name:"):
            lines[i] = f"name: {dir_name}"
            seen_name = True
            break
    if not seen_name:
        lines.insert(0, f"name: {dir_name}")
    return "---" + "\n".join(lines) + "\n---" + parts[2]

def sync_skills(src: Path, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for d in sorted(p for p in src.iterdir() if p.is_dir()):
        # newline="" both ways: the read must not translate the source's line endings and the
        # write must not re-translate them to CRLF on Windows (normalise already handled LF).
        raw = (d / "SKILL.md").read_text(encoding="utf-8", newline="")
        target = out / d.name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(normalise_skill_md(raw, d.name), encoding="utf-8", newline="")
        written.append(target)
    return written
