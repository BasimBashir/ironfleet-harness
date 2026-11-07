# src/harness/workflow/orchestrator.py — the SQLite-lease orchestrator (D4)
"""Claims, leases, crash recovery and the derived matter state. Linear plans
only: a task is claimable when every lower-seq task in its execution is
completed. Halt-on-failure is the D3 ruling: a failed stage fails the
execution and leaves later tasks pending — no continue-on-failure here."""
from __future__ import annotations

import asyncio
import socket
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness.workflow.db import connect

DEFAULT_MAX_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def platform_db(store_root: Path) -> Path:
    """platform.db lives next to trace.db and sessions/ at the store root."""
    return Path(store_root) / "platform.db"


def create_execution(con, matter_id: str, session_id: str, task_text: str,
                     stages: list[dict], *, max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                     execution_id: str | None = None) -> str:
    """One execution row (state=executing) plus one pending task per stage."""
    import json
    eid = execution_id or f"exec-{uuid.uuid4().hex[:12]}"
    plan_json = json.dumps([{"stage": s["stage"], "agent": s["agent"],
                             "instruction": s["instruction"]} for s in stages])
    now = _now()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "INSERT INTO executions(execution_id, matter_id, session_id, state,"
            " compiled_plan_json, input_task_text, started_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (eid, matter_id, session_id, "executing", plan_json, task_text, now))
        for i, s in enumerate(stages, start=1):
            con.execute(
                "INSERT INTO tasks(task_id, execution_id, seq, key, agent_id,"
                " instruction, approval_kind, state, max_attempts)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (f"{eid}-t{i}", eid, i, s["stage"], s.get("agent", ""),
                 s.get("instruction", ""), s.get("approval"), "pending", max_attempts))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return eid


