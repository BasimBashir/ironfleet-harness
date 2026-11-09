# src/harness/lifecycle/deadlines.py — the kernel-only deadline register + sentinel (M5).
# Ported from ironfleet-legal/mcp/server.py::t_deadline_register: a caller-supplied
# `due` is REFUSED outright; kind=filing -> court_filing_deadline, kind=statutory_demand
# -> kernel_tools.statutory_demand. Rows carry source="kernel". The sentinel computes
# the reminder ladder as data (T-14/T-7/T-3/T-1) and is the only writer that flips a
# deadline to overdue — setting cases.needs_restrategy=1 in the same transaction
# (the §3.4 "missed deadline -> re-strategy immediately" trigger).
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from harness.lifecycle import dossier
from harness.module_e import post_judgment
from harness.module_e.kernel_tools import statutory_demand
from harness.module_e.vendored.court_calendar import court_filing_deadline
from harness.workflow import audit

_LADDER = (14, 7, 3, 1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register(con, matter: str, what: str, service_date, *, days=None,
             kind: str = "filing", region=None, jurisdiction: str = "nz",
             missed_consequence: str | None = None, actor: str = "orchestrator",
             **kernel_args) -> dict:
    """Register one deadline. The due date is computed by the kernel, never
    supplied: passing `due`/`due_date` raises, exactly like the plugin."""
    if "due" in kernel_args or "due_date" in kernel_args:
        raise RuntimeError("deadlines are kernel-computed: pass service_date "
                           "(+ days, or kind=statutory_demand), never a due date")
    svc = date.fromisoformat(str(service_date))
    if kind == "filing":
        d = court_filing_deadline(svc, int(days), region=region, jurisdiction=jurisdiction)
        rule = (f"court_filing_deadline: {days} working days from service "
                f"{svc.isoformat()} ({jurisdiction})")
    elif kind == "statutory_demand":
        out = statutory_demand({**kernel_args, "service_date": svc.isoformat(),
                                "jurisdiction": jurisdiction})
        d = date.fromisoformat(str(out["compliance_deadline"])[:10])
        rule = f"statutory demand compliance period ({jurisdiction})"
    elif kind == "appeal":
        out = post_judgment.appeal_window(svc.isoformat(), region=region,
                                          jurisdiction=jurisdiction)
        d = date.fromisoformat(out["due"])
        rule = out["rule_ref"] or f"appeal window ({jurisdiction})"
    elif kind == "settlement":
        if days is None:
            raise RuntimeError("kind=settlement needs days (milestone offset)")
        out = post_judgment.settlement_milestone(svc.isoformat(), int(days),
                                                 region=region,
                                                 jurisdiction=jurisdiction)
        d = date.fromisoformat(out["due"])
        rule = out["rule_ref"] or f"settlement milestone ({jurisdiction})"
    else:
        raise RuntimeError(f"unknown deadline kind: {kind!r} "
                           "(filing | statutory_demand | appeal | settlement)")
    row = dossier.append(con, matter, "deadlines",
                         {"what": what, "due": d.isoformat(), "rule": rule,
                          "source": "kernel", "service_date": svc.isoformat(),
                          "kind": kind, "status": "open",
                          "missed_consequence": missed_consequence},
                         actor=actor)
    return {"registered": True, "due": d.isoformat(), "rule": rule, "row": row}


def _status(due: str, today: date) -> str:
    d = date.fromisoformat(str(due))
    if d < today:
        return "overdue"
    if d <= today + timedelta(days=7):
        return "due_soon"
    return "open"


def sentinel(con, matter: str, *, today: date | None = None,
             actor: str = "sentinel") -> dict:
    """The deadline sentinel: compute the reminder ladder (data, not a timer) and
    flip any open deadline whose `due` < today to overdue, setting
    cases.needs_restrategy=1 in the same transaction."""
    t = today or date.today()
    out: dict = {"matter": matter, "today": t.isoformat(), "rungs": {},
                 "due_soon": [], "overdue": []}
    rows = con.execute("SELECT * FROM deadlines WHERE matter_id=?"
                       " ORDER BY due", (matter,)).fetchall()
    con.execute("BEGIN IMMEDIATE")
    try:
        for r in rows:
            due = date.fromisoformat(r["due"])
            days_left = (due - t).days
            rung = next((f"T-{n}" for n in _LADDER if days_left <= n and days_left >= 0),
                        None)
            if rung:
                out["rungs"].setdefault(rung, []).append(r["deadline_id"])
            status = _status(r["due"], t)
            if status == "due_soon":
                out["due_soon"].append({"deadline_id": r["deadline_id"],
                                        "what": r["what"], "due": r["due"],
                                        "days_left": days_left})
            if status == "overdue" and r["status"] != "overdue":
                con.execute("UPDATE deadlines SET status='overdue' WHERE deadline_id=?",
                            (r["deadline_id"],))
                has_case = con.execute("SELECT 1 FROM cases WHERE matter_id=?",
                                       (matter,)).fetchone()
                if has_case:
                    con.execute("UPDATE cases SET needs_restrategy=1, updated_at=?"
                                " WHERE matter_id=?", (_now(), matter))
                audit.append(con, matter_id=matter, actor=actor,
                             action="deadline.overdue", target=r["deadline_id"],
                             inputs_digest=json.dumps(
                                 {"what": r["what"], "due": r["due"]}, sort_keys=True))
                out["overdue"].append({"deadline_id": r["deadline_id"],
                                       "what": r["what"], "due": r["due"],
                                       "missed_consequence": r["missed_consequence"]})
            elif status == "overdue":
                out["overdue"].append({"deadline_id": r["deadline_id"],
                                       "what": r["what"], "due": r["due"],
                                       "missed_consequence": r["missed_consequence"]})
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    row = con.execute("SELECT needs_restrategy FROM cases WHERE matter_id=?",
                      (matter,)).fetchone()
    out["needs_restrategy"] = bool(row and row["needs_restrategy"])
    return out
