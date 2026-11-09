# src/harness/service/conversations.py — counsel chat rows + ops reads (M7, 04 §5.8/§5.9)
"""Conversations/messages are durable rows; posting a message creates an
execution through the same dispatch use-case as POST /executions (04 §5.8:
chat and the board are views of the same state) and returns 202. Ops: healthz
summary (no auth, loopback) and the audit list (global audit.read)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from harness.service import authz, executions
from harness.workflow import audit

WRITE = "matter.write"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conv(con, cid: str) -> dict:
    row = con.execute("SELECT * FROM conversations WHERE conversation_id=?",
                      (cid,)).fetchone()
    if row is None:
        raise authz.not_found("conversation_not_found",
                              f"conversation {cid!r} not found")
    return dict(row)


def list_conversations(con, principal: dict, mid: str) -> list[dict]:
    authz.require(con, principal, authz.READ, mid)
    return [dict(r) for r in con.execute(
        "SELECT * FROM conversations WHERE matter_id=? ORDER BY created_at", (mid,))]


def create_conversation(con, principal: dict, mid: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, mid)
    cid = f"cv-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO conversations(conversation_id, matter_id, title,"
                    " created_by, created_at) VALUES(?,?,?,?,?)",
                    (cid, mid, (body or {}).get("title") or "", principal["user_id"],
                     _now()))
        audit.append(con, matter_id=mid, actor=principal["username"],
                     action="conversation.created", target=cid)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return _conv(con, cid)


def list_messages(con, principal: dict, cid: str, *, limit: int = 50,
                  cursor: int = 0) -> dict:
    conv = _conv(con, cid)
    authz.require(con, principal, authz.READ, conv["matter_id"])
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY ts, rowid", (cid,))]
    nxt = cursor + limit if cursor + limit < len(rows) else None
    return {"items": rows[cursor:cursor + limit], "next_cursor": nxt}


def post_message(con, principal: dict, cid: str, body: dict) -> dict:
    conv = _conv(con, cid)
    text = (body or {}).get("text") or ""
    if not text:
        raise authz.ServiceError(422, "validation_failed", "text required")
    # dispatch authz + execution row via the shared use-case (needs matter.dispatch)
    ex = executions.create(con, principal, conv["matter_id"], {"task_text": text})
    mid_ = f"msg-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO messages(message_id, conversation_id, matter_id, role,"
                    " text, execution_id, actor, ts) VALUES(?,?,?,?,?,?,?,?)",
                    (mid_, cid, conv["matter_id"], "user", text, ex["execution_id"],
                     principal["username"], _now()))
        audit.append(con, matter_id=conv["matter_id"], actor=principal["username"],
                     action="message.posted", target=mid_)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    msg = dict(con.execute("SELECT * FROM messages WHERE message_id=?",
                           (mid_,)).fetchone())
    return {"message": msg, "execution": {"execution_id": ex["execution_id"],
                                          "state": ex["state"]}}


# -- ops (04 §5.9) ---------------------------------------------------------------

def healthz(con) -> dict:
    """No auth (loopback only). Store check is a live query; the provider summary
    is the doctor's text (soft failures stay inside doctor_report)."""
    from harness.service.system import doctor_report
    con.execute("SELECT 1").fetchone()
    try:
        doctor = doctor_report()
    except Exception as exc:                                      # noqa: BLE001
        doctor = f"doctor unavailable: {type(exc).__name__}"
    return {"stores": "ok", "proxy_bound": True, "providers": doctor,
            "version": "v1"}


def audit_list(con, principal: dict, *, matter_id: str = "", limit: int = 50,
               cursor: int = 0) -> dict:
    authz.require(con, principal, "audit.read")
    if matter_id:
        rows = con.execute("SELECT * FROM audit_events WHERE matter_id=?"
                           " ORDER BY rowid", (matter_id,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM audit_events ORDER BY rowid").fetchall()
    ok, bad = audit.verify(con)
    items = [dict(r) for r in rows[cursor:cursor + limit]]
    nxt = cursor + limit if cursor + limit < len(rows) else None
    return {"items": items, "next_cursor": nxt,
            "chain": {"ok": ok, "first_bad": bad}}
