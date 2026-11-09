# src/harness/workflow/audit.py — the hash-chained AuditEvent log (03 §2.19)
"""Append-only by db trigger, not by convention: UPDATE/DELETE RAISE(ABORT).
Each event's hash = sha256(prev_hash + canonical json of the row), genesis
prev_hash = "0"*64. verify() recomputes every hash and every link and names
the first bad row. Tail truncation is NOT detectable by verify alone (needs an
externally anchored head hash — later, with the auditor role)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

GENESIS = "0" * 64
# The append-only triggers live in db.SCHEMA (created once at connect); running
# DDL inside append() would commit the caller's open transaction.


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def append(con, *, matter_id: str, actor: str, action: str, target: str,
           inputs_digest: str = "", outputs_digest: str = "") -> str:
    """Append one event in the caller's open transaction, so the audit row and
    the state change it records commit or roll back together."""
    prev = con.execute("SELECT hash FROM audit_events ORDER BY rowid DESC"
                       " LIMIT 1").fetchone()
    prev_hash = prev["hash"] if prev else GENESIS
    aid = f"aud-{uuid.uuid4().hex[:12]}"
    row = {"audit_id": aid, "matter_id": matter_id, "actor": actor, "action": action,
           "target": target, "inputs_digest": inputs_digest,
           "outputs_digest": outputs_digest, "prev_hash": prev_hash,
           "ts": datetime.now(timezone.utc).isoformat()}
    row["hash"] = hashlib.sha256((prev_hash + _canonical(row)).encode("utf-8")).hexdigest()
    con.execute(
        "INSERT INTO audit_events(audit_id, matter_id, actor, action, target,"
        " inputs_digest, outputs_digest, prev_hash, hash, ts)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (row["audit_id"], matter_id, actor, action, target, inputs_digest,
         outputs_digest, prev_hash, row["hash"], row["ts"]))
    # every audited write is also an SSE event, in the same transaction (M7, 03 §2.14)
    emit(con, matter_id, action, {"actor": actor, "target": target, "audit_id": aid})
    return aid


def emit(con, matter_id: str, type: str, payload: dict) -> int:
    """Append one workflow_events row in the caller's transaction (SSE source;
    id = rowid so Last-Event-ID replay is WHERE id > ?)."""
    cur = con.execute(
        "INSERT INTO workflow_events(matter_id, type, payload_json, ts) VALUES(?,?,?,?)",
        (matter_id, type, json.dumps(payload, sort_keys=True),
         datetime.now(timezone.utc).isoformat()))
    return cur.lastrowid


def verify(con) -> tuple[bool, str | None]:
    """Recompute the chain; returns (ok, first_bad_audit_id). A tampered row
    fails its own hash; a deleted middle row breaks the NEXT row's link."""
    prev_hash = GENESIS
    for r in con.execute("SELECT * FROM audit_events ORDER BY rowid").fetchall():
        row = dict(r)
        expect = row.pop("hash")
        if row["prev_hash"] != prev_hash or \
                hashlib.sha256((prev_hash + _canonical(row)).encode("utf-8")).hexdigest() != expect:
            return False, row["audit_id"]
        prev_hash = expect
    return True, None
