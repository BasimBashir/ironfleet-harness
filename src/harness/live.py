# src/harness/live.py — the live agent/LLM activity log (one JSONL file per matter)
"""Every agent turn's opencode events (step, text, tool call in/out, reasoning) and
every gate LLM call (provider, model, ms, tokens, output, thinking, tool calls) land
as one JSON line in <store>/live/<matter>.jsonl the moment they happen. The API
tails the file as SSE (GET /matters/{mid}/live); trace.db stays the usage ledger.

Writers share one process (the API server runs the live worker and its gate), so a
module lock keeps lines whole. `current` names the agent a matter's turn is running:
the orchestrator runs one turn per matter at a time, so the gate attributes an LLM
call to it the same way TraceStore.attr() does after the turn."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
current: dict[str, dict] = {}          # matter_ref -> {"agent", "session_id", "model"}


def path(root: Path, matter_ref: str) -> Path:
    """The matter's log file. matter_ref becomes a file name, so anything outside
    [A-Za-z0-9._-] is replaced and dot-only names are refused (no path escape)."""
    name = _UNSAFE.sub("_", matter_ref or "")
    if not name.strip("."):
        raise ValueError(f"unusable matter ref for a live log: {matter_ref!r}")
    return Path(root) / "live" / f"{name}.jsonl"


def append(root: Path, matter_ref: str, kind: str, **fields) -> None:
    """One record. Never raises: a full disk or a bad ref must not kill a turn."""
    try:
        p = path(root, matter_ref)
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind,
               **current.get(matter_ref, {}), **fields}
        line = json.dumps(rec, ensure_ascii=False, default=str) + "\n"
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)   # store/live may be gone mid-run
            with open(p, "a", encoding="utf-8", newline="") as f:
                f.write(line)
    except Exception:                                      # noqa: BLE001
        pass


def agent_line(root: Path, matter_ref: str):
    """on_line callback for run_opencode: each JSON stdout line is one agent event."""
    def on_line(line: str) -> None:
        line = line.strip()
        if not line.startswith("{"):
            return
        try:
            ev = json.loads(line)
        except ValueError:
            return
        append(root, matter_ref, "agent", event=ev)
    return on_line


# shortcut: a first connect replays only the last REPLAY_BYTES of the log; older lines stay
# in the file (read it directly) — raise it if lawyers need a whole long run in the browser.
REPLAY_BYTES = 4 * 1024 * 1024


def read_from(root: Path, matter_ref: str, offset: int | None) -> tuple[list[tuple[int, dict]], int]:
    """Records after byte `offset` as (end_offset, record) pairs, plus the new offset.
    None = first connect: replay the tail. A missing file reads as nothing yet; a file
    shorter than the offset (deleted and re-created) restarts from 0. A trailing
    partial line (a write in progress) is left for the next read."""
    p = path(root, matter_ref)
    try:
        size = p.stat().st_size
    except OSError:
        return [], offset or 0
    if offset is None:
        offset = max(0, size - REPLAY_BYTES)
        skip_partial = offset > 0
    else:
        skip_partial = False
        if offset > size:
            offset = 0
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read()
    if skip_partial:
        nl = data.find(b"\n")
        if nl < 0:
            return [], offset
        offset, data = offset + nl + 1, data[nl + 1:]
    out: list[tuple[int, dict]] = []
    pos = offset
    for raw in data.splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        pos += len(raw)
        try:
            out.append((pos, json.loads(raw)))
        except ValueError:
            continue
    return out, pos
