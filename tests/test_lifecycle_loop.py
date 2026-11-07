"""M5 commit 3: the loop — debrief intake, re-strategy versioning, the deadline
sentinel (kernel-only register + reminder ladder + missed->needs_restrategy),
and the lawyer-now detector. Mirrors the plugin grader's two-round flow."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from harness.lifecycle import deadlines, debrief, dossier, lawyer_now, restrategy, statemachine
from harness.module_e.vendored.court_calendar import court_filing_deadline
from harness.workflow import audit
from harness.workflow.db import connect

MATTER = "harbour-freight"


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


@pytest.fixture
def case(con):
    statemachine.transition(con, MATTER, "INTAKE")
    for s in ("ASSESS", "STRATEGY", "PRE_ACTION", "DRAFT", "MOOT", "APPROVE",
              "FILE_SERVE", "AWAIT", "RESPOND", "HEARING_PREP", "COURT"):
        statemachine.transition(con, MATTER, s)
    return con


# -- debrief -------------------------------------------------------------------

def test_ingest_requires_date(case):
    with pytest.raises(RuntimeError):
        debrief.ingest_court_event(case, MATTER, {"event_type": "minute"})


def test_round1_diff_carries_all_unresolved_and_walks_states(case):
    dossier.append(case, MATTER, "predictions",
                   {"prediction_id": "p1", "strategy_version": 1, "claim": "immediate"})
    dossier.append(case, MATTER, "predictions",
                   {"prediction_id": "p2", "strategy_version": 1, "claim": "judgment"})
    d = debrief.ingest_court_event(case, MATTER, {
        "event_type": "minute", "date": "2026-11-05",
        "judge_said": "judgment $126,000; 20 working days",
        "orders": ["payment within 20 working days"]})
    assert d["open_count"] == 2
    assert [e["prediction_id"] for e in d["diff"]] == ["p1", "p2"]
    assert d["court_said"] if False else d["diff"][0]["court_said"]["date"] == "2026-11-05"
    assert statemachine.state(case, MATTER) == "RE_STRATEGY"
    ev = dossier.read(case, MATTER, "court_events")["events"][-1]
    assert ev["event_date"] == "2026-11-05"
    assert ev["payload"]["judge_said"].startswith("judgment $126,000")


def test_record_outcome_resolves_prediction(case):
    dossier.append(case, MATTER, "predictions",
                   {"prediction_id": "p1", "strategy_version": 1, "claim": "c"})
    debrief.record_outcome(case, MATTER, "p1", match=False,
                           actual="20 working days, not immediately",
                           court_date="2026-11-05")
    out = dossier.read(case, MATTER, "predictions")
    assert out["unresolved"] == []
    o = dossier.read(case, MATTER, "outcomes")["events"][0]
    assert o["match"] == 0 and o["court_date"] == "2026-11-05"


# -- re-strategy ---------------------------------------------------------------

def test_cut_strategy_versions_and_requires_why(case):
    debrief.ingest_court_event(case, MATTER, {"date": "2026-11-05"})
    with pytest.raises(RuntimeError):
        restrategy.cut_strategy(case, MATTER, "s2.md", "   ")
    r = restrategy.cut_strategy(case, MATTER, "s2.md", "court refused immediacy",
                                ["watch the window"])
    assert r["version"] == 1  # first cut from a case with no strategy yet
    r2 = restrategy.cut_strategy(case, MATTER, "s3.md", "short-paid", [])
    assert r2["version"] == 2
    assert dossier.read(case, MATTER, "strategy")["versions"] == [1, 2]


def test_cut_strategy_refused_outside_replan_states(con):
    statemachine.transition(con, MATTER, "INTAKE")
    with pytest.raises(RuntimeError):
        restrategy.cut_strategy(con, MATTER, "s1.md", "why")


# -- deadlines: kernel-only register + sentinel --------------------------------

def test_register_refuses_caller_due(con):
    with pytest.raises(RuntimeError):
        deadlines.register(con, MATTER, "model-invented", "2026-11-05",
                           due="2026-12-01")
    with pytest.raises(RuntimeError):
        deadlines.register(con, MATTER, "x", "2026-11-05", due_date="2026-12-01")


def test_register_filing_matches_kernel(con):
    k = court_filing_deadline(date(2026, 11, 5), 20).isoformat()
    reg = deadlines.register(con, MATTER, "judgment sum payable", "2026-11-05",
                             days=20, missed_consequence="leave to enforce")
    assert reg["due"] == k and reg["row"]["source"] == "kernel"
    assert reg["row"]["kind"] == "filing" and reg["row"]["status"] == "open"
    assert reg["row"]["missed_consequence"] == "leave to enforce"


def test_register_unknown_kind(con):
    with pytest.raises(RuntimeError):
        deadlines.register(con, MATTER, "x", "2026-11-05", kind="vibes")


def test_sentinel_ladder_and_overdue_sets_needs_restrategy(con):
    statemachine.transition(con, MATTER, "INTAKE")
    today = date(2026, 12, 1)
    deadlines.register(con, MATTER, "payment", "2026-11-05", days=20)      # due ~Dec 3
    deadlines.register(con, MATTER, "costs", "2026-11-05", days=10)        # due ~Nov 19 -> overdue
    deadlines.register(con, MATTER, "evidence", "2026-11-05", days=60)     # far out
    out = deadlines.sentinel(con, MATTER, today=today)
    assert out["overdue"] and out["overdue"][0]["what"] == "costs"
    assert out["needs_restrategy"] is True
    row = con.execute("SELECT needs_restrategy FROM cases WHERE matter_id=?",
                      (MATTER,)).fetchone()
    assert row["needs_restrategy"] == 1
    dl = con.execute("SELECT status FROM deadlines WHERE what='costs'").fetchone()
    assert dl["status"] == "overdue"
    a = con.execute("SELECT action FROM audit_events WHERE matter_id=?"
                    " AND action='deadline.overdue'", (MATTER,)).fetchone()
    assert a is not None
    ok, bad = audit.verify(con)
    assert ok and bad is None
    # rungs are data: the ~Dec 3 payment deadline at T-3-ish on Dec 1
    assert any(r.startswith("T-") for r in out["rungs"])


def test_sentinel_no_overdue_no_flag(con):
    statemachine.transition(con, MATTER, "INTAKE")
    deadlines.register(con, MATTER, "far", "2026-11-05", days=90)
    out = deadlines.sentinel(con, MATTER, today=date(2026, 11, 6))
    assert out["overdue"] == [] and out["needs_restrategy"] is False


# -- lawyer-now truth table ------------------------------------------------------

def _set_fact(con, field, value):
    dossier.append(con, MATTER, "facts", {"op": "set", "field": field, "value": value})


def test_lawyer_now_truth_table(con):
    statemachine.transition(con, MATTER, "INTAKE")
    assert lawyer_now.evaluate(con, MATTER)["lawyer_now"] is False
    _set_fact(con, "claim_amount", 126000)
    r = lawyer_now.evaluate(con, MATTER)
    assert r["lawyer_now"] is True and "claim_above_self_help" in r["rules"]
    _set_fact(con, "criminal", True)
    _set_fact(con, "children_involved", True)
    _set_fact(con, "insolvent", True)
    r = lawyer_now.evaluate(con, MATTER)
    assert set(r["rules"]) >= {"criminal_exposure", "family_safety",
                               "user_insolvency", "claim_above_self_help"}
    row = con.execute("SELECT lawyer_now, lawyer_now_reason FROM cases"
                      " WHERE matter_id=?", (MATTER,)).fetchone()
    assert row["lawyer_now"] == 1
    assert "criminal_exposure" in row["lawyer_now_reason"]


def test_lawyer_now_missed_limitation_and_court_order(con):
    statemachine.transition(con, MATTER, "INTAKE")
    deadlines.register(con, MATTER, "limitation period expiry", "2026-11-05", days=5)
    deadlines.sentinel(con, MATTER, today=date(2026, 11, 20))
    debrief_event = {"date": "2026-11-20", "orders": ["costs against the plaintiff"]}
    dossier.append(con, MATTER, "court_events",
                   {"event_type": "minute", "event_date": "2026-11-20",
                    "payload": debrief_event})
    r = lawyer_now.evaluate(con, MATTER, today=date(2026, 11, 20))
    assert "missed_limitation" in r["rules"]
    assert "court_order_against_user" in r["rules"]


def test_two_round_flow_end_to_end(case):
    """The scripted harbour-freight loop, compressed: seed v1 + p1/p2, round 1,
    outcomes, v2 + p3, kernel deadline, round 2, outcome, v3."""
    dossier.append(case, MATTER, "strategy",
                   {"version": 1, "file": "s1.md", "why_changed": "opening",
                    "next_actions": ["prove the debt"]})
    dossier.append(case, MATTER, "predictions",
                   {"prediction_id": "p1", "strategy_version": 1, "claim": "immediate"})
    dossier.append(case, MATTER, "predictions",
                   {"prediction_id": "p2", "strategy_version": 1, "claim": "judgment"})
    d1 = debrief.ingest_court_event(case, MATTER, {
        "event_type": "minute", "date": "2026-11-05",
        "judge_said": "judgment $126,000; 20 working days",
        "orders": ["payment within 20 working days"]})
    assert d1["open_count"] == 2
    debrief.record_outcome(case, MATTER, "p1", False, "20 wd not immediate", "2026-11-05")
    debrief.record_outcome(case, MATTER, "p2", True, "judgment entered", "2026-11-05")
    restrategy.cut_strategy(case, MATTER, "s2.md", "immediacy refused", [])
    dossier.append(case, MATTER, "predictions",
                   {"prediction_id": "p3", "strategy_version": 2, "claim": "pays in full"})
    k1 = court_filing_deadline(date(2026, 11, 5), 20).isoformat()
    reg = deadlines.register(case, MATTER, "judgment sum payable", "2026-11-05", days=20)
    assert reg["due"] == k1
    # round 2: leave to enforce, next_date rides the court event
    d2 = debrief.ingest_court_event(case, MATTER, {
        "event_type": "minute", "date": "2026-12-08",
        "judge_said": "part payment $100,000; balance $26,000; leave granted",
        "orders": ["leave to enforce for $26,000"], "next_date": "2027-02-10"})
    # case is in RE_STRATEGY; COURT->DEBRIEF walk skipped, diff still computed
    assert d2["open_count"] == 1 and d2["diff"][0]["prediction_id"] == "p3"
    debrief.record_outcome(case, MATTER, "p3", False, "part payment only", "2026-12-08")
    restrategy.cut_strategy(case, MATTER, "s3.md", "short-paid within window", [])
    assert dossier.read(case, MATTER, "strategy")["versions"] == [1, 2, 3]
    assert dossier.read(case, MATTER, "predictions")["unresolved"] == []
    dl = dossier.read(case, MATTER, "deadlines")
    assert all(r["source"] == "kernel" for r in dl["deadlines"])
    ev = dossier.read(case, MATTER, "court_events")["events"][-1]
    assert ev["payload"]["next_date"] == "2027-02-10"
