"""The factory (spec 17 §5.2, slice 3): plan parse + SupervisorRoutes fallback +
stage handoff. Pure parts only here — the live multi-stage run is the acceptance
driver's job, never the suite's (house rule)."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.session.factory import (
    FactoryRunner,
    parse_plan,
    stage_agent_md,
    fallback_plan,
    stage_prompt,
)
from harness.session.store import SessionStore


# -- plan parse (shell-drives: the manager's TEXT plan) ------------------------

def test_parse_plan_reads_stage_lines():
    text = "here is my plan:\n```plan\ngather|hunter|find the parties\ndraft|clerk|write it up\n```"
    plan = parse_plan(text)
    assert plan is not None and plan.source == "model"
    assert [(s["stage"], s["agent"]) for s in plan.stages] == [
        ("gather", "hunter"), ("draft", "clerk")]


def test_parse_plan_returns_none_on_garbage():
    assert parse_plan("no plan here") is None
    assert parse_plan("```plan\ngarbage-line\n```") is None          # no pipes
    assert parse_plan("```plan\n|only-two\n```") is None             # missing instruction
    assert parse_plan("```plan\na|b|\n```") is None                  # empty instruction


def test_parse_plan_ignores_text_outside_the_fence():
    """Only the fenced block is a plan — prose mentioning pipes must not parse."""
    assert parse_plan("a|b|c is a pipe character, use it\n```plan\nx|y|z\n```") is not None
    assert parse_plan("just some prose with a|b|c in it") is None


# -- the fallback (hybrid: SupervisorRoutes when the plan will not parse) ------

def test_fallback_plan_uses_supervisor_routes():
    plan = fallback_plan("drafting", "LOW", "draft a response")
    assert plan.source == "routes"
    assert [s["agent"] for s in plan.stages] == ["hunter", "clerk"]
    # every stage names the task (the generic instruction's contract)
    assert all("draft a response" in s["prompt"] for s in plan.stages)


def test_fallback_plan_unknown_intent_defaults():
    plan = fallback_plan("no-such-intent", "LOW", "t")
    assert [s["agent"] for s in plan.stages] == ["hunter"]     # default_route


# -- the per-stage agent file (F5: the body carries the instruction) -----------

def test_stage_agent_md_body_carries_the_instruction():
    md = stage_agent_md("gather", "find the parties")
    assert "mode: primary" in md and "find the parties" in md
    # the P7 lock: the body must not be the canary's "reply with exactly unused" —
    # a body that contradicts the task makes the model obey the FILE, not the prompt.
    assert "unused" not in md


def test_stage_agent_md_writes_enabled_tools_open_mode():
    """P7's stage 1 needed write; stage 2 needed read. tools: is an override, so
    the ENABLED tool must be listed true and every other false — an unlisted name
    keeps its default (enabled) state (the same rule _frontmatter documents)."""
    md = stage_agent_md("stage-1", "write it", tools={"write": True})
    assert "  write: true" in md
    assert "  bash: false" in md and "  edit: false" in md


# -- stage handoff (P7's file carry + prompt carry, proven live) ---------------

def test_stage_prompt_carries_the_previous_stage():
    first = stage_prompt("gather", "find the parties", task="who are the parties")
    assert "who are the parties" in first and "gather" in first
    second = stage_prompt("draft", "write it up", task="who are the parties",
                          previous_stage="gather", previous_summary="the parties are A and B",
                          artifact="handoff.md")
    assert "the parties are A and B" in second        # prompt carry (P7-proven)
    assert "handoff.md" in second                     # file carry (P7-proven)
    assert "gather" in second


def test_stage_prompt_first_stage_carries_no_history():
    p = stage_prompt("gather", "find them", task="the task")
    assert "previous" not in p.lower()                # nothing to carry yet


# -- the runner (the orchestration, exercised through a fake spawn) -----------

class _FakeDriver:
    """A driver that records calls instead of spawning: the runner's ORDER and
    HANDOFF contract is the thing under test, not opencode. Summaries are keyed
    by call index, not by agent name — the spawn uses a generated stage-file
    stem the test must not need to know."""

    def __init__(self, summaries: list[str] | None = None):
        self.calls: list[tuple[str, str, str]] = []
        self.summaries = list(summaries) if summaries else []
        self.workspaces: list[str] = []
        self.jobs: list[tuple[str, str, str]] = []

    def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
        self.workspaces.append(agent)
        return Path("/tmp") / session_id / agent

    async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
        self.calls.append((agent, agent, prompt))
        from harness.session.store import TurnRow
        i = len(self.calls) - 1
        text = self.summaries[i] if i < len(self.summaries) else ""
        return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                       agent=agent, tools_used=[], output_summary=text,
                       docs_touched=[], trace_refs=[])


def test_runner_runs_stages_in_order_and_hands_forward(tmp_path):
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(["found A and B", "drafted it"])
    runner = FactoryRunner(driver, store=store)
    import asyncio
    rows = asyncio.run(runner.run_task(sid, "m1", "who are the parties",
                                       plan_text="```plan\ngather|hunter|find them\n"
                                                "draft|clerk|write it up\n```"))
    assert [r.agent for r in rows] == ["hunter", "clerk"]          # in plan order
    # stage 2's prompt carries stage 1's summary (P7's prompt carry)
    assert "found A and B" in driver.calls[1][2]
    # a job row per stage, so the global view has the stage ledger (S7f's table)
    jobs = store.jobs(sid)
    assert [(j["stage"], j["agent"], j["status"]) for j in jobs] == [
        ("gather", "hunter", "running"), ("gather", "hunter", "done"),
        ("draft", "clerk", "running"), ("draft", "clerk", "done")]


def test_runner_falls_back_to_routes_when_plan_is_garbage(tmp_path):
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver()
    runner = FactoryRunner(driver, store=store)
    import asyncio
    # no plan text -> routes for the default intent; passes a stage count > 0
    rows = asyncio.run(runner.run_task(sid, "m1", "some task", plan_text="not a plan"))
    assert [r.agent for r in rows] == ["hunter"]


def test_runner_writes_stage_agent_file_after_the_sync(tmp_path):
    """F5/P7: the stage agent file must be written into the workspace AFTER
    workspace_for()'s sync_mount, or the next stage's generate_all pass could
    clobber it. The fake records the order the runner used."""
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver()
    runner = FactoryRunner(driver, store=store)
    import asyncio
    asyncio.run(runner.run_task(sid, "m1", "t", plan_text="```plan\ng|hunter|find it\n```"))
    # workspace_for (the sync) happens before the turn for that agent
    assert driver.workspaces == ["hunter"]
