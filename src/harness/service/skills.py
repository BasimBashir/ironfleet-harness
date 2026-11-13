# src/harness/service/skills.py — admin skill upload (M13.6)
"""One SKILL.md (frontmatter + markdown) per upload, validated by the same
normalise_skill_md the shipped skills go through. Markdown only — no zips or
scripts: executable content from an upload is a code-execution hole. Lands in
<store_root>/skills/<name>/SKILL.md, which every later mount syncs after the
shipped skills; a shipped skill's name cannot be taken."""
from __future__ import annotations

import re
from pathlib import Path

from harness.module_e.skills import normalise_skill_md
from harness.service import authz
from harness.workflow import audit

PERM = "user.admin"
_MAX = 256 * 1024


def upload(con, principal: dict, name: str, raw: bytes, *, store_root) -> dict:
    authz.require(con, principal, PERM)
    from harness.substrate.mount import MODULE_E

    def bad(msg):
        return authz.ServiceError(422, "validation_failed", msg)
    if not re.fullmatch(r"[a-z0-9-]+", name or ""):
        raise bad("name must be lowercase letters, digits and hyphens")
    if (MODULE_E / "skills" / name).exists():
        raise bad(f"{name}: a shipped skill already has this name")
    if len(raw) > _MAX:
        raise bad("SKILL.md is larger than 256 KB")
    try:
        text = normalise_skill_md(raw.decode("utf-8"), name)
    except UnicodeDecodeError:
        raise bad("SKILL.md must be UTF-8 text") from None
    except ValueError as e:
        raise bad(str(e)) from None
    target = Path(store_root) / "skills" / name / "SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="")
    con.execute("BEGIN IMMEDIATE")
    try:
        audit.append(con, matter_id="", actor=principal["username"], action="skill.uploaded",
                     target=name, inputs_digest=name)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"skill": name, "bytes": len(text.encode("utf-8"))}
