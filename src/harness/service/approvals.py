# src/harness/service/approvals.py — the Approval Center's backend (06 Phase 4)
"""Plain functions over platform.db, like the rest of service/ (M3): the TUI,
CLI or a future API all call these. decide() is ONE transaction — approval row
+ audit event + execution back to executing (approve) or cancelled (reject) —
and deciding an already-decided approval raises."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from harness.workflow import audit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pending(con, matter_id: str | None = None) -> list[dict]:
    """The Approval Center's list: every pending approval, newest first."""
    if matter_id is None:
        rows = con.execute(
            "SELECT * FROM approvals WHERE state='pending' ORDER BY requested_at DESC"
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM approvals WHERE state='pending' AND matter_id=?"
            " ORDER BY requested_at DESC", (matter_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["request_payload"] = json.loads(d.pop("request_payload_json") or "{}")
        except ValueError:
            d["request_payload"] = {}
        out.append(d)
    return out


def decide(con, approval_id: str, *, approve: bool, decided_by: str,
           note: str = "") -> None:
    """Approve -> the execution goes back to executing and run() picks up the
    rest; reject -> the execution is cancelled and nothing more runs."""
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute("SELECT * FROM approvals WHERE approval_id=?",
                          (approval_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown approval: {approval_id!r}")
        if row["state"] != "pending":
            raise ValueError(f"approval {approval_id} already {row['state']}")
        state = "approved" if approve else "rejected"
        con.execute(
            "UPDATE approvals SET state=?, decided_by=?, decision_note=?, decided_at=?"
            " WHERE approval_id=?", (state, decided_by, note, _now(), approval_id))
        audit.append(con, matter_id=row["matter_id"], actor=decided_by,
                     action="approval.decided", target=approval_id,
                     inputs_digest=state, outputs_digest=note[:500])
        exec_state = "executing" if approve else "cancelled"
        con.execute("UPDATE executions SET state=?, current_wait_ref='', ended_at=?"
                    " WHERE execution_id=?",
                    (exec_state, _now() if not approve else None, row["execution_id"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
