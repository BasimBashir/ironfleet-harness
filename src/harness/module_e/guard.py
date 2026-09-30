from __future__ import annotations
from pathlib import Path

# `task` carries a subagent's prose answer back to the primary — it is free text, not a
# structured envelope, so it is annotation-eligible even though it is a builtin.
_ALWAYS_ANNOTATE = {"task"}

def annotate_eligible(tool: str, whitelist: set[str]) -> bool:
    """May the guard MUTATE this tool's result text? Detection and blocking run regardless of
    this answer — only content mutation is gated, because that is what corrupts structured
    envelopes (M0 hazard 2). Fail-safe: an unknown tool is never rewritten."""
    return tool in _ALWAYS_ANNOTATE or tool in whitelist

def render_guard_plugin(template: str, ws: Path, python: str, guard_cli: str,
                        whitelist: set[str]) -> str:
    wl = ", ".join(f'"{t}"' for t in sorted(whitelist | _ALWAYS_ANNOTATE))
    return (template.replace("__SPIKE_WS__", str(ws).replace("\\", "/"))
                    .replace("__PYTHON__", str(python).replace("\\", "/"))
                    .replace("__GUARD_CLI__", str(guard_cli).replace("\\", "/"))
                    .replace("__ANNOTATE__", wl))
