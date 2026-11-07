# src/harness/lifecycle/lawyer_now.py — the §3.4 "get a lawyer NOW" detector (M5).
# Deterministic rules over registered facts + court events + the deadline register.
# No model involvement: every rule names its trigger in cases.lawyer_now_reason.
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from harness.workflow import audit

# claim above the self-help threshold (NZD)
_SELF_HELP_MAX = 25000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def evaluate(con, matter: str, *, actor: str = "safety",
             today: date | None = None) -> dict:
    """Run the §3.4 rule set; set cases.lawyer_now + reason JSON + audit event
    in one transaction. Returns {lawyer_now, rules: [...]}.

    Rules (NEXT_STEPS §3.4):
      criminal_exposure        — facts.criminal == true
      family_safety            — facts.children_involved == true
      user_insolvency          — facts.insolvent == true
      claim_above_self_help    — facts.claim_amount > 25000
      missed_limitation        — an overdue deadline whose what mentions limitation
      court_order_against_user — a court event ordering something against the user
    """
    t = today or date.today()
    # latest value per field (projection at read, same rule as dossier.read)
    facts = {}
    for r in con.execute("SELECT field, value_json FROM facts WHERE matter_id=?"
                         " ORDER BY ts, rowid", (matter,)).fetchall():
        try:
            facts[r["field"]] = json.loads(r["value_json"])
        except (ValueError, TypeError):
            facts[r["field"]] = r["value_json"]

    triggered: list[str] = []
    if facts.get("criminal") is True:
        triggered.append("criminal_exposure")
    if facts.get("children_involved") is True:
        triggered.append("family_safety")
    if facts.get("insolvent") is True:
        triggered.append("user_insolvency")
    try:
        if float(facts.get("claim_amount", 0)) > _SELF_HELP_MAX:
            triggered.append("claim_above_self_help")
    except (TypeError, ValueError):
        pass
    for r in con.execute("SELECT what, due, status FROM deadlines WHERE matter_id=?",
                         (matter,)).fetchall():
        if "limitation" in str(r["what"]).lower() and r["status"] == "overdue":
            triggered.append("missed_limitation")
            break
    for r in con.execute("SELECT payload_json FROM case_events WHERE matter_id=?",
                         (matter,)).fetchall():
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except ValueError:
            continue
        text = " ".join(str(o) for o in payload.get("orders", [])).lower()
        if any(k in text for k in ("against the defendant", "against the plaintiff",
                                   "costs against", "contempt")):
            triggered.append("court_order_against_user")
            break

    con.execute("BEGIN IMMEDIATE")
    try:
        now = _now()
        row = con.execute("SELECT matter_id FROM cases WHERE matter_id=?",
                          (matter,)).fetchone()
        if row is None:
            con.execute("INSERT INTO cases(matter_id, state, lawyer_now, "
                        "lawyer_now_reason, needs_restrategy, created_at, updated_at)"
                        " VALUES(?,NULL,?,?,0,?,?)",
                        (matter, 1 if triggered else 0, json.dumps(triggered), now, now))
        else:
            con.execute("UPDATE cases SET lawyer_now=?, lawyer_now_reason=?, "
                        "updated_at=? WHERE matter_id=?",
                        (1 if triggered else 0, json.dumps(triggered), now, matter))
        if triggered:
            audit.append(con, matter_id=matter, actor=actor, action="lawyer_now",
                         target=",".join(triggered))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"lawyer_now": bool(triggered), "rules": triggered}
