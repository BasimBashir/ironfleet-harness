# src/harness/service/idempotency.py — Idempotency-Key storage (M7, plan §2)
"""Keyed per principal: same key + same request hash -> the stored response is
replayed; same key + different hash -> 409 idempotency_conflict. Only 2xx
responses are stored, so a failed attempt can be retried with the same key."""
from __future__ import annotations

from datetime import datetime, timezone

from harness.service.authz import ServiceError


def lookup(con, user_id: str, key: str, request_hash: str) -> tuple[int, str] | None:
    row = con.execute("SELECT request_hash, status, body FROM idempotency_keys"
                      " WHERE user_id=? AND key=?", (user_id, key)).fetchone()
    if row is None:
        return None
    if row["request_hash"] != request_hash:
        raise ServiceError(409, "idempotency_conflict",
                           "Idempotency-Key reused with a different request")
    return row["status"], row["body"]


def store(con, user_id: str, key: str, request_hash: str, status: int, body: str) -> None:
    # shortcut: two concurrent first uses of one key both execute (first row wins);
    # upgrade to a reserve-then-fill row if clients ever race their own retries.
    con.execute("INSERT OR IGNORE INTO idempotency_keys(user_id, key, request_hash,"
                " status, body, created_at) VALUES(?,?,?,?,?,?)",
                (user_id, key, request_hash, status, body,
                 datetime.now(timezone.utc).isoformat()))
