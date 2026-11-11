# src/harness/service/auth.py — local accounts + opaque bearer tokens (M7, 02 §11)
"""Passwords: stdlib pbkdf2_hmac-sha256 with a per-user salt. Tokens: 32 random
bytes handed to the client once; only their sha256 is stored, so a leaked
platform.db does not leak live sessions. Refresh rotates (old token revoked)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timezone

from harness.service.authz import ServiceError, global_perms

TOKEN_TTL_S = 12 * 3600
_ITER = 600_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                  bytes.fromhex(salt), int(it))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(got.hex(), dk)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_user(con, username: str, password: str, *, role_id: str = "admin",
                must_change_password: bool = False) -> str:
    if not username or not password:
        raise ServiceError(422, "validation_failed", "username and password required")
    uid = f"u-{uuid.uuid4().hex[:12]}"
    try:
        con.execute("INSERT INTO users(user_id, username, pw_hash, role_id, created_at,"
                    " state, must_change_password) VALUES(?,?,?,?,?,'active',?)",
                    (uid, username, hash_password(password), role_id, _now(),
                     int(must_change_password)))
    except Exception as e:  # sqlite3.IntegrityError: username taken
        raise ServiceError(409, "user_exists", f"user {username!r} exists") from e
    return uid


def signup(con, username: str, password: str) -> dict:
    """Public account request (B): pending + inactive until a user.admin approves.
    Rejected names stay reserved, so any state conflict is the same 409."""
    from harness.workflow import audit
    if not username or not password:
        raise ServiceError(422, "validation_failed", "username and password required")
    uid = f"u-{uuid.uuid4().hex[:12]}"
    try:
        con.execute("INSERT INTO users(user_id, username, pw_hash, role_id, is_active,"
                    " created_at, state) VALUES(?,?,?,?,0,?,'pending')",
                    (uid, username, hash_password(password), "reader", _now()))
    except Exception as e:  # sqlite3.IntegrityError: username taken
        raise ServiceError(409, "user_exists", f"user {username!r} exists") from e
    audit.append(con, matter_id="", actor=username, action="user.signup_requested",
                 target=uid, inputs_digest=username[:200])
    return {"user_id": uid, "state": "pending"}


def set_password(con, principal: dict | None, password: str) -> dict:
    """Self-service change; clears the forced-change flag (B default admin/admin)."""
    from harness.workflow import audit
    if principal is None:
        raise ServiceError(401, "unauthenticated", "bearer token required")
    if not password:
        raise ServiceError(422, "validation_failed", "password required")
    con.execute("UPDATE users SET pw_hash=?, must_change_password=0 WHERE user_id=?",
                (hash_password(password), principal["user_id"]))
    audit.append(con, matter_id="", actor=principal["username"],
                 action="user.password_changed", target=principal["user_id"],
                 inputs_digest="")
    return {"ok": True}


def _issue(con, user_id: str) -> dict:
    token = secrets.token_urlsafe(32)
    exp = time.time() + TOKEN_TTL_S
    con.execute("INSERT INTO tokens(token_hash, user_id, kind, expires_at, created_at)"
                " VALUES(?,?,?,?,?)", (_sha(token), user_id, "access", exp, _now()))
    return {"token": token,
            "expires_at": datetime.fromtimestamp(exp, timezone.utc).isoformat()}


def login(con, username: str, password: str) -> dict:
    row = con.execute("SELECT * FROM users WHERE username=? AND is_active=1",
                      (username,)).fetchone()
    if row is None or not verify_password(password, row["pw_hash"]):
        raise ServiceError(401, "invalid_credentials", "bad username or password")
    return {**_issue(con, row["user_id"]),
            "must_change_password": bool(row["must_change_password"])}


def principal_for(con, token: str | None) -> dict | None:
    """Authentication only: bearer token -> principal dict, or None."""
    if not token:
        return None
    row = con.execute(
        "SELECT u.user_id, u.username, u.role_id, u.must_change_password FROM tokens t"
        " JOIN users u ON u.user_id = t.user_id WHERE t.token_hash=? AND t.revoked=0"
        " AND t.expires_at > ? AND u.is_active=1", (_sha(token), time.time())).fetchone()
    return dict(row, token=token) if row else None


def refresh(con, principal: dict | None) -> dict:
    if principal is None:
        raise ServiceError(401, "unauthenticated", "bearer token required")
    con.execute("UPDATE tokens SET revoked=1 WHERE token_hash=?", (_sha(principal["token"]),))
    return _issue(con, principal["user_id"])


def me(con, principal: dict | None) -> dict:
    if principal is None:
        raise ServiceError(401, "unauthenticated", "bearer token required")
    return {"user": {"user_id": principal["user_id"], "username": principal["username"]},
            "roles": [principal["role_id"]],
            "permissions": sorted(global_perms(con, principal)),
            "must_change_password": bool(principal["must_change_password"])}
