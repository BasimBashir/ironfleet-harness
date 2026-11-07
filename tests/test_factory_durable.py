"""M4 commit 3: HARNESS_DURABLE=1 routes FactoryRunner.run_task through the
SQLite-lease orchestrator (D4). Flag unset -> no platform.db, byte-for-byte the
legacy loop (the existing factory tests stay green untouched)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from harness.session.factory import FactoryRunner
from harness.session.store import SessionStore
from harness.workflow import orchestrator
from harness.workflow.db import connect
from harness.service import approvals as svc_approvals


class _FakeDriver:
    """Same shape as test_session_factory._FakeDriver: records calls, returns
    canned summaries keyed by call index."""

    def __init__(self, summaries=None, root=None, fail_on=None):
        self.calls: list[tuple[str, str, str]] = []
        self.summaries = list(summaries) if summaries else []
        self.workspaces: list[str] = []
        self.root = root
        self.fail_on = fail_on or set()

    def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
        self.workspaces.append(agent)
        return (self.root or Path("/tmp")) / "workspaces" / session_id / agent

    async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
        from harness.session.store import TurnRow
        self.calls.append((agent, agent, prompt))
        i = len(self.calls) - 1
        if agent in self.fail_on or f"stage-{self.calls[-1][0]}" in self.fail_on:
            raise RuntimeError("stage blew up")
        text = self.summaries[i] if i < len(self.summaries) else ""
        return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                       agent=agent, tools_used=[], output_summary=text,
                       docs_touched=[], trace_refs=[])


_PLAN = "```plan\ngather|hunter|find them\ndraft|clerk|write it up\nclose|auditor|summarise\n```"


def test_flag_unset_creates_no_platform_db(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_DURABLE", raising=False)
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    runner = FactoryRunner(_FakeDriver(["a", "b", "c"], root=tmp_path), store=store)
    rows = asyncio.run(runner.run_task(sid, "m1", "task", plan_text=_PLAN))
    assert [r.agent for r in rows] == ["hunter", "clerk", "auditor"]
    assert not (tmp_path / "platform.db").exists()


def test_flag_set_hands_summaries_forward_like_the_legacy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_DURABLE", "1")
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(["found A and B", "drafted it", "closed"], root=tmp_path)
    runner = FactoryRunner(driver, store=store)
    rows = asyncio.run(runner.run_task(sid, "m1", "who are the parties", plan_text=_PLAN))
    assert [r.agent for r in rows] == ["hunter", "clerk", "auditor"]
    # same hand-forward contract as the legacy loop: stage 2's prompt carries stage 1's summary
    assert "found A and B" in driver.calls[1][2]
    assert "drafted it" in driver.calls[2][2]
    con = connect(tmp_path / "platform.db")
    try:
        execs = con.execute("SELECT state FROM executions").fetchall()
        assert len(execs) == 1 and execs[0]["state"] == "completed"
        tasks = con.execute("SELECT key, state FROM tasks ORDER BY seq").fetchall()
        assert [(t["key"], t["state"]) for t in tasks] == [
            ("gather", "completed"), ("draft", "completed"), ("close", "completed")]
    finally:
        con.close()


def test_flag_set_halt_on_failure_differs_from_legacy(tmp_path, monkeypatch):
    """D3: the durable path halts on a raising stage; the legacy loop continues."""
    monkeypatch.setenv("HARNESS_DURABLE", "1")
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(["ok", "never"], root=tmp_path,
                         fail_on={"clerk-stage-draft"})
    runner = FactoryRunner(driver, store=store)
    rows = asyncio.run(runner.run_task(sid, "m1", "t", plan_text=_PLAN))
    assert [r.agent for r in rows] == ["hunter"]          # draft raised -> halt, no close
    con = connect(tmp_path / "platform.db")
    try:
        assert con.execute("SELECT state FROM executions").fetchone()["state"] == "failed"
        states = [r["state"] for r in con.execute(
            "SELECT state FROM tasks ORDER BY seq").fetchall()]
        assert states == ["completed", "failed", "pending"]
    finally:
        con.close()


def test_flag_set_with_approval_stage_parks_then_resume_finishes(tmp_path, monkeypatch):
    """The yaml's `approval: filing` rides the stage dict; run_task returns at
    the park, decide(approve) + the resume path finishes the execution."""
    from harness.session.factory import StagePlan
    monkeypatch.setenv("HARNESS_DURABLE", "1")
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(["drafted filing", "reviewed"], root=tmp_path)
    runner = FactoryRunner(driver, store=store)
    plan = StagePlan(stages=[
        {"stage": "draft", "agent": "clerk", "instruction": "write it up",
         "approval": "filing"},
        {"stage": "review", "agent": "auditor", "instruction": "check it"},
    ], source="model")
    monkeypatch.setattr(runner, "plan", lambda *a, **k: plan)

    async def main():
        rows = await runner.run_task(sid, "m1", "t")
        assert [r.agent for r in rows] == ["clerk"]       # parked after the approval stage
        con = connect(tmp_path / "platform.db")
        try:
            eid = con.execute("SELECT execution_id FROM executions").fetchone()["execution_id"]
            assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                               (eid,)).fetchone()["state"] == "waiting_human"
            pend = svc_approvals.pending(con)
            assert len(pend) == 1 and pend[0]["kind"] == "filing"
            svc_approvals.decide(con, pend[0]["approval_id"], approve=True,
                                 decided_by="lawyer", note="ok")
            # the restart path: service/workflows.resume runs whatever is claimable
            from harness.service import workflows
            rows2 = await workflows.resume(runner, sid)
            assert [r.agent for r in rows + rows2] == ["clerk", "auditor"]
            assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                               (eid,)).fetchone()["state"] == "completed"
        finally:
            con.close()
    asyncio.run(main())
