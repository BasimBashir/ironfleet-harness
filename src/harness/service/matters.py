# src/harness/service/matters.py — matter CRUD + members + derived state (M7, 04 §5.2)
"""Every function takes `principal` first and calls authz.require before
touching data — the routes never check permissions (plan §2). List/create are
matter-scoped by membership: list shows readable matters only; create also
inserts the creator's admin membership row so the creator can read it back."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from harness.service import authz
from harness.workflow import audit, orchestrator

WRITE = "matter.write"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matter_dict(con, r) -> dict:
    d = dict(r)
    d["state"] = orchestrator.matter_state(con, d["matter_id"])
    d["outstanding_approvals"] = con.execute(
        "SELECT COUNT(*) AS c FROM approvals WHERE matter_id=? AND state='pending'",
        (d["matter_id"],)).fetchone()["c"]
    return d


def list_matters(con, principal: dict, *, state: str = "", q: str = "",
                 limit: int = 50, cursor: int = 0) -> dict:
    """Board rows over the principal's readable matters. cursor = rowid offset
    of matters (stable while rows are append-only in practice; ties broken by
    matter_id)."""
    ids = set(authz.readable_matters(con, principal))
    rows = con.execute(
        "SELECT * FROM matters WHERE archived=0 ORDER BY created_at, matter_id"
    ).fetchall()
    items = [_matter_dict(con, r) for r in rows if r["matter_id"] in ids]
    if state:
        items = [m for m in items if m["state"] == state]
    if q:
        ql = q.lower()
        items = [m for m in items
                 if ql in (m.get("title") or "").lower()
                 or ql in (m.get("client_ref") or "").lower()]
    total = len(items)
    page = items[cursor:cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {"items": page, "next_cursor": next_cursor}


def create(con, principal: dict, body: dict) -> dict:
    # opening a matter needs matter.write on the principal's platform role
    authz.require(con, principal, WRITE)
    mid = f"m-{uuid.uuid4().hex[:12]}"
    now = _now()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "INSERT INTO matters(matter_id, title, client_ref, matter_type,"
            " jurisdiction, confidentiality, objectives, priority, archived,"
            " created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,0,?,?,?)",
            (mid, body.get("title") or "", body.get("client_ref"),
             body.get("matter_type"), body.get("jurisdiction"),
             body.get("confidentiality"), body.get("objectives"),
             body.get("priority") or "normal", principal["user_id"], now, now))
        con.execute("INSERT INTO matter_members(matter_id, user_id, role_id)"
                    " VALUES(?,?,?)", (mid, principal["user_id"], principal["role_id"]))
        audit.append(con, matter_id=mid, actor=principal["username"],
                     action="matter.created", target=mid,
                     inputs_digest=(body.get("title") or "")[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    row = con.execute("SELECT * FROM matters WHERE matter_id=?", (mid,)).fetchone()
    return _matter_dict(con, row)


def get(con, principal: dict, matter_id: str) -> dict:
    authz.require(con, principal, authz.READ, matter_id)
    row = con.execute("SELECT * FROM matters WHERE matter_id=?",
                      (matter_id,)).fetchone()
    if row is None:
        raise authz.not_found("matter_not_found", f"matter {matter_id!r} not found")
    return _matter_dict(con, row)


def patch(con, principal: dict, matter_id: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, matter_id)
    row = con.execute("SELECT * FROM matters WHERE matter_id=?",
                      (matter_id,)).fetchone()
    if row is None:
        raise authz.not_found("matter_not_found", f"matter {matter_id!r} not found")
    fields = [f for f in ("title", "client_ref", "matter_type", "jurisdiction",
                          "confidentiality", "objectives", "priority")
              if f in body]
    if not fields:
        raise authz.ServiceError(422, "validation_failed", "no patchable fields")
    sets = ",".join(f"{f}=?" for f in fields)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(f"UPDATE matters SET {sets}, updated_at=? WHERE matter_id=?",
                    (*[body[f] for f in fields], _now(), matter_id))
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="matter.updated", target=matter_id,
                     inputs_digest=",".join(fields))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return get(con, principal, matter_id)


def set_state(con, principal: dict, matter_id: str, body: dict) -> dict:
    """Only archived/active are stored facts (plan §0.5); the rest of 02 §4's
    state is derived. Anything else -> 409 invalid_transition."""
    authz.require(con, principal, WRITE, matter_id)
    to = body.get("to")
    if to not in ("archived", "active"):
        raise authz.ServiceError(409, "invalid_transition",
                                 f"stored state accepts only archived|active, got {to!r}")
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE matters SET archived=?, updated_at=? WHERE matter_id=?",
                    (1 if to == "archived" else 0, _now(), matter_id))
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="matter.state", target=to)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return get(con, principal, matter_id)


def members(con, principal: dict, matter_id: str) -> list[dict]:
    authz.require(con, principal, authz.READ, matter_id)
    rows = con.execute(
        "SELECT mm.user_id, u.username, mm.role_id FROM matter_members mm"
        " JOIN users u ON u.user_id=mm.user_id WHERE mm.matter_id=?"
        " ORDER BY u.username", (matter_id,)).fetchall()
    return [{"user": {"user_id": r["user_id"], "username": r["username"]},
             "role": r["role_id"]} for r in rows]


def put_member(con, principal: dict, matter_id: str, user_id: str,
               body: dict) -> dict:
    authz.require(con, principal, WRITE, matter_id)
    role_id = body.get("role_id")
    if not role_id or con.execute("SELECT 1 FROM roles WHERE role_id=?",
                                  (role_id,)).fetchone() is None:
        raise authz.ServiceError(422, "validation_failed", f"unknown role_id {role_id!r}")
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO matter_members(matter_id, user_id, role_id)"
                    " VALUES(?,?,?) ON CONFLICT(matter_id, user_id)"
                    " DO UPDATE SET role_id=excluded.role_id",
                    (matter_id, user_id, role_id))
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="member.put", target=user_id, inputs_digest=role_id)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"user": {"user_id": user_id}, "role": role_id}


def delete_member(con, principal: dict, matter_id: str, user_id: str) -> None:
    authz.require(con, principal, WRITE, matter_id)
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute("DELETE FROM matter_members WHERE matter_id=? AND user_id=?",
                          (matter_id, user_id))
        if cur.rowcount != 1:
            con.execute("ROLLBACK")
            raise authz.not_found("member_not_found",
                                  f"no membership for {user_id!r} on {matter_id!r}")
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="member.deleted", target=user_id)
        con.execute("COMMIT")
    except authz.ServiceError:
        raise
    except Exception:
        con.execute("ROLLBACK")
        raise
