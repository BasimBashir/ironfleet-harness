# src/harness/api/deps.py — per-request connection, authentication, paging (M7)
"""AUTHENTICATION ONLY: a bearer token becomes a principal or a 401. Whether
that principal may do anything is decided in harness.service (plan §2)."""
from __future__ import annotations

import base64

from fastapi import Depends, Query, Request

from harness.service import auth, system
from harness.service.authz import ServiceError


def get_con(request: Request):
    con = system.open_db(request.app.state.store_root)
    try:
        yield con
    finally:
        con.close()


def bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return (h[7:].strip() or None) if h.lower().startswith("bearer ") else None


def get_principal(request: Request, con=Depends(get_con)) -> dict:
    p = auth.principal_for(con, bearer(request))
    if p is None:
        raise ServiceError(401, "unauthenticated", "bearer token required")
    return p


def page(limit: int = Query(50, ge=1, le=200), cursor: str | None = None) -> dict:
    """Opaque cursor -> offset. shortcut: offset cursor, not keyset — a row
    inserted mid-walk can shift a page; upgrade if the board ever pages live."""
    off = 0
    if cursor:
        try:
            off = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeDecodeError):
            raise ServiceError(422, "validation_failed", "bad cursor") from None
        if off < 0:
            raise ServiceError(422, "validation_failed", "bad cursor")
    return {"limit": limit, "cursor": off}


def paged(result: dict) -> dict:
    nc = result.get("next_cursor")
    return {**result, "next_cursor": None if nc is None
            else base64.urlsafe_b64encode(str(nc).encode()).decode()}