def claim(con, owner: str, *, lease_s: float = 120, now: float | None = None) -> dict | None:
    """Atomically take the lowest-seq claimable task. Claimable = in an
    executing execution, every earlier task completed, and the task itself is
    pending OR running with an expired lease (the crash case). A task past
    max_attempts is failed instead of re-run, so a stage that kills the
    process every time cannot crash-loop."""
    now = time.time() if now is None else now
    con.execute("BEGIN IMMEDIATE")
    try:
        row = con.execute(
            "SELECT t.* FROM tasks t JOIN executions e ON e.execution_id = t.execution_id"
            " WHERE e.state = 'executing'"
            "   AND (t.state = 'pending' OR (t.state = 'running' AND t.lease_expires_at <= ?))"
            "   AND NOT EXISTS (SELECT 1 FROM tasks p WHERE p.execution_id = t.execution_id"
            "                   AND p.seq < t.seq AND p.state != 'completed')"
            " ORDER BY t.execution_id, t.seq LIMIT 1", (now,)).fetchone()
        if row is None:
            con.execute("COMMIT")
            return None
        if row["attempts"] >= row["max_attempts"]:
            con.execute("UPDATE tasks SET state='failed' WHERE task_id=?", (row["task_id"],))
            con.execute("UPDATE executions SET state='failed', ended_at=?"
                        " WHERE execution_id=?", (_now(), row["execution_id"]))
            con.execute("COMMIT")
            return None
        con.execute(
            "UPDATE tasks SET state='running', lease_owner=?, lease_expires_at=?,"
            " attempts=attempts+1 WHERE task_id=?",
            (owner, now + lease_s, row["task_id"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return dict(con.execute("SELECT * FROM tasks WHERE task_id=?",
                            (row["task_id"],)).fetchone())


def heartbeat(con, task_id: str, owner: str, lease_s: float) -> bool:
    """Extend the lease only while `owner` still holds it — a thief cannot
    keep a stolen task alive."""
    cur = con.execute(
        "UPDATE tasks SET lease_expires_at=? WHERE task_id=? AND lease_owner=?"
        " AND state='running'", (time.time() + lease_s, task_id, owner))
    return cur.rowcount == 1


def complete(con, task_id: str, owner: str, *, result_summary: str = "") -> bool:
    """Mark the task completed, guarded on the lease owner. Returns False when
    a stale owner (lease stolen) tries to write — the new owner's result wins."""
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute(
            "UPDATE tasks SET state='completed', result_summary=?, lease_owner=''"
            " WHERE task_id=? AND lease_owner=?", (result_summary, task_id, owner))
        if cur.rowcount != 1:
            con.execute("ROLLBACK")
            return False
        _maybe_finish_execution(con)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return True


def fail(con, task_id: str, owner: str, *, error: str = "") -> bool:
    """D3 halt-on-failure: the task fails and its execution fails; later tasks
    stay pending and nothing else is claimable from that execution."""
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute(
            "UPDATE tasks SET state='failed', result_summary=?, lease_owner=''"
            " WHERE task_id=? AND lease_owner=?", (error[:500], task_id, owner))
        if cur.rowcount != 1:
            con.execute("ROLLBACK")
            return False
        row = con.execute("SELECT execution_id FROM tasks WHERE task_id=?",
                          (task_id,)).fetchone()
        con.execute("UPDATE executions SET state='failed', ended_at=?"
                    " WHERE execution_id=?", (_now(), row["execution_id"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return True


def _maybe_finish_execution(con) -> None:
    """When no task of an executing execution is left pending/running, the
    execution completes (inside the caller's transaction)."""
    row = con.execute(
        "SELECT e.execution_id FROM executions e WHERE e.state='executing' AND NOT EXISTS"
        " (SELECT 1 FROM tasks t WHERE t.execution_id=e.execution_id"
        "  AND t.state IN ('pending','running'))").fetchall()
    for r in row:
        con.execute("UPDATE executions SET state='completed', ended_at=?"
                    " WHERE execution_id=?", (_now(), r["execution_id"]))


def matter_state(con, matter_id: str) -> str:
    """Derived, never stored (02 §4): waiting_human -> waiting_on_you; else any
    executing -> running; else latest failed -> blocked; else latest completed
    -> review_required; no executions -> draft."""
    rows = con.execute(
        "SELECT state, started_at FROM executions WHERE matter_id=?"
        " ORDER BY started_at DESC", (matter_id,)).fetchall()
    if not rows:
        return "draft"
    states = {r["state"] for r in rows}
    if "waiting_human" in states:
        return "waiting_on_you"
    if "executing" in states:
        return "running"
    latest = rows[0]["state"]
    if latest == "failed":
        return "blocked"
    if latest == "completed":
        return "review_required"
    return "draft"


async def run(con, execution_id: str, body, *, owner: str | None = None,
              lease_s: float = 120) -> None:
    """Claim -> await body(task, prev_summary) -> complete, until nothing is
    claimable. `prev_summary` is the previous task's stored result_summary, so
    a resumed run hands forward exactly as an uninterrupted one. The lease is
    renewed every lease_s/4 while the body awaits, so a long turn is never
    stolen; a crash is reclaimable after lease_s. A body exception fails the
    task and halts (D3)."""
    owner = owner or new_owner()
    while True:
        task = claim(con, owner, lease_s=lease_s)
        if task is None:
            return
        prev = con.execute(
            "SELECT result_summary FROM tasks WHERE execution_id=? AND seq<?"
            " ORDER BY seq DESC LIMIT 1", (execution_id, task["seq"])).fetchone()
        prev_summary = prev["result_summary"] if prev and prev["result_summary"] else ""
        renew = asyncio.create_task(_renew_loop(con, task["task_id"], owner, lease_s))
        try:
            result = await body(task, prev_summary)
        except Exception as exc:                                   # noqa: BLE001
            fail(con, task["task_id"], owner, error=f"{type(exc).__name__}: {exc}")
            return
        finally:
            renew.cancel()
        complete(con, task["task_id"], owner,
                 result_summary=(result or "")[:2000])
        # an approval stage parks AFTER it completes: the human approves the
        # drafted output, and claim() skips non-executing executions from here on
        if task.get("approval_kind"):
            from harness.workflow import approvals as _approvals
            matter = con.execute("SELECT matter_id FROM executions WHERE execution_id=?",
                                 (execution_id,)).fetchone()
            _approvals.park_after_stage(con, matter_id=matter["matter_id"],
                                       execution_id=execution_id,
                                       task={**task, "result_summary": (result or "")[:2000]})
            return


async def _renew_loop(con, task_id: str, owner: str, lease_s: float) -> None:
    try:
        while True:
            await asyncio.sleep(max(lease_s / 4, 0.05))
            heartbeat(con, task_id, owner, lease_s)
    except asyncio.CancelledError:
        pass
