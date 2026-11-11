# src/harness/lifecycle/statemachine.py — NEXT_STEPS §3.1 as data (M5, doc 07 §2).
# The `cases` row is created lazily on first transition; every transition is
# refused loudly when illegal and audit-logged when taken, in one transaction.
from __future__ import annotations

from datetime import datetime, timezone

from harness.workflow import audit

STATES = [
    "INTAKE", "ASSESS", "STRATEGY", "PRE_ACTION", "DRAFT", "MOOT", "APPROVE",
    "FILE_SERVE", "AWAIT", "RESPOND", "HEARING_PREP", "COURT", "DEBRIEF",
    "RE_STRATEGY", "JUDGMENT", "ENFORCE", "APPEAL", "SETTLE", "CLOSED",
]

# The §3.1 chain order, plus settlement/discontinuance (SETTLE) from any state
# at or after PRE_ACTION, and CLOSED from the terminal legal outcomes.
_CHAIN = STATES[:STATES.index("SETTLE")]  # up to and including APPEAL
_SETTLE_FROM = set(_CHAIN[_CHAIN.index("PRE_ACTION"):])
_CLOSED_FROM = {"JUDGMENT", "ENFORCE", "APPEAL", "SETTLE"}

TRANSITIONS: dict[str, set[str]] = {s: set() for s in STATES}
for a, b in zip(_CHAIN, _CHAIN[1:]):
    TRANSITIONS[a].add(b)
for s in _SETTLE_FROM:
    TRANSITIONS[s].add("SETTLE")
for s in _CLOSED_FROM:
    TRANSITIONS[s].add("CLOSED")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state(con, matter: str) -> str | None:
    """The current §3.1 state, or None when the matter has no case row yet."""
    row = con.execute("SELECT state FROM cases WHERE matter_id=?", (matter,)).fetchone()
    return row["state"] if row else None


def transition(con, matter: str, to: str, *, actor: str = "operator",
               note: str = "") -> str:
    """Move the case to `to` if legal; refuse loudly otherwise (no write).
    Settlement branches from any state >= PRE_ACTION per §3.1."""
    if to not in TRANSITIONS:
        raise RuntimeError(f"unknown state {to!r} (one of: {', '.join(STATES)})")
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT state FROM cases WHERE matter_id=?",
                          (matter,)).fetchone()
        cur = row["state"] if row else None
        # a row with state NULL (lawyer_now.evaluate creates one) is still stateless
        if cur is None:
            if to != STATES[0]:
                con.execute("ROLLBACK")
                raise RuntimeError(
                    f"case {matter!r} has no state yet — first transition must be "
                    f"{STATES[0]!r}, got {to!r}")
            now = _now()
            if row is None:
                con.execute("INSERT INTO cases(matter_id, state, lawyer_now, "
                            "lawyer_now_reason, needs_restrategy, created_at, updated_at)"
                            " VALUES(?,?,0,'[]',0,?,?)", (matter, to, now, now))
            else:
                con.execute("UPDATE cases SET state=?, updated_at=? WHERE matter_id=?",
                            (to, now, matter))
        else:
            if to not in TRANSITIONS.get(cur, set()):
                con.execute("ROLLBACK")
                raise RuntimeError(
                    f"illegal transition {cur} -> {to} for {matter!r} "
                    f"(allowed: {', '.join(sorted(TRANSITIONS.get(cur, set()))) or 'none'})")
            con.execute("UPDATE cases SET state=?, updated_at=? WHERE matter_id=?",
                        (to, _now(), matter))
        audit.append(con, matter_id=matter, actor=actor, action="state.transition",
                     target=to,
                     inputs_digest=f"{cur}->{to}" + (f" {note}" if note else ""))
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    return to


# pipeline stage key -> the §3.1 state its completion evidences (moot completes
# only once its filing approval is granted, hence APPROVE)
_STAGE_STATE = {"intake": "INTAKE", "assess": "ASSESS", "strategy": "STRATEGY",
                "filings": "DRAFT", "moot": "APPROVE"}


def advance_after_run(con, execution_id: str, *, actor: str = "workflow") -> str | None:
    """A completed execution walks its matter forward along the chain, one legal
    step at a time, to the furthest state its stages evidence. Never backwards,
    never off-chain (SETTLE/CLOSED stay put); returns the resulting state."""
    ex = con.execute("SELECT matter_id, state, started_at FROM executions"
                     " WHERE execution_id=?", (execution_id,)).fetchone()
    if not ex or ex["state"] != "completed":
        return None
    # someone else moved the case while this run was in flight: they are driving
    # the lifecycle, so the run's evidence must not overrule them
    if con.execute("SELECT 1 FROM audit_events WHERE matter_id=? AND action="
                   "'state.transition' AND actor<>? AND ts>?",
                   (ex["matter_id"], actor, ex["started_at"] or "")).fetchone():
        return state(con, ex["matter_id"])
    keys = [r["key"] for r in con.execute(
        "SELECT key FROM tasks WHERE execution_id=? AND state='completed'", (execution_id,))]
    targets = [STATES.index(_STAGE_STATE[k]) for k in keys if k in _STAGE_STATE]
    cur = state(con, ex["matter_id"])
    if not targets or (cur and cur not in _CHAIN):
        return cur
    i = _CHAIN.index(cur) if cur else -1
    for s in _CHAIN[i + 1:max(targets) + 1]:
        transition(con, ex["matter_id"], s, actor=actor, note=f"run {execution_id}")
    return state(con, ex["matter_id"])
