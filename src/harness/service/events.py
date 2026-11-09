# src/harness/service/events.py — the SSE source over workflow_events (M7, 04 §5.7)
"""since() is the read side of the append-only workflow_events table (id=rowid,
so Last-Event-ID replay is WHERE id > ?). Channel authorization lives in the
callers: `matter:{mid}` requires matter.read on that matter; `board` only
carries matters the principal can read (authz.readable_matters)."""
from __future__ import annotations

import json

from harness.service import authz


def _row(r) -> dict:
    d = dict(r)
    try:
        d["payload"] = json.loads(d.pop("payload_json") or "{}")
    except ValueError:
        d["payload"] = {}
    return d


def since(con, principal: dict, channels: list[str], after_id: int = 0,
          *, limit: int = 500) -> list[dict]:
    """Events after `after_id` on the authorized channels, oldest first.

    channels: "matter:{mid}" or "board". Every matter channel is checked with
    authz.require (no membership -> 404 matter_not_found, fails closed); board
    expands to the principal's readable matters, so it never carries a matter
    the principal cannot see."""
    matter_ids: list[str] = []
    want_board = False
    for ch in channels:
        if ch == "board":
            want_board = True
        elif ch.startswith("matter:"):
            mid = ch[len("matter:"):]
            authz.require(con, principal, authz.READ, mid)
            if mid not in matter_ids:
                matter_ids.append(mid)
        else:
            raise authz.ServiceError(422, "validation_failed",
                                     f"unknown channel {ch!r}")
    if want_board:
        for mid in authz.readable_matters(con, principal):
            if mid not in matter_ids:
                matter_ids.append(mid)
    if not matter_ids:
        return []
    marks = ",".join("?" * len(matter_ids))
    rows = con.execute(
        f"SELECT id, matter_id, type, payload_json, ts FROM workflow_events"
        f" WHERE id > ? AND matter_id IN ({marks}) ORDER BY id LIMIT ?",
        (after_id, *matter_ids, limit)).fetchall()
    return [_row(r) for r in rows]


def latest_id(con) -> int:
    row = con.execute("SELECT MAX(id) AS m FROM workflow_events").fetchone()
    return row["m"] or 0
