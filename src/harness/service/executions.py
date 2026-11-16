# src/harness/service/executions.py — executions + pause/resume/cancel/redirect (M7, 04 §5.4)
"""Create wraps orchestrator.create_execution with the default legal pipeline
(factory.legal_plan) when no plan_block/workflow_id is given (plan §0.2: the
API never blocks — 202 + execution row, the existing runner claims it).
pause/resume/cancel/redirect are thin state writes + SSE events (plan §1):
claim() already skips non-executing executions, so cancel takes effect at the
next claim; redirect rewrites a pending task's instruction."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from harness.service import authz
from harness.session import factory
from harness.workflow import audit, orchestrator

DISPATCH = "matter.dispatch"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exec_dict(con, r) -> dict:
    d = dict(r)
    try:
        d["plan"] = json.loads(d.pop("compiled_plan_json") or "[]")
    except ValueError:
        d["plan"] = []
    d["tasks"] = [dict(t) for t in con.execute(
        "SELECT * FROM tasks WHERE execution_id=? ORDER BY seq",
        (d["execution_id"],)).fetchall()]
    return d


def _require_exec(con, principal, execution_id, perm) -> dict:
    row = con.execute("SELECT * FROM executions WHERE execution_id=?",
                      (execution_id,)).fetchone()
    if row is None:
        raise authz.not_found("execution_not_found",
                              f"execution {execution_id!r} not found")
    authz.require(con, principal, perm, row["matter_id"])
    return dict(row)


def create(con, principal: dict, matter_id: str, body: dict) -> dict:
    authz.require(con, principal, DISPATCH, matter_id)
    task_text = (body or {}).get("task_text") or ""
    if not task_text:
        raise authz.ServiceError(422, "validation_failed", "task_text required")
    plan_block = (body or {}).get("plan_block") or ""
    workflow_id = (body or {}).get("workflow_id")
    parsed = factory.parse_plan(plan_block) if plan_block else None
    if parsed:
        stages = parsed.stages
    elif workflow_id:
        row = con.execute("SELECT definition_json FROM workflows WHERE workflow_id=?",
                          (workflow_id,)).fetchone()
        if row is None:
            raise authz.not_found("workflow_not_found",
                                  f"workflow {workflow_id!r} not found")
        stages = json.loads(row["definition_json"])
    else:
        # fallback_plan routes a /mock-hearing | /hearing-pack goal to its workflow file
        stages = factory.fallback_plan("", "LOW", task_text).stages
    # the session id keys the agent workspaces: one per execution, so no two runs
    # (and never two matters) share a workspace tree or its from-* hand-forwards
    eid = f"exec-{uuid.uuid4().hex[:12]}"
    orchestrator.create_execution(
        con, matter_id, session_id=f"api-{principal['username']}-{eid}",
        task_text=task_text, stages=stages, execution_id=eid)
    return get(con, principal, eid)


def get(con, principal: dict, execution_id: str) -> dict:
    row = _require_exec(con, principal, execution_id, authz.READ)
    return _exec_dict(con, row)


def tasks(con, principal: dict, execution_id: str) -> list[dict]:
    row = _require_exec(con, principal, execution_id, authz.READ)
    return [dict(t) for t in con.execute(
        "SELECT * FROM tasks WHERE execution_id=? ORDER BY seq",
        (row["execution_id"],)).fetchall()]


def _set_state(con, principal, execution_id, to: str, *, note: str = "",
               task_id: str | None = None, instruction: str | None = None) -> dict:
    row = _require_exec(con, principal, execution_id, DISPATCH)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE executions SET state=?, ended_at=? WHERE execution_id=?",
                    (to, _now() if to == "cancelled" else row["ended_at"], execution_id))
        if task_id is not None and instruction is not None:
            cur = con.execute(
                "UPDATE tasks SET instruction=? WHERE task_id=? AND execution_id=?"
                " AND state='pending'", (instruction, task_id, execution_id))
            if cur.rowcount != 1:
                con.execute("ROLLBACK")
                raise authz.ServiceError(409, "lease_conflict",
                                         f"task {task_id!r} is not pending")
        audit.emit(con, row["matter_id"], "execution.state_changed",
                   {"execution_id": execution_id, "to": to, "note": note[:200],
                    "task_id": task_id, "actor": principal["username"]})
        audit.append(con, matter_id=row["matter_id"], actor=principal["username"],
                     action=f"execution.{to}", target=execution_id,
                     inputs_digest=note[:200])
        con.execute("COMMIT")
    except authz.ServiceError:
        raise
    except Exception:
        con.execute("ROLLBACK")
        raise
    return get(con, principal, execution_id)


def pause(con, principal: dict, execution_id: str) -> dict:
    # only a running execution pauses: pausing a run parked at an approval and resuming it
    # would set it executing and the worker would run past the pending approval
    row = _require_exec(con, principal, execution_id, DISPATCH)
    if row["state"] != "executing":
        raise authz.ServiceError(409, "invalid_transition",
                                 f"pause needs state executing, got {row['state']!r}")
    return _set_state(con, principal, execution_id, "paused")


def resume(con, principal: dict, execution_id: str) -> dict:
    row = _require_exec(con, principal, execution_id, DISPATCH)
    if row["state"] != "paused":
        raise authz.ServiceError(409, "invalid_transition",
                                 f"resume needs state paused, got {row['state']!r}")
    return _set_state(con, principal, execution_id, "executing")


def cancel(con, principal: dict, execution_id: str, body: dict) -> dict:
    return _set_state(con, principal, execution_id, "cancelled",
                      note=(body or {}).get("reason") or "")


def redirect(con, principal: dict, execution_id: str, body: dict) -> dict:
    task_id = (body or {}).get("task_id")
    instruction = (body or {}).get("instruction")
    if not task_id or not instruction:
        raise authz.ServiceError(422, "validation_failed",
                                 "task_id and instruction required")
    # keeps the run's state: forcing "executing" would unpark a run waiting on an approval
    row = _require_exec(con, principal, execution_id, DISPATCH)
    return _set_state(con, principal, execution_id, row["state"],
                      task_id=task_id, instruction=instruction)
