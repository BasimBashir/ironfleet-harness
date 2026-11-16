# src/harness/service/usage.py — token usage per matter + per agent (M8)
"""The workspace's token meters (D-3 pick: C's meters on B; 05 §13: the TUI's
meter "now via the API"). Reads <store>/trace.db dispatches read-only — the rows
the gate writes and session/tokens.py aggregates; keyed by matter_ref (= the
platform matter_id on the durable path) and the F1 agent column."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from harness.service import authz

_ZERO = {"in": 0, "out": 0, "cache": 0, "thinking": 0, "all": 0, "dispatches": 0, "ms": 0}


def _trace_db(con) -> Path:
    # platform.db sits at the store root, beside trace.db
    main = next(r for r in con.execute("PRAGMA database_list") if r[1] == "main")
    return Path(main[2]).parent / "trace.db"


def _row(r) -> dict:
    d = {"in": r[1] or 0, "out": r[2] or 0, "cache": r[3] or 0, "thinking": r[4] or 0,
         "dispatches": r[5], "ms": r[6] or 0}
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
            " SUM(tokens_reasoning), COUNT(*), SUM(latency_ms) FROM dispatches WHERE matter_ref=?"
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


def _sums(rows) -> dict:
    """calls, errors, tokens, ms over (status, in, out, reasoning, cache, ms) rows."""
    d = {"calls": 0, "errors": 0, "in": 0, "out": 0, "thinking": 0, "cache": 0, "ms": 0}
    for st, tin, tout, tr, tc, ms in rows:
        d["calls"] += 1
        d["errors"] += st == "error"
        d["in"] += tin or 0
        d["out"] += tout or 0
        d["thinking"] += tr or 0
        d["cache"] += tc or 0
        d["ms"] += ms or 0
    d["all"] = d["in"] + d["out"]
    return d


def account_usage(con, principal: dict) -> dict:
    """Totals per provider/model (each LLM account) and per IronFleet user (the
    matter's creator owns its calls); refused calls are counted, never dropped."""
    authz.require(con, principal, "audit.read")
    rows = _dispatches(con, "SELECT provider, model, matter_ref, status, tokens_in, tokens_out,"
                            " tokens_reasoning, tokens_cache, latency_ms FROM dispatches")
    owner = {m: u for m, u in con.execute(
        "SELECT m.matter_id, COALESCE(u.username, m.created_by) FROM matters m"
        " LEFT JOIN users u ON u.user_id = m.created_by").fetchall()}
    by_model: dict[tuple, list] = {}
    by_user: dict[str, list] = {}
    for prov, model, mref, *vals in rows:
        by_model.setdefault((prov or "-", model or "-"), []).append(vals)
        by_user.setdefault(owner.get(mref) or "(no matter)", []).append(vals)
    return {
        "total": _sums(v for vs in by_model.values() for v in vs),
        "by_model": [{"provider": p, "model": m, **_sums(vs)}
                     for (p, m), vs in sorted(by_model.items())],
        "by_user": [{"user": u, **_sums(vs)} for u, vs in sorted(by_user.items())],
    }


def _dispatches(con, sql: str) -> list:
    path = _trace_db(con)
    if not path.is_file():
        return []
    t = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return t.execute(sql).fetchall()
    finally:
        t.close()


def trace_errors(con) -> int:
    rows = _dispatches(con, "SELECT COUNT(*) FROM dispatches WHERE status='error'")
    return rows[0][0] if rows else 0


def _rank(xs: list[int], p: float) -> int:
    """Nearest-rank percentile over a sorted list."""
    return xs[max(0, math.ceil(len(xs) * p) - 1)] if xs else 0


def metrics(con, principal: dict) -> dict:
    """02 §14: derived queries over trace.db + the workflow tables — no metrics stack."""
    authz.require(con, principal, "audit.read")
    rows = _dispatches(con, "SELECT provider, model, engine, status, latency_ms"
                            " FROM dispatches ORDER BY provider, model, latency_ms")
    by_engine: dict[str, int] = {}
    lat: dict[tuple, list[int]] = {}
    for prov, model, engine, _, ms in rows:
        by_engine[engine or ""] = by_engine.get(engine or "", 0) + 1
        lat.setdefault((prov, model), []).append(ms or 0)
    tasks = dict(con.execute("SELECT state, COUNT(*) FROM tasks GROUP BY state").fetchall())
    return {
        "dispatches": {"total": len(rows), "errors": sum(r[3] == "error" for r in rows),
                       "by_engine": by_engine},
        "latency": [{"provider": p, "model": m, "n": len(xs), "p50_ms": _rank(xs, .5),
                     "p95_ms": _rank(xs, .95)} for (p, m), xs in lat.items()],
        "tasks": {"pending": tasks.get("pending", 0), "running": tasks.get("running", 0)},
        "executions": dict(con.execute("SELECT state, COUNT(*) FROM executions"
                                       " GROUP BY state").fetchall()),
    }
