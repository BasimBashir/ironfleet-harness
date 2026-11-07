# src/harness/lifecycle/dossier.py — the SQL case dossier (M5, docs/enterprise/07).
# Ported 1:1 from ironfleet-legal/mcp/dossier.py: the nine JSONL registers become
# tables in platform.db; append validates at the boundary and writes row + audit
# event in one transaction; read computes projections at read, never stores them.
# Due dates are never computed here — kernels only (deadlines.py).
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from harness.workflow import audit

ENTITIES = (
    "facts", "evidence", "strategy", "proposals", "predictions",
    "court_events", "deadlines", "outcomes", "flaws",
)

_DUE_SOON_DAYS = 7

# entity -> (table, id column). Row shapes mirror the plugin's event dicts.
_TABLES = {
    "facts": ("facts", None),
    "evidence": ("evidence", "evidence_id"),
    "strategy": ("strategy_versions", None),
    "proposals": ("proposals", "proposal_id"),
    "predictions": ("predictions", "prediction_id"),
    "court_events": ("case_events", "event_id"),
    "deadlines": ("deadlines", "deadline_id"),
    "outcomes": ("outcomes", "outcome_id"),
    "flaws": ("flaws", None),
}

# entity -> ordered column list for INSERT; event keys map onto these names.
_COLUMNS = {
    "facts": ("matter_id", "field", "op", "value_json", "actor", "ts"),
    "evidence": ("evidence_id", "matter_id", "op", "label", "file", "sha256", "actor", "ts"),
    "strategy": ("matter_id", "version", "file", "why_changed", "next_actions_json",
                 "actor", "ts"),
    "proposals": ("proposal_id", "matter_id", "what", "why", "asked_at_ts", "response",
                  "responded_at_ts", "actor", "ts"),
    "predictions": ("prediction_id", "matter_id", "strategy_version", "claim", "actor", "ts"),
    "court_events": ("event_id", "matter_id", "event_type", "event_date", "payload_json",
                     "actor", "ts"),
    "deadlines": ("deadline_id", "matter_id", "what", "due", "rule", "source",
                  "service_date", "kind", "status", "missed_consequence", "actor", "ts"),
    "outcomes": ("outcome_id", "prediction_id", "match", "actual", "court_date",
                 "actor", "ts"),
    "flaws": ("flaw_id", "matter_id", "class", "severity", "doc", "status", "detector",
              "detail", "actor", "ts"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matter(matter) -> str:
    if (not isinstance(matter, str) or not matter or ":" in matter
            or "/" in matter or "\\" in matter):
        raise RuntimeError(f"matter ref must be a non-empty colon-free, path-free "
                           f"ref (e.g. harbour-freight), got {matter!r}")
    return matter


def _entity(entity) -> str:
    if entity not in ENTITIES:
        raise RuntimeError(f"unknown dossier entity {entity!r} "
                           f"(one of: {', '.join(ENTITIES)})")
    return entity


def _event_row(entity: str, matter: str, event: dict, actor: str) -> tuple[str, tuple]:
    """Build the (INSERT sql, params) for one event. Missing columns default to
    None/''; ids are generated here so the audit digest can name them."""
    table, idcol = _TABLES[entity]
    cols = list(_COLUMNS[entity])
    row = dict(event)
    row["matter_id"] = matter if "matter_id" in cols else row.get("matter_id")
    row["actor"] = actor
    row["ts"] = _now()
    if idcol and not row.get(idcol):
        prefix = {"evidence": "ev", "proposals": "pr", "predictions": "p",
                  "court_events": "ce", "deadlines": "dl", "outcomes": "o"}.get(entity, "x")
        row[idcol] = f"{prefix}-{uuid.uuid4().hex[:12]}"
    if entity == "facts" and "value" in row:
        row["value_json"] = json.dumps(row.pop("value"), ensure_ascii=False)
    if entity == "court_events" and "payload" in row:
        row["payload_json"] = json.dumps(row.pop("payload"), ensure_ascii=False)
    if entity == "strategy" and isinstance(row.get("next_actions"), (list, dict)):
        row["next_actions_json"] = json.dumps(row.pop("next_actions"), ensure_ascii=False)
    params = []
    for c in cols:
        v = row.get(c)
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        params.append(v)
    sql = (f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})")
    return sql, tuple(params), row


def append(con, matter, entity: str, event: dict, *, actor: str = "case-manager") -> dict:
    """Append one event to one register. Validation at the boundary: a bad
    entity/matter or a non-serialisable event fails HERE, loudly — the INSERT
    and the audit event commit or roll back together."""
    m = _matter(matter)
    e = _entity(entity)
    if not isinstance(event, dict):
        raise RuntimeError("event must be a JSON object")
    try:
        json.dumps(event)
    except (TypeError, ValueError) as ex:
        raise RuntimeError(f"event is not JSON-serialisable: {ex}") from None
    sql, params, row = _event_row(e, m, event, actor)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(sql, params)
        audit.append(con, matter_id=m, actor=actor, action="dossier.append",
                     target=e, inputs_digest=json.dumps(event, sort_keys=True,
                                                       default=str)[:500])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return row


def _events(con, matter: str, entity: str) -> list[dict]:
    table, _ = _TABLES[entity]
    cols = _COLUMNS[entity]
    if entity == "outcomes":
        # outcomes has no matter_id; it hangs off predictions, which does.
        rows = con.execute(
            f"SELECT {','.join('o.' + c for c in cols)} FROM {table} o"
            " JOIN predictions p ON p.prediction_id = o.prediction_id"
            " WHERE p.matter_id=? ORDER BY o.ts, o.rowid", (matter,)).fetchall()
    else:
        rows = con.execute(f"SELECT {','.join(cols)} FROM {table} WHERE matter_id=?"
                           " ORDER BY ts, rowid", (matter,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in list(d):
            if k.endswith("_json") and isinstance(d[k], str):
                try:
                    d[k[:-5]] = json.loads(d[k])
                except ValueError:
                    pass
        out.append(d)
    return out


def _deadline_status(due, today: date) -> str:
    try:
        d = date.fromisoformat(str(due))
    except (TypeError, ValueError):
        return "unknown"
    if d < today:
        return "overdue"
    if d <= today + timedelta(days=_DUE_SOON_DAYS):
        return "due_soon"
    return "ok"


def read(con, matter, entity: str, *, today: date | None = None) -> dict:
    """All events of one register plus its mechanical projection (ported 1:1):
    facts → latest per field; strategy → version chain + latest; deadlines →
    today-relative status; predictions → unresolved; flaws → open + gate_blocked."""
    m = _matter(matter)
    e = _entity(entity)
    events = _events(con, m, e)
    out: dict = {"matter": m, "entity": e, "count": len(events), "events": events}
    if e == "facts":
        fields: dict[str, dict] = {}
        for ev in events:
            if ev.get("op") == "set" and ev.get("field"):
                fields[str(ev["field"])] = ev
        out["fields"] = fields
    elif e == "strategy":
        versions = [ev for ev in events if isinstance(ev.get("version"), int)]
        versions.sort(key=lambda ev: ev["version"])
        out["versions"] = [ev["version"] for ev in versions]
        out["latest"] = versions[-1] if versions else None
    elif e == "deadlines":
        t = today or date.today()
        out["today"] = t.isoformat()
        out["deadlines"] = [dict(ev, status=_deadline_status(ev.get("due"), t))
                            for ev in events]
    elif e == "predictions":
        resolved = {o["prediction_id"] for o in _events(con, m, "outcomes")}
        out["unresolved"] = [ev.get("prediction_id") for ev in events
                             if ev.get("prediction_id") not in resolved]
    elif e == "flaws":
        latest: dict[str, dict] = {}
        for ev in events:
            if ev.get("flaw_id"):
                latest[str(ev["flaw_id"])] = ev
        open_rows = [ev for ev in latest.values() if ev.get("status") == "open"]
        counts = {s: sum(1 for ev in open_rows if ev.get("severity") == s)
                  for s in ("critical", "material", "minor")}
        out["open"] = open_rows
        out["open_counts"] = counts
        out["gate_blocked"] = counts["critical"] > 0 or counts["material"] > 0
    return out
