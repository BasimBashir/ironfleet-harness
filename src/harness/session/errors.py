# src/harness/session/errors.py
"""The session layer's error log: every caught exception lands here, once, with
WHERE it happened and WHY.

Why this exists: a TUI that swallows an exception is a TUI that silently stops
working — `except Exception: pass` exists twice in tui.py today and cost real
debugging time on this project. The rule: nothing in the session layer catches an
exception without recording it, so a future failure is located from the log
(where / exception / message / cause / raising line) instead of from guesswork.

Format: one JSON object per line under the store root (errors.jsonl), same
convention as the session JSONL and guard-log.jsonl — tail/grep-able, nothing to
migrate. The module deliberately keeps ONE function: a TUI needs a place to
record a caught error, not a logging framework.
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

FILENAME = "errors.jsonl"


def record_error(exc: BaseException, *, where: str, root: Path | None = None,
                 context: dict | None = None) -> None:
    """Append one failure. `where` is "module.function" — the answer to where it
    happened; the chained __cause__ answers why, and the innermost frame answers
    which line. Never raises: logging must not turn a caught error into a crash."""
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "where": where,
        "exception": type(exc).__name__,
        "message": str(exc),
        "cause": f"{type(exc.__cause__).__name__}: {exc.__cause__}" if exc.__cause__ else None,
        "line": traceback.format_tb(exc.__traceback__)[-1].strip() if exc.__traceback__ else "",
        "context": context or {},
    }
    try:
        if root is not None:
            path = Path(root) / FILENAME
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            # Library call before a store root exists: stderr beats silence, and
            # the row shape is identical, just not persisted.
            print(f"[session-error] {json.dumps(row, ensure_ascii=False)}", file=sys.stderr)
    except Exception:                                          # noqa: BLE001
        pass  # a logging failure must never mask the original error


def read_errors(root: Path, limit: int = 50) -> list[dict]:
    """The log, oldest first. A torn line loses ONE row, never the file."""
    path = Path(root) / FILENAME
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]
