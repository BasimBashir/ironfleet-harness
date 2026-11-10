# src/harness/service/catalog.py — workflows/agents/approvals/requests/runs (M7)
"""Thin durable-row services for the 04 §5.4/§5.5/§5.6 surface (plan §1:
rows + contract tests, no engine). Approvals wrap service.approvals.decide,
which gains the principal + authz approval.decide. Requests are approvals rows
with kind=info_request (03 §2.17); answering un-parks like decide."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from harness.service import approvals as _approvals
from harness.service import authz
from harness.workflow import audit

WRITE = "matter.write"
DISPATCH = "matter.dispatch"
DECIDE = "approval.decide"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- workflows (04 §5.4) --------------------------------------------------------

def list_workflows(con, principal: dict) -> list[dict]:
    authz.require(con, principal, authz.READ)
    rows = con.execute("SELECT * FROM workflows ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["definition"] = json.loads(d.pop("definition_json") or "[]")
        except ValueError:
            d["definition"] = []
        out.append(d)
    return out


def create_workflow(con, principal: dict, body: dict) -> dict:
    authz.require(con, principal, WRITE)
    name = (body or {}).get("name") or ""
    definition = (body or {}).get("definition") or (body or {}).get("yaml") or []
    if not name or not isinstance(definition, list) or not definition or not all(
            isinstance(s, dict) and all(isinstance(s.get(k), str) and s.get(k)
                                        for k in ("stage", "agent", "instruction"))
            for s in definition):
        raise authz.ServiceError(422, "validation_failed",
                                 "name + definition[{stage, agent, instruction, "
                                 "approval?}] required")
    wid = f"wf-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO workflows(workflow_id, name, definition_json,"
                    " created_by, created_at) VALUES(?,?,?,?,?)",
                    (wid, name, json.dumps(definition), principal["user_id"], _now()))
        audit.append(con, matter_id="", actor=principal["username"],
                     action="workflow.created", target=wid, inputs_digest=name[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"workflow_id": wid, "name": name, "definition": definition,
            "created_by": principal["user_id"]}


# -- agents (04 §5.5) -----------------------------------------------------------

def list_agents(con, principal: dict) -> list[dict]:
    authz.require(con, principal, authz.READ)
    return [dict(r) for r in con.execute(
        "SELECT * FROM agents ORDER BY created_at").fetchall()]


def create_agent(con, principal: dict, body: dict) -> dict:
    authz.require(con, principal, WRITE)
    name = (body or {}).get("name") or ""
    if not name:
        raise authz.ServiceError(422, "validation_failed", "name required")
    aid = f"ag-{uuid.uuid4().hex[:12]}"
    now = _now()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO agents(agent_id, name, role, tool_policy,"
                    " default_task_class, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                    (aid, name, body.get("role"), body.get("tool_policy"),
                     body.get("default_task_class"), now, now))
        audit.append(con, matter_id="", actor=principal["username"],
                     action="agent.created", target=aid, inputs_digest=name[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return dict(con.execute("SELECT * FROM agents WHERE agent_id=?",
                            (aid,)).fetchone())


def patch_agent(con, principal: dict, agent_id: str, body: dict) -> dict:
    authz.require(con, principal, WRITE)
    row = con.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
    if row is None:
        raise authz.not_found("agent_not_found", f"agent {agent_id!r} not found")
    fields = [f for f in ("name", "role", "tool_policy", "default_task_class")
              if f in body]
    if not fields:
        raise authz.ServiceError(422, "validation_failed", "no patchable fields")
    sets = ",".join(f"{f}=?" for f in fields)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(f"UPDATE agents SET {sets}, updated_at=? WHERE agent_id=?",
                    (*[body[f] for f in fields], _now(), agent_id))
        audit.append(con, matter_id="", actor=principal["username"],
                     action="agent.updated", target=agent_id,
                     inputs_digest=",".join(fields))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return dict(con.execute("SELECT * FROM agents WHERE agent_id=?",
                            (agent_id,)).fetchone())


# -- runs (04 §5.5, thin) -------------------------------------------------------

def list_runs(con, principal: dict, matter_id: str, *, state: str = "") -> list[dict]:
    authz.require(con, principal, authz.READ, matter_id)
    rows = con.execute(
        "SELECT e.* FROM executions e WHERE e.matter_id=? ORDER BY e.started_at DESC",
        (matter_id,)).fetchall()
    out = [dict(r) for r in rows]
    if state:
        out = [r for r in out if r["state"] == state]
    return out


def get_run(con, principal: dict, run_id: str) -> dict:
    row = con.execute("SELECT * FROM executions WHERE execution_id=?",
                      (run_id,)).fetchone()
    if row is None:
        raise authz.not_found("run_not_found", f"run {run_id!r} not found")
    authz.require(con, principal, authz.READ, row["matter_id"])
    # inspection timeline (05 §5.5/§5.9): the run's last 200 events, oldest first
    events = [dict(e) for e in con.execute(
        "SELECT id, ts, type, json_extract(payload_json,'$.task_id') AS task_id"
        " FROM workflow_events WHERE json_extract(payload_json,'$.execution_id')=?"
        " ORDER BY id DESC LIMIT 200", (run_id,))]
    return {**dict(row), "events": events[::-1]}


def interject(con, principal: dict, run_id: str, body: dict) -> dict:
    row = con.execute("SELECT * FROM executions WHERE execution_id=?",
                      (run_id,)).fetchone()
    if row is None:
        raise authz.not_found("run_not_found", f"run {run_id!r} not found")
    authz.require(con, principal, DISPATCH, row["matter_id"])
    text = (body or {}).get("text") or ""
    if not text:
        raise authz.ServiceError(422, "validation_failed", "text required")
    iid = f"inj-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO interjections(interjection_id, run_id, matter_id,"
                    " text, actor, ts) VALUES(?,?,?,?,?,?)",
                    (iid, run_id, row["matter_id"], text, principal["username"], _now()))
        audit.append(con, matter_id=row["matter_id"], actor=principal["username"],
                     action="run.interject", target=run_id, inputs_digest=text[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"interjection_id": iid, "run_id": run_id, "text": text}


def cancel_run(con, principal: dict, run_id: str) -> dict:
    from harness.service import executions
    return executions.cancel(con, principal, run_id, {"reason": "cancelled via run"})


# -- approvals + requests (04 §5.6) ----------------------------------------------

def list_approvals(con, principal: dict, *, state: str = "pending",
                   matter_id: str | None = None, limit: int = 50,
                   cursor: int = 0) -> dict:
    if matter_id is not None:
        authz.require(con, principal, authz.READ, matter_id)
        readable = {matter_id}
    else:
        readable = set(authz.readable_matters(con, principal))
    rows = []
    for r in con.execute("SELECT * FROM approvals WHERE state=?"
                         " ORDER BY requested_at DESC", (state or "pending",)):
        if r["matter_id"] not in readable:
            continue
        d = dict(r)
        try:
            d["request_payload"] = json.loads(d.pop("request_payload_json") or "{}")
        except ValueError:
            d["request_payload"] = {}
        rows.append(d)
    total = len(rows)
    page = rows[cursor:cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {"items": page, "next_cursor": next_cursor}


def _approval_row(con, approval_id: str) -> dict:
    r = con.execute("SELECT * FROM approvals WHERE approval_id=?",
                    (approval_id,)).fetchone()
    if r is None:
        raise authz.not_found("approval_not_found",
                              f"approval {approval_id!r} not found")
    return dict(r)


def decide(con, principal: dict, approval_id: str, *, approve: bool,
           note: str = "") -> dict:
    row = _approval_row(con, approval_id)
    authz.require(con, principal, DECIDE, row["matter_id"])
    try:
        _approvals.decide(con, approval_id, approve=approve,
                          decided_by=principal["username"], note=note)
    except ValueError as exc:
        raise authz.ServiceError(409, "invalid_transition", str(exc)) from None
    if approve and row["kind"] == "matter.close":
        from harness.lifecycle import statemachine
        try:
            statemachine.transition(con, row["matter_id"], "CLOSED",
                                    actor=principal["username"], note=approval_id)
        except RuntimeError as exc:
            raise authz.ServiceError(409, "invalid_transition", str(exc)) from None
    return _approval_row(con, approval_id)


def create_request(con, principal: dict, matter_id: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, matter_id)
    question = (body or {}).get("question") or ""
    kind = (body or {}).get("kind") or "info"
    if not question:
        raise authz.ServiceError(422, "validation_failed", "question required")
    qid = f"req-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "INSERT INTO approvals(approval_id, matter_id, execution_id, task_id, kind,"
            " request_payload_json, state, requested_at) VALUES(?,?,?,?,?,?, 'pending',?)",
            (qid, matter_id, body.get("task_id") or "", "", f"info_request:{kind}",
             json.dumps({"question": question}), _now()))
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="request.created", target=qid, inputs_digest=question[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return _approval_row(con, qid)


def answer_request(con, principal: dict, request_id: str, body: dict) -> dict:
    """Answering a request un-parks it exactly like an approve decision."""
    row = _approval_row(con, request_id)
    authz.require(con, principal, DECIDE, row["matter_id"])
    text = (body or {}).get("text") or ""
    if not text and not (body or {}).get("doc_ids"):
        raise authz.ServiceError(422, "validation_failed", "text or doc_ids required")
    con.execute("BEGIN IMMEDIATE")
    try:
        if row["state"] != "pending":
            raise authz.ServiceError(409, "invalid_transition",
                                     f"request {request_id} already {row['state']}")
        con.execute("UPDATE approvals SET state='answered', decided_by=?,"
                    " decision_note=?, decided_at=? WHERE approval_id=?",
                    (principal["username"], text[:500], _now(), request_id))
        audit.append(con, matter_id=row["matter_id"], actor=principal["username"],
                     action="request.answered", target=request_id,
                     inputs_digest=text[:200])
        con.execute("COMMIT")
    except authz.ServiceError:
        con.execute("ROLLBACK")
        raise
    except Exception:
        con.execute("ROLLBACK")
        raise
    return _approval_row(con, request_id)
