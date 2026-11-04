# src/harness/module_e/guard.py
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

def guard_dir(ws: Path) -> Path:
    """The harness-owned authority directory for a workspace (M1/S4): allowed.json,
    guard-log.jsonl and passages.json live OUTSIDE the workspace — the agent under
    guard cannot edit the rules that judge it, or its own event log."""
    return ws.parent / ".ironfleet-guard" / ws.name

def render_guard_plugin(template: str, ws: Path, python: str, guard_cli: str,
                        whitelist: set[str]) -> str:
    # BRACKETED array literal — load-bearing. JS's Set constructor takes ONE iterable:
    # `new Set("a", "b")` silently iterates only "a" (a string -> its characters), so an
    # unbracketed comma list renders a set that matches NOTHING and annotation is inert
    # (Task 5 review C1, found under Node). The brackets make the payload a real array.
    wl = "[" + ", ".join(f'"{t}"' for t in sorted(whitelist | _ALWAYS_ANNOTATE)) + "]"
    gd = str(guard_dir(ws)).replace("\\", "/")
    return (template.replace("__SPIKE_WS__", str(ws).replace("\\", "/"))
                    .replace("__PYTHON__", str(python).replace("\\", "/"))
                    .replace("__GUARD_CLI__", str(guard_cli).replace("\\", "/"))
                    .replace("__GUARD_DIR__", gd)
                    .replace("__ANNOTATE__", wl))
