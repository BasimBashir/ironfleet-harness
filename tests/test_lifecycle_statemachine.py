"""M5 commit 2: the §3.1 state machine as data on platform.db — legal jumps
only, audit-logged, survives restart."""
from __future__ import annotations

import pytest

from harness.lifecycle import statemachine
from harness.workflow import audit
from harness.workflow.db import connect

MATTER = "harbour-freight"


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


def test_states_are_the_spec_verbatim():
    assert statemachine.STATES == [
        "INTAKE", "ASSESS", "STRATEGY", "PRE_ACTION", "DRAFT", "MOOT", "APPROVE",
        "FILE_SERVE", "AWAIT", "RESPOND", "HEARING_PREP", "COURT", "DEBRIEF",
        "RE_STRATEGY", "JUDGMENT", "ENFORCE", "APPEAL", "SETTLE", "CLOSED",
    ]


def test_walk_the_chain(con):
    statemachine.transition(con, MATTER, "INTAKE")
    for s in ("ASSESS", "STRATEGY", "PRE_ACTION", "DRAFT", "MOOT", "APPROVE",
              "FILE_SERVE", "AWAIT", "RESPOND", "HEARING_PREP", "COURT",
              "DEBRIEF", "RE_STRATEGY"):
        assert statemachine.transition(con, MATTER, s) == s
    assert statemachine.state(con, MATTER) == "RE_STRATEGY"


def test_illegal_jump_refused_loudly_no_write(con):
    statemachine.transition(con, MATTER, "INTAKE")
    with pytest.raises(RuntimeError):
        statemachine.transition(con, MATTER, "COURT")   # skips the whole chain
    assert statemachine.state(con, MATTER) == "INTAKE"
    with pytest.raises(RuntimeError):
        statemachine.transition(con, MATTER, "NOT_A_STATE")
    assert statemachine.state(con, MATTER) == "INTAKE"


def test_settlement_from_any_state_at_or_after_pre_action(con):
    for start in ("PRE_ACTION", "DRAFT", "FILE_SERVE", "AWAIT", "COURT", "ENFORCE"):
        m = f"m-{start}"
        statemachine.transition(con, m, "INTAKE")
        # walk to `start` along the chain
        chain = statemachine.STATES
        for s in chain[1:chain.index(start) + 1]:
            statemachine.transition(con, m, s)
        assert statemachine.transition(con, m, "SETTLE") == "SETTLE"
        assert statemachine.transition(con, m, "CLOSED") == "CLOSED"


def test_settlement_refused_before_pre_action(con):
    statemachine.transition(con, MATTER, "INTAKE")
    statemachine.transition(con, MATTER, "ASSESS")
    statemachine.transition(con, MATTER, "STRATEGY")
    with pytest.raises(RuntimeError):
        statemachine.transition(con, MATTER, "SETTLE")


def test_transition_writes_audit_row(con):
    statemachine.transition(con, MATTER, "INTAKE", actor="op", note="opened")
    a = con.execute("SELECT action, target, actor FROM audit_events"
                    " WHERE matter_id=?", (MATTER,)).fetchone()
    assert a["action"] == "state.transition" and a["target"] == "INTAKE"
    assert a["actor"] == "op"
    ok, bad = audit.verify(con)
    assert ok and bad is None


def test_restart_same_state(con, tmp_path):
    statemachine.transition(con, MATTER, "INTAKE")
    statemachine.transition(con, MATTER, "ASSESS")
    con.close()
    con2 = connect(tmp_path / "platform.db")
    try:
        assert statemachine.state(con2, MATTER) == "ASSESS"
    finally:
        con2.close()


def test_state_unknown_matter_is_none(con):
    assert statemachine.state(con, "ghost") is None


def _completed_run(con, keys, started_at):
    con.execute("INSERT INTO executions(execution_id, matter_id, state, started_at)"
                " VALUES('ex-1', ?, 'completed', ?)", (MATTER, started_at))
    for n, k in enumerate(keys, 1):
        con.execute("INSERT INTO tasks(task_id, execution_id, seq, key, state)"
                    " VALUES(?, 'ex-1', ?, ?, 'completed')", (f"t{n}", n, k))
    con.commit()


def test_completed_run_walks_the_matter_forward(con):
    _completed_run(con, ["intake", "assess", "strategy"], "2000-01-01T00:00:00+00:00")
    statemachine.transition(con, MATTER, "INTAKE", actor="workflow")
    assert statemachine.advance_after_run(con, "ex-1") == "STRATEGY"


def test_operator_move_during_the_run_wins(con):
    _completed_run(con, ["intake", "assess", "strategy", "filings", "moot"],
                   "2000-01-01T00:00:00+00:00")
    statemachine.transition(con, MATTER, "INTAKE")     # operator, after dispatch
    assert statemachine.advance_after_run(con, "ex-1") == "INTAKE"
