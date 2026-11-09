# src/harness/service/authz.py — THE authorization point (M7, enterprise 02 §11, 04 §4)
"""Every service function the API calls takes a principal and calls require()
before touching data; routes never check permissions. Matter access = a
matter_members row for that matter (its role's perms), or the global
`matter.cross_read` key, which grants reads only. No row -> 404
matter_not_found (fails closed, doesn't leak existence); row but missing perm
-> 403 permission_denied."""
from __future__ import annotations

READ = "matter.read"


class ServiceError(Exception):
    """Carries the stable error code + HTTP status the API envelope renders."""

    def __init__(self, status: int, code: str, message: str = "", details=None):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code
        self.details = details or {}


def not_found(code: str = "not_found", message: str = "") -> ServiceError:
    return ServiceError(404, code, message)


def _role_perms(con, role_id: str | None) -> set[str]:
    return {r["perm"] for r in con.execute(
        "SELECT perm FROM role_permissions WHERE role_id=?", (role_id,))}


def global_perms(con, principal: dict) -> set[str]:
    """Perms from the user's platform role (cross_read, audit.read, ...)."""
    return _role_perms(con, principal.get("role_id"))


def matter_perms(con, principal: dict, matter_id: str) -> set[str]:
    """Perms on one matter: the membership role's keys, plus read via cross_read."""
    row = con.execute("SELECT role_id FROM matter_members WHERE matter_id=? AND user_id=?",
                      (matter_id, principal["user_id"])).fetchone()
    perms = _role_perms(con, row["role_id"]) if row else set()
    if "matter.cross_read" in global_perms(con, principal):
        perms.add(READ)
    return perms


def require(con, principal: dict | None, perm: str, matter_id: str | None = None) -> None:
    if principal is None:
        raise ServiceError(401, "unauthenticated", "bearer token required")
    if matter_id is None:
        if perm not in global_perms(con, principal):
            raise ServiceError(403, "permission_denied", f"missing {perm}")
        return
    exists = con.execute("SELECT 1 FROM matters WHERE matter_id=?", (matter_id,)).fetchone()
    perms = matter_perms(con, principal, matter_id) if exists else set()
    if not perms:
        raise not_found("matter_not_found", f"matter {matter_id!r} not found")
    if perm not in perms:
        raise ServiceError(403, "permission_denied", f"missing {perm} on {matter_id}")


def readable_matters(con, principal: dict) -> list[str]:
    """Matter ids the principal may read (board channel, lists, approvals)."""
    if principal is None:
        raise ServiceError(401, "unauthenticated", "bearer token required")
    if "matter.cross_read" in global_perms(con, principal):
        return [r["matter_id"] for r in con.execute("SELECT matter_id FROM matters")]
    return [r["matter_id"] for r in con.execute(
        "SELECT mm.matter_id FROM matter_members mm JOIN role_permissions rp"
        " ON rp.role_id = mm.role_id AND rp.perm = ? WHERE mm.user_id=?",
        (READ, principal["user_id"]))]
