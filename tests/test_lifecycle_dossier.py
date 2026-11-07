"""M5 commit 2: the SQL dossier (docs/enterprise/07) — append with boundary
validation + read with the plugin's mechanical projections, ported 1:1 from
ironfleet-legal/mcp/dossier.py onto platform.db."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from harness.lifecycle import dossier
from harness.workflow import audit
from harness.workflow.db import connect

MATTER = "harbour-freight"


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


# -- append validation (the trust boundary) ------------------------------------

def test_append_rejects_bad_matter(con):
    for bad in ("", "a:b", "a/b", "a\\b", None, 5):
        with pytest.raises(RuntimeError):
            dossier.append(con, bad, "facts", {"op": "set", "field": "x", "value": 1})


def test_append_rejects_unknown_entity(con):
    with pytest.raises(RuntimeError):
        dossier.append(con, MATTER, "nope", {})


def test_append_rejects_non_dict_and_non_serialisable(con):
    with pytest.raises(RuntimeError):
        dossier.append(con, MATTER, "facts", ["not", "a", "dict"])
    with pytest.raises(RuntimeError):
        dossier.append(con, MATTER, "facts", {"bad": object()})


def test_append_writes_row_and_audit_in_one_transaction(con):
    row = dossier.append(con, MATTER, "facts",
                         {"op": "set", "field": "claim_amount", "value": 126000},
                         actor="case-manager")
    assert row["field"] == "claim_amount" and row["actor"] == "case-manager"
    n = con.execute("SELECT COUNT(*) c FROM facts WHERE matter_id=?",
                    (MATTER,)).fetchone()["c"]
    assert n == 1
    a = con.execute("SELECT action, target FROM audit_events WHERE matter_id=?",
                    (MATTER,)).fetchone()
    assert a["action"] == "dossier.append" and a["target"] == "facts"
    ok, bad = audit.verify(con)
    assert ok and bad is None


def test_append_rolls_back_audit_when_insert_fails(con):
    # outcomes.prediction_id is UNIQUE: a second outcome for the same prediction
    # must fail the whole transaction — no orphan audit row.
    dossier.append(con, MATTER, "predictions",
                   {"prediction_id": "p1", "strategy_version": 1, "claim": "x"})
    dossier.append(con, MATTER, "outcomes",
                   {"outcome_id": "o1", "prediction_id": "p1", "match": 1,
                    "actual": "yes", "court_date": "2026-11-05"})
    with pytest.raises(Exception):
        dossier.append(con, MATTER, "outcomes",
                       {"outcome_id": "o2", "prediction_id": "p1", "match": 0,
                        "actual": "no", "court_date": "2026-11-05"})
    n = con.execute("SELECT COUNT(*) c FROM audit_events WHERE matter_id=?"
                    " AND action='dossier.append'", (MATTER,)).fetchone()["c"]
    assert n == 2  # only the two successful appends


# -- read projections, ported 1:1 ----------------------------------------------

def test_read_facts_latest_per_field(con):
    dossier.append(con, MATTER, "facts", {"op": "set", "field": "a", "value": 1})
    dossier.append(con, MATTER, "facts", {"op": "set", "field": "a", "value": 2})
    dossier.append(con, MATTER, "facts", {"op": "set", "field": "b", "value": "x"})
    out = dossier.read(con, MATTER, "facts")
    assert out["count"] == 3
    assert out["fields"]["a"]["value"] == 2
    assert out["fields"]["b"]["value"] == "x"


def test_read_strategy_version_chain_and_latest(con):
    for v in (1, 2, 3):
        dossier.append(con, MATTER, "strategy",
                       {"version": v, "file": f"s{v}.md", "why_changed": "r"})
    out = dossier.read(con, MATTER, "strategy")
    assert out["versions"] == [1, 2, 3]
    assert out["latest"]["version"] == 3


def test_read_deadlines_status_vs_today(con):
    today = date.today()
    for due, expect in ((today - timedelta(days=1), "overdue"),
                        (today + timedelta(days=3), "due_soon"),
                        (today + timedelta(days=30), "ok")):
        dossier.append(con, MATTER, "deadlines",
                       {"what": "w", "due": due.isoformat(), "source": "kernel",
                        "status": "open"})
    out = dossier.read(con, MATTER, "deadlines")
    statuses = [d["status"] for d in out["deadlines"]]
    assert statuses == ["overdue", "due_soon", "ok"]
    assert out["today"] == today.isoformat()


def test_read_predictions_unresolved(con):
    dossier.append(con, MATTER, "predictions",
                   {"prediction_id": "p1", "strategy_version": 1, "claim": "c1"})
    dossier.append(con, MATTER, "predictions",
                   {"prediction_id": "p2", "strategy_version": 1, "claim": "c2"})
    dossier.append(con, MATTER, "outcomes",
                   {"outcome_id": "o1", "prediction_id": "p2", "match": 1,
                    "actual": "a", "court_date": "2026-11-05"})
    out = dossier.read(con, MATTER, "predictions")
    assert out["unresolved"] == ["p1"]


def test_read_flaws_last_status_wins_and_gate_blocked(con):
    dossier.append(con, MATTER, "flaws",
                   {"flaw_id": "f1", "class": "citation", "severity": "critical",
                    "doc": "d.md", "status": "open"})
    dossier.append(con, MATTER, "flaws",
                   {"flaw_id": "f1", "class": "citation", "severity": "critical",
                    "doc": "d.md", "status": "fixed"})
    dossier.append(con, MATTER, "flaws",
                   {"flaw_id": "f2", "class": "logic", "severity": "material",
                    "doc": "e.md", "status": "open"})
    out = dossier.read(con, MATTER, "flaws")
    assert out["count"] == 3
    assert [f["flaw_id"] for f in out["open"]] == ["f2"]
    assert out["open_counts"] == {"critical": 0, "material": 1, "minor": 0}
    assert out["gate_blocked"] is True


def test_read_unknown_entity_refused(con):
    with pytest.raises(RuntimeError):
        dossier.read(con, MATTER, "nope")


def test_restart_same_projection(con, tmp_path):
    dossier.append(con, MATTER, "strategy", {"version": 1, "file": "s1", "why_changed": "r"})
    con.close()
    con2 = connect(tmp_path / "platform.db")   # reopen: same file, same state
    try:
        out = dossier.read(con2, MATTER, "strategy")
        assert out["versions"] == [1] and out["latest"]["file"] == "s1"
    finally:
        con2.close()
