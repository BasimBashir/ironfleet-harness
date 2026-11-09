# mcp/harness/module_e/post_judgment.py — M9 kernels: appeal window, enforcement
# options/issue date, settlement milestones. Every date is computed HERE from the
# jurisdiction pack; a caller-supplied due date is refused, exactly like
# t_deadline_register. Values in nz.json quote the operator-supplied exports
# (Desktop/nz: High Court Rules 2016 r 20.4, r 17.3; Senior Courts Act 2016 s 58).
from __future__ import annotations

from datetime import date, timedelta

from .vendored.court_calendar import add_working_days
from .vendored.jurisdiction_loader import JurisdictionLoader


def _svc(service_date: str) -> date:
    return date.fromisoformat(str(service_date))


def _refuse_due(kwargs: dict) -> None:
    if "due" in kwargs or "due_date" in kwargs:
        raise RuntimeError("deadlines are kernel-computed: pass the event/service "
                           "date, never a due date")


def appeal_window(service_date: str, *, region: str | None = None,
                  jurisdiction: str = "nz", **kwargs) -> dict:
    """Appeal window from the pack (nz: 20 working days, HCR 2016 r 20.4(2)(b))."""
    _refuse_due(kwargs)
    rules = JurisdictionLoader.get_post_judgment_rules(jurisdiction)
    days = rules["appeal_days"]
    if days is None:
        raise RuntimeError(f"pack {jurisdiction!r} carries no appeal section — "
                           "operator supplies it as data first (D-P8)")
    svc = _svc(service_date)
    if rules["appeal_day_type"] == "calendar":
        due = svc + timedelta(days=days)
    else:
        due = add_working_days(svc, days, region, jurisdiction)
    return {"due": due.isoformat(), "days": days,
            "day_type": rules["appeal_day_type"], "rule_ref": rules["appeal_rule_ref"],
            "service_date": svc.isoformat(), "jurisdiction": jurisdiction}


def enforcement_options(jurisdiction: str = "nz") -> dict:
    """The enforcement processes catalogue, straight from the pack (r 17.3(1))."""
    rules = JurisdictionLoader.get_post_judgment_rules(jurisdiction)
    return {"options": rules["enforcement_options"],
            "rule_ref": "High Court Rules 2016 r 17.3(1)"
            if jurisdiction == "nz" else "",
            "issue_rule_ref": rules["enforcement_issue_rule_ref"],
            "jurisdiction": jurisdiction}


def enforcement_issue_date(event_date: str, *, process: str,
                           payment_period_ends: str | None = None,
                           jurisdiction: str = "nz", **kwargs) -> dict:
    """Earliest issue date for an enforcement process. r 17.3(3): no process may
    be issued until the period specified in the judgment for payment has expired —
    so an event date before that period ends is refused, not clamped."""
    _refuse_due(kwargs)
    opts = enforcement_options(jurisdiction)
    codes = {o["code"] for o in opts["options"]}
    if process not in codes:
        raise RuntimeError(f"unknown enforcement process {process!r} "
                           f"(pack offers: {', '.join(sorted(codes)) or 'none'})")
    ev = _svc(event_date)
    if payment_period_ends:
        end = _svc(payment_period_ends)
        if ev < end:
            raise RuntimeError(
                f"r 17.3(3): no enforcement process before the judgment's payment "
                f"period ends {end.isoformat()} (event date {ev.isoformat()})")
    return {"issue_date": ev.isoformat(), "process": process,
            "rule_ref": opts["issue_rule_ref"] or "High Court Rules 2016 r 17.3(3)",
            "jurisdiction": jurisdiction}


def settlement_milestone(service_date: str, days: int, *,
                         region: str | None = None, jurisdiction: str = "nz",
                         **kwargs) -> dict:
    """One settlement performance milestone: calendar/working days per the pack."""
    _refuse_due(kwargs)
    rules = JurisdictionLoader.get_post_judgment_rules(jurisdiction)
    svc = _svc(service_date)
    if rules["settlement_milestone_day_type"] == "working":
        due = add_working_days(svc, int(days), region, jurisdiction)
    else:
        due = svc + timedelta(days=int(days))
    return {"due": due.isoformat(), "days": int(days),
            "day_type": rules["settlement_milestone_day_type"],
            "rule_ref": rules["settlement_milestone_ref"],
            "service_date": svc.isoformat(), "jurisdiction": jurisdiction}


def settlement_track(con, matter: str, labels, *, service_date: str, milestones,
                     region: str | None = None, jurisdiction: str = "nz",
                     actor: str = "case-manager") -> dict:
    """Register every settlement milestone as a kernel deadline (kind=settlement).
    `labels` is display text for the caller; the dates come only from the kernel.
    Platform variant: writes through the SQL dossier (harness.lifecycle.dossier)."""
    from harness.lifecycle import dossier as _dossier
    if len(labels) != len(milestones):
        raise RuntimeError("labels and milestones must have the same length")
    rows = []
    for label, m in zip(labels, milestones):
        out = settlement_milestone(service_date, m["days"], region=region,
                                   jurisdiction=jurisdiction)
        row = {"what": str(m.get("what", label)), "due": out["due"],
               "rule": out["rule_ref"] or "settlement milestone",
               "source": "kernel", "service_date": service_date,
               "kind": "settlement", "status": "open"}
        saved = _dossier.append(con, matter, "deadlines", row, actor=actor)
        rows.append({"due": out["due"], "row": saved})
    return {"registered": len(rows), "rows": rows}
