# src/harness/crashlog.py — M11 T4: local crash capture, no telemetry (02 §15).
"""When a long-running surface (the launcher, the API serve) dies, the evidence
stays on the operator's machine: one UTF-8 log per crash under
`<store-root>/crash/`, carrying the traceback, the harness version and the
store-root provenance `source`. Never sent anywhere — there is no sender in
this codebase, and the no-telemetry drift test keeps it that way. The
directory is trimmed to the last KEEP logs so a crash loop cannot fill the
disk."""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import harness

KEEP = 20


def capture(store_root, component: str, exc: BaseException | None = None,
            source: str = "") -> Path:
    """Write one crash log; return its path. Never raises (a crash handler
    that throws is worse than no log)."""
    try:
        d = Path(store_root) / "crash"
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc)
        p = d / f"{ts.strftime('%Y%m%d-%H%M%S')}-{component}.log"
        lines = [
            f"harness {harness.__version__}",
            f"ts: {ts.isoformat()}",
            f"component: {component}",
            f"store: {store_root}" + (f" (source: {source})" if source else ""),
            "",
        ]
        for tb in traceback.format_exception(exc or sys.exc_info()[1] or
                                             RuntimeError("no exception recorded")):
            lines.append(tb)
        p.write_text("\n".join(lines), encoding="utf-8")
        # a crash loop (many writes inside one clock tick) ties on mtime and name
        # order lies (c10 < c4), so the only honest trim: the log just written
        # always survives, and at most KEEP files remain — which others go is not
        # a contract.
        others = [q for q in d.glob("*.log") if q != p]
        others.sort(key=lambda q: q.stat().st_mtime_ns)
        for old in others[:-(KEEP - 1)]:
            old.unlink(missing_ok=True)
        return p
    except Exception:
        return Path(store_root) / "crash"  # best effort; never mask the crash


def run_guarded(store_root, component: str, fn, *args, source: str = "", **kwargs):
    """fn() on success; on Exception, capture the log then re-raise — the
    caller owns the exit code, the log is the durable record."""
    try:
        return fn(*args, **kwargs)
    except Exception as ex:
        capture(store_root, component, ex, source=source)
        raise
