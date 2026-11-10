# src/harness/service/users.py — user/role admin (05 §12, 03 §2.3-2.5)
"""Only `user.admin` may list/create/patch users and list roles. Deactivation
needs no token sweep: principal_for already filters is_active=1."""
from __future__ import annotations

from harness.service import auth, authz
from harness.workflow import audit

PERM = "user.admin"
_COLS = "user_id, username, role_id, is_active, created_at"  # never pw_hash


def _row(con, uid: str) -> dict | None:
    r = con.execute(f"SELECT {_COLS} FROM users WHERE user_id=?", (uid,)).fetchone()
    return None if r is None else {**dict(r), "is_active": bool(r["is_active"])}


def _check_role(con, role_id) -> None:
    if not con.execute("SELECT 1 FROM roles WHERE role_id=?", (role_id,)).fetchone():
        raise authz.ServiceError(422, "validation_failed", f"unknown role {role_id!r}")


def list_users(con, principal: dict | None) -> list[dict]:
    authz.require(con, principal, PERM)
    return [_row(con, r["user_id"]) for r in
            con.execute("SELECT user_id FROM users ORDER BY username").fetchall()]


def create(con, principal: dict | None, body: dict) -> dict:
    authz.require(con, principal, PERM)
    role_id = body.get("role_id") or "reader"
    _check_role(con, role_id)
    con.execute("BEGIN IMMEDIATE")
    try:
        uid = auth.create_user(con, body.get("username") or "", body.get("password") or "",
                               role_id=role_id)
        audit.append(con, matter_id="", actor=principal["username"],
                     action="user.created", target=uid, inputs_digest=body["username"][:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return _row(con, uid)


def patch(con, principal: dict | None, user_id: str, body: dict) -> dict:
    authz.require(con, principal, PERM)
    if _row(con, user_id) is None:
        raise authz.not_found("user_not_found", f"user {user_id!r} not found")
    if body.get("role_id") is not None:
        _check_role(con, body["role_id"])
    con.execute("BEGIN IMMEDIATE")
    try:
        if body.get("role_id") is not None:
            con.execute("UPDATE users SET role_id=? WHERE user_id=?", (body["role_id"], user_id))
        if body.get("is_active") is not None:
            con.execute("UPDATE users SET is_active=? WHERE user_id=?",
                        (int(bool(body["is_active"])), user_id))
        # nobody left to administer users is unrecoverable from the UI
        if not con.execute("SELECT 1 FROM users u JOIN role_permissions rp ON rp.role_id=u.role_id"
                           " WHERE u.is_active=1 AND rp.perm=?", (PERM,)).fetchone():
            raise authz.ServiceError(409, "invalid_transition",
                                     "this change would leave no active user administrator")
        audit.append(con, matter_id="", actor=principal["username"], action="user.updated",
                     target=user_id, inputs_digest=str(sorted(body.items()))[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return _row(con, user_id)


def list_roles(con, principal: dict | None) -> list[dict]:
    authz.require(con, principal, PERM)
    perms: dict[str, list[str]] = {}
    for r in con.execute("SELECT role_id, perm FROM role_permissions ORDER BY perm"):
        perms.setdefault(r["role_id"], []).append(r["perm"])
    return [{**dict(r), "permissions": perms.get(r["role_id"], [])}
            for r in con.execute("SELECT * FROM roles ORDER BY role_id").fetchall()]
