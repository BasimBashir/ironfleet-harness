# src/harness/service/sessions.py — the session use-cases as plain functions (M3).
"""Moved from tui.py: split_plan (the dispatch worker shares it), the run-2+
digest, the deliverables glob, and the chaired dispatch. `notify` exists
because "auto-compacting…" must be delivered BEFORE the long task runs —
returning it afterwards would change what the user sees."""
from __future__ import annotations

import re
from pathlib import Path

from harness.session.tokens import maybe_compact, window_for


def split_plan(text: str) -> tuple[str, str]:
    """A typed task may carry a ```plan fenced block — the factory's stage script
    (stage|agent|prompt per line), the same shape the acceptance driver feeds
    run_task. The block moves to plan_text verbatim; the rest stays the task.
    Pure so tests and the dispatch worker share one rule."""
    m = re.search(r"```plan\s*\n.*?```", text, re.S)
    if not m:
        return text, ""
    prose = (text[:m.start()] + text[m.end():]).strip()
    return (prose or "(run the plan)"), m.group(0)


def session_digest(store, base: Path, session_id: str) -> str:
    """Run-2+'s memory: the last checkpoint's summary (or the last two turn
    summaries) plus the deliverables already produced — seeded into stage 1
    so a follow-up prompt continues from the last checkpoint."""
    rows = store.turns(session_id) if session_id else []
    if not rows:
        return ""
    parts: list[str] = []
    checkpoints = [r for r in rows if (r.display or "").startswith("/compact")]
    if checkpoints:
        parts.append("Last checkpoint: " + (checkpoints[-1].output_summary or "")[:600])
    else:
        for r in rows[-2:]:
            if r.output_summary:
                parts.append(f"{r.agent} reported: {r.output_summary[:300]}")
    if base and session_id:
        names = [f"{f.parent.name}/{f.name}"
                 for f in (Path(base) / session_id).glob("*/*.md")
                 if ".opencode" not in f.parts]
        if names:
            parts.append("Files already produced: " + ", ".join(names[-12:]))
    return " | ".join(parts)[:2000]


def deliverables(base: Path, session_id: str) -> list[Path]:
    """Every doc an agent wrote under this session (one level deep), skipping
    .opencode — the TUI announces these once per file as clickable links."""
    return sorted(f for f in (Path(base) / session_id).glob("*/*.md")
                  if ".opencode" not in f.parts)


async def dispatch_task(runner, session_id: str, text: str, *,
                        used: int, window: int, provider_name: str,
                        notify=lambda msg: None):
    driver = getattr(runner, "driver", None)
    """The chaired dispatch: auto-compact gate, then the FULL crew at the
    corpus's best serving tier (a typed ```plan scripts the stages exactly; a
    plain goal gets the legal pipeline with the session digest seeded).
    Returns the factory's rows, or None when there is no session/driver."""
    if driver is None or not session_id:
        return None
    cp = await maybe_compact(driver, session_id, used=used, window=window,
                             safe_fill=window_for(provider_name)[1])
    if cp is not None:
        notify("auto-compacting…")
    matter_ref = driver.resume(session_id)["matter_ref"]
    task, plan_text = split_plan(text)
    rows = await runner.run_task(session_id, matter_ref, task,
                                 plan_text=plan_text,
                                 complexity="HIGH",
                                 classification="CLOUD_PERMITTED",
                                 session_digest=session_digest(
                                     driver.store, driver.base, session_id))
    return rows
