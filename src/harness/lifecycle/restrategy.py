# src/harness/lifecycle/restrategy.py — re-strategy versioning (M5).
# cut_strategy appends strategy v(max+1); a re-strategy must name what the court
# decided that the previous version got wrong (non-empty why_changed).
from __future__ import annotations

from harness.lifecycle import dossier, statemachine

_REPLAN_STATES = {"RE_STRATEGY", "AWAIT", "RESPOND"}


def cut_strategy(con, matter: str, file: str, why_changed: str,
                 next_actions=None, *, actor: str = "strategist") -> dict:
    """Cut strategy version N+1. Requires the case to be in RE_STRATEGY (the
    debrief's landing state) or AWAIT/RESPOND (an out-of-court re-plan)."""
    if not why_changed or not str(why_changed).strip():
        raise RuntimeError("cut_strategy needs a non-empty why_changed — name what "
                           "the court decided that the previous version got wrong")
    cur = statemachine.state(con, matter)
    if cur not in _REPLAN_STATES:
        raise RuntimeError(f"cannot cut a strategy from state {cur!r} "
                           f"(needs one of {sorted(_REPLAN_STATES)})")
    read = dossier.read(con, matter, "strategy")
    version = (read["versions"][-1] + 1) if read["versions"] else 1
    row = dossier.append(con, matter, "strategy",
                         {"version": version, "file": file, "why_changed": why_changed,
                          "next_actions": list(next_actions or [])},
                         actor=actor)
    return row
