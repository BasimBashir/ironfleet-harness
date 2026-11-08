# src/harness/workflow/approvals.py — the Approval rows + the park primitive
"""A stage carrying `approval: <kind>` parks AFTER it completes: the lawyer
approves the drafted output, not an empty intent. The park is an approval row
(pending) plus execution state waiting_human + current_wait_ref; claim()
already skips non-executing executions, so nothing downstream runs — across
restarts, for days."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from harness.workflow import audit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MootRequired(RuntimeError):
    """M6: a filing approval was requested without a PASSED moot.verdict record
    for the execution — nothing reaches approval without a moot record."""


def request(con, *, matter_id: str, execution_id: str, task_id: str, kind: str,
            payload: dict) -> str:
    """One transaction: approval row pending + audit event + execution parked.
    M6: kind='filing' refuses (MootRequired, no row written) unless the execution
    carries a PASSED moot.verdict audit record."""
    if kind == "filing":
        from harness.moot.gate import last_verdict
        v = last_verdict(con, matter_id, execution_id)
        if not v or v.get("verdict") != "PASSED":
            raise MootRequired(
                f"no PASSED moot record for execution {execution_id} — the moot "
                f"stage must run and pass before a filing approval can be requested")
    aid = f"apr-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "INSERT INTO approvals(approval_id, matter_id, execution_id, task_id,"
            " kind, request_payload_json, state, requested_at) VALUES(?,?,?,?,?,?,?,?)",
            (aid, matter_id, execution_id, task_id, kind,
             json.dumps(payload, sort_keys=True), "pending", _now()))
        audit.append(con, matter_id=matter_id, actor="orchestrator",
                     action="approval.requested", target=aid,
                     inputs_digest=json.dumps(payload, sort_keys=True)[:500])
        con.execute("UPDATE executions SET state='waiting_human', current_wait_ref=?"
                    " WHERE execution_id=?", (aid, execution_id))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return aid


def park_after_stage(con, *, matter_id: str, execution_id: str, task: dict) -> str | None:
    """Called by orchestrator.run after a stage completes; parks only when the
    stage declared an approval kind. Returns the approval id, or None."""
    kind = task.get("approval_kind")
    if not kind:
        return None
    return request(con, matter_id=matter_id, execution_id=execution_id,
                   task_id=task["task_id"], kind=kind,
                   payload={"stage": task["key"], "agent": task.get("agent_id", ""),
                            "result_summary": (task.get("result_summary") or "")[:500]})
