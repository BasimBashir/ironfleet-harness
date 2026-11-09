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


def create_user(con, username: str, password: str, *, role_id: str = "admin") -> str:
    if not username or not password:
        raise ServiceError(422, "validation_failed", "username and password required")
    uid = f"u-{uuid.uuid4().hex[:12]}"
    try:
        con.execute("INSERT INTO users(user_id, username, pw_hash, role_id, created_at)"
                    " VALUES(?,?,?,?,?)", (uid, username, hash_password(password),
                                           role_id, _now()))
    except Exception as e:  # sqlite3.IntegrityError: username taken
        raise ServiceError(409, "user_exists", f"user {username!r} exists") from e
    return uid


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
    return _issue(con, row["user_id"])


def principal_for(con, token: str | None) -> dict | None:
    """Authentication only: bearer token -> principal dict, or None."""
    if not token:
        return None
    row = con.execute(
        "SELECT u.user_id, u.username, u.role_id FROM tokens t JOIN users u"
        " ON u.user_id = t.user_id WHERE t.token_hash=? AND t.revoked=0"
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
            "permissions": sorted(global_perms(con, principal))}
