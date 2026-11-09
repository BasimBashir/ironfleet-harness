# src/harness/service/lifecycle_api.py — the 08 §16 lifecycle surface (M7)
"""Principal-first wrappers over the M5 lifecycle modules (statemachine,
dossier, deadlines, debrief, lawyer_now). Every function calls authz.require
first; kernel errors (RuntimeError) become stable envelope codes here so the
routes stay parse -> one call -> serialize. Question sets are static constants
(plan §1: no adaptive questioning in M7)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from harness.lifecycle import deadlines, debrief, dossier, lawyer_now, statemachine
from harness.service import authz
from harness.workflow import audit

WRITE = "matter.write"

# 08 §4: one ask per question, <= 20 words; ids are the facts-register field names
# the lawyer-now detector reads (criminal, children_involved, insolvent, claim_amount).
INTAKE_QUESTIONS = [
    {"id": "summary", "section": "story",
     "text": "Tell us what happened, in your own words. Dates, names and amounts help."},
    {"id": "other_party", "section": "parties", "text": "Who is the other side?"},
    {"id": "claim_amount", "section": "money",
     "text": "How much money is involved, in NZD? For example: 4500"},
    {"id": "key_date", "section": "dates",
     "text": "When did the problem start? For example: 14 March 2026"},
    {"id": "criminal", "section": "safety",
     "text": "Has anyone mentioned police, charges or a criminal investigation?"},
    {"id": "children_involved", "section": "safety",
     "text": "Does this involve the care or safety of children?"},
    {"id": "insolvent", "section": "safety",
     "text": "Are you unable to pay your debts as they fall due?"},
]

# 08 §9 debrief questionnaire; `date` anchors the prediction diff (debrief.py).
DEBRIEF_QUESTIONS = [
    {"id": "date", "text": "What was the date of the hearing? For example: 2026-03-14"},
    {"id": "judge_said", "text": "What did the judge say about the main issue?"},
    {"id": "orders", "text": "Were any orders made? What exactly do they say?"},
    {"id": "next_date", "text": "What is the next date, if one was given?"},
    {"id": "documents_handed", "text": "Did you hand over the documents we listed?"},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _page(items: list, limit: int, cursor: int) -> dict:
    nxt = cursor + limit if cursor + limit < len(items) else None
    return {"items": items[cursor:cursor + limit], "next_cursor": nxt}


def _bad(exc: Exception, code: str = "validation_failed", status: int = 422):
    return authz.ServiceError(status, code, str(exc))


# -- lifecycle ------------------------------------------------------------------

def lifecycle(con, principal: dict, mid: str) -> dict:
    authz.require(con, principal, authz.READ, mid)
    cur = statemachine.state(con, mid)
    hist = [{"to": r["target"], "transition": r["inputs_digest"], "actor": r["actor"],
             "ts": r["ts"]} for r in con.execute(
        "SELECT target, inputs_digest, actor, ts FROM audit_events WHERE matter_id=?"
        " AND action='state.transition' ORDER BY rowid", (mid,)).fetchall()]
    nxt = sorted(statemachine.TRANSITIONS[cur]) if cur else [statemachine.STATES[0]]
    return {"stage": cur, "entered_at": hist[-1]["ts"] if hist else None,
            "history": hist, "next_allowed": nxt}


def transition(con, principal: dict, mid: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, mid)
    try:
        statemachine.transition(con, mid, (body or {}).get("to") or "",
                                actor=principal["username"],
                                note=(body or {}).get("note") or "")
    except RuntimeError as exc:
        raise _bad(exc, "invalid_transition", 409) from None
    return lifecycle(con, principal, mid)


# -- next actions (proposals register) -------------------------------------------

def next_actions(con, principal: dict, mid: str, *, limit: int = 50,
                 cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, mid)
    rows = [ev for ev in dossier.read(con, mid, "proposals")["events"]
            if not ev.get("response")]
    return _page(rows, limit, cursor)


def complete_next_action(con, principal: dict, mid: str, aid: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, mid)
    note = (body or {}).get("note")
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = con.execute(
            "UPDATE proposals SET response=?, responded_at_ts=? WHERE proposal_id=?"
            " AND matter_id=? AND (response IS NULL OR response='')",
            ("done" + (f": {note}" if note else ""), _now(), aid, mid))
        if cur.rowcount != 1:
            raise authz.not_found("next_action_not_found",
                                  f"open next action {aid!r} not found")
        audit.append(con, matter_id=mid, actor=principal["username"],
                     action="next_action.completed", target=aid)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return dict(con.execute("SELECT * FROM proposals WHERE proposal_id=?",
                            (aid,)).fetchone())


# -- facts + intake ---------------------------------------------------------------

def facts(con, principal: dict, mid: str) -> dict:
    authz.require(con, principal, authz.READ, mid)
    reg = dossier.read(con, mid, "facts")
    fields = {k: v.get("value") for k, v in reg["fields"].items()}
    return {"fields": fields,
            "missing": [q["id"] for q in INTAKE_QUESTIONS if q["id"] not in fields]}


def _set_facts(con, principal: dict, mid: str, updates: dict) -> None:
    for field, value in updates.items():
        try:
            dossier.append(con, mid, "facts", {"field": field, "op": "set",
                                               "value": value},
                           actor=principal["username"])
        except RuntimeError as exc:
            raise _bad(exc) from None
    lawyer_now.evaluate(con, mid, actor=principal["username"])  # 08 §3: re-run on change


def post_facts(con, principal: dict, mid: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, mid)
    updates = (body or {}).get("updates")
    if not isinstance(updates, dict) or not updates:
        raise authz.ServiceError(422, "validation_failed", "updates{} required")
    _set_facts(con, principal, mid, updates)
    return facts(con, principal, mid)


def intake_questions(con, principal: dict, mid: str) -> dict:
    authz.require(con, principal, authz.READ, mid)
    have = facts(con, principal, mid)["fields"]
    todo = [q for q in INTAKE_QUESTIONS if q["id"] not in have]
    sections = list(dict.fromkeys(q["section"] for q in INTAKE_QUESTIONS))
    done = [s for s in sections if all(q["id"] in have for q in INTAKE_QUESTIONS
                                       if q["section"] == s)]
    return {"current": todo[0] if todo else None, "sections_done": len(done),
            "sections_total": len(sections)}


def intake_answer(con, principal: dict, mid: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, mid)
    qid = (body or {}).get("question_id")
    if qid not in {q["id"] for q in INTAKE_QUESTIONS} or "answer" not in (body or {}):
        raise authz.ServiceError(422, "validation_failed",
                                 "known question_id and answer required")
    _set_facts(con, principal, mid, {qid: body["answer"]})
    return intake_questions(con, principal, mid)


# -- strategy / predictions / flaws ----------------------------------------------

def strategy(con, principal: dict, mid: str, *, limit: int = 50, cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, mid)
    rows = sorted(dossier.read(con, mid, "strategy")["events"],
                  key=lambda ev: ev.get("version") or 0)
    return _page(rows, limit, cursor)


def strategy_diff(con, principal: dict, mid: str, v: int, against: int) -> dict:
    authz.require(con, principal, authz.READ, mid)
    by_v = {ev["version"]: ev for ev in dossier.read(con, mid, "strategy")["events"]}
    if v not in by_v or against not in by_v:
        raise authz.not_found("strategy_version_not_found",
                              f"versions {v} and {against} must both exist")
    a = set(map(str, by_v[against].get("next_actions") or []))
    b = set(map(str, by_v[v].get("next_actions") or []))
    lo, hi = sorted((v, against))
    reasons = [by_v[n]["why_changed"] for n in sorted(by_v) if lo < n <= hi]
    failed = [dict(r) for r in con.execute(
        "SELECT p.prediction_id, p.strategy_version, p.claim, o.actual, o.court_date"
        " FROM predictions p JOIN outcomes o ON o.prediction_id=p.prediction_id"
        " WHERE p.matter_id=? AND o.match=0 AND p.strategy_version>=?"
        " AND p.strategy_version<?", (mid, lo, hi)).fetchall()]
    return {"changes": [{"op": "added", "action": x} for x in sorted(b - a)]
            + [{"op": "removed", "action": x} for x in sorted(a - b)],
            "reasons": reasons, "failed_predictions": failed}


def predictions(con, principal: dict, mid: str, *, limit: int = 50,
                cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, mid)
    reg = dossier.read(con, mid, "predictions")
    open_ids = set(reg["unresolved"])
    rows = [dict(ev, resolved=ev.get("prediction_id") not in open_ids)
            for ev in reg["events"]]
    return _page(rows, limit, cursor)


def flaws(con, principal: dict, mid: str, *, state: str = "", severity: str = "",
          limit: int = 50, cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, mid)
    latest: dict[str, dict] = {}
    for ev in dossier.read(con, mid, "flaws")["events"]:
        if ev.get("flaw_id"):
            latest[str(ev["flaw_id"])] = ev          # last status per flaw_id wins
    rows = [ev for ev in latest.values()
            if (not state or ev.get("status") == state)
            and (not severity or ev.get("severity") == severity)]
    return _page(rows, limit, cursor)


# -- hearing / debrief --------------------------------------------------------------

def hearing_pack(con, principal: dict, mid: str) -> dict:
    """Read projection only (plan §1): no document generation."""
    authz.require(con, principal, authz.READ, mid)
    fl = dossier.read(con, mid, "flaws")
    rehearsals = [dict(r) for r in con.execute(
        "SELECT execution_id, state, started_at FROM executions WHERE matter_id=?"
        " AND input_task_text LIKE '/mock-hearing%' ORDER BY started_at", (mid,))]
    return {"sections": {"strategy": dossier.read(con, mid, "strategy")["latest"],
                         "deadlines": dossier.read(con, mid, "deadlines")["deadlines"],
                         "open_flaws": fl["open"]},
            "checklist": [{"item": "no open blocking flaws", "ok": not fl["gate_blocked"]}],
            "rehearsals": rehearsals}


def mock_hearing(con, principal: dict, mid: str) -> dict:
    from harness.service import executions
    ex = executions.create(con, principal, mid, {"task_text": "/mock-hearing"})
    return {"rehearsal_id": ex["execution_id"]}


def debrief_questions(con, principal: dict, mid: str) -> list[dict]:
    authz.require(con, principal, authz.READ, mid)
    return DEBRIEF_QUESTIONS


def post_debrief(con, principal: dict, mid: str, body: dict) -> dict:
    authz.require(con, principal, WRITE, mid)
    answers = (body or {}).get("answers")
    if not isinstance(answers, dict):
        raise authz.ServiceError(422, "validation_failed", "answers{} required")
    try:
        return debrief.ingest_court_event(con, mid, answers, actor=principal["username"])
    except RuntimeError as exc:
        raise _bad(exc) from None


# -- deadlines / lawyer-now / closure ------------------------------------------------

def deadline_list(con, principal: dict, mid: str, *, limit: int = 50,
                  cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, mid)
    deadlines.sentinel(con, mid, actor="sentinel")
    return _page(dossier.read(con, mid, "deadlines")["deadlines"], limit, cursor)


def lawyer_now_read(con, principal: dict, mid: str) -> dict:
    authz.require(con, principal, authz.READ, mid)
    res = lawyer_now.evaluate(con, mid, actor="safety")
    return {"state": "flagged" if res["lawyer_now"] else "clear",
            "triggers": res["rules"], "help": []}


def closure_checklist(con, principal: dict, mid: str) -> dict:
    authz.require(con, principal, authz.READ, mid)
    cur = statemachine.state(con, mid)
    pending = con.execute("SELECT COUNT(*) AS c FROM approvals WHERE matter_id=?"
                          " AND state='pending'", (mid,)).fetchone()["c"]
    items = [
        {"item": "case reached a closable stage",
         "ok": "CLOSED" in statemachine.TRANSITIONS.get(cur or "", set())},
        {"item": "no pending approvals", "ok": pending == 0},
        {"item": "no open blocking flaws",
         "ok": not dossier.read(con, mid, "flaws")["gate_blocked"]},
        {"item": "every prediction resolved",
         "ok": not dossier.read(con, mid, "predictions")["unresolved"]},
    ]
    return {"items": items, "eligible": all(i["ok"] for i in items)}


def close(con, principal: dict, mid: str, body: dict) -> dict:
    """202 {approval}: the close is an approval of kind matter.close; approving
    it transitions the case to CLOSED (catalog.decide)."""
    authz.require(con, principal, WRITE, mid)
    if not closure_checklist(con, principal, mid)["eligible"]:
        raise authz.ServiceError(409, "invalid_transition",
                                 "closure checklist not satisfied")
    apid = f"ap-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "INSERT INTO approvals(approval_id, matter_id, execution_id, task_id, kind,"
            " request_payload_json, state, requested_at)"
            " VALUES(?,?,'','','matter.close',?,'pending',?)",
            (apid, mid, json.dumps({"note": (body or {}).get("note") or ""}), _now()))
        audit.append(con, matter_id=mid, actor=principal["username"],
                     action="close.requested", target=apid)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"approval": dict(con.execute("SELECT * FROM approvals WHERE approval_id=?",
                                         (apid,)).fetchone())}
