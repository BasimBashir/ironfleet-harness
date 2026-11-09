# src/harness/service/usage.py — token usage per matter + per agent (M8)
"""The workspace's token meters (D-3 pick: C's meters on B; 05 §13: the TUI's
meter "now via the API"). Reads <store>/trace.db dispatches read-only — the rows
the gate writes and session/tokens.py aggregates; keyed by matter_ref (= the
platform matter_id on the durable path) and the F1 agent column."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harness.service import authz

_ZERO = {"in": 0, "out": 0, "cache": 0, "thinking": 0, "all": 0, "dispatches": 0}


def _trace_db(con) -> Path:
    # platform.db sits at the store root, beside trace.db
    main = next(r for r in con.execute("PRAGMA database_list") if r[1] == "main")
    return Path(main[2]).parent / "trace.db"


def _row(r) -> dict:
    d = {"in": r[1] or 0, "out": r[2] or 0, "cache": r[3] or 0, "thinking": r[4] or 0,
         "dispatches": r[5]}
    d["all"] = d["in"] + d["out"]          # cache reads are not new tokens
    return d


def matter_tokens(con, matter_id: str) -> dict:
    path = _trace_db(con)
    if not path.is_file():
        return {"total": dict(_ZERO), "agents": []}
    t = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = t.execute(
            "SELECT agent, SUM(tokens_in), SUM(tokens_out), SUM(tokens_cache),"
            " SUM(tokens_reasoning), COUNT(*) FROM dispatches WHERE matter_ref=?"
            " GROUP BY agent ORDER BY agent", (matter_id,)).fetchall()
    finally:
        t.close()
    agents = [{"agent": r[0] or "(unattributed)", **_row(r)} for r in rows]
    total = dict(_ZERO)
    for a in agents:
        for k in total:
            total[k] += a[k]
    return {"total": total, "agents": agents}


def get(con, principal: dict, matter_id: str) -> dict:
    authz.require(con, principal, authz.READ, matter_id)
    return matter_tokens(con, matter_id)
