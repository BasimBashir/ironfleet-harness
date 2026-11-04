"""The factory (spec 17 §5.2, slice 3): plan parse + SupervisorRoutes fallback +
stage handoff. Pure parts only here — the live multi-stage run is the acceptance
driver's job, never the suite's (house rule)."""
from __future__ import annotations

import asyncio
import json
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

def test_fallback_plan_is_the_legal_pipeline_and_names_the_task():
    """User ruling 2026-10-21: one typed prompt runs the WHOLE legal crew — the
    supervisor routes default (two generic stages) cannot produce a legal
    outcome. load_routes itself stays untouched for hybrid intents."""
    plan = fallback_plan("drafting", "LOW", "draft a response")
    assert plan.source == "legal-pipeline"
    assert len(plan.stages) >= 8
    # every stage names the task (the interpolation contract)
    assert all("draft a response" in s["instruction"] for s in plan.stages)


def test_supervisor_routes_still_resolve_for_hybrid_intents():
    from harness.module_e.supervisor import load_routes
    agents = load_routes(Path(__file__).parents[1] / "data" / "module-e" /
                         "supervisor.yaml").resolve("drafting", "LOW")
    assert agents == ["hunter", "clerk"]          # the table is unchanged


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

    def __init__(self, summaries: list[str] | None = None, root: Path | None = None):
        self.calls: list[tuple[str, str, str]] = []
        self.summaries = list(summaries) if summaries else []
        self.workspaces: list[str] = []
        self.jobs: list[tuple[str, str, str]] = []
        # The factory writes the guard's authority file NEXT to the workspace
        # (guard_dir); the fake's workspaces must sit inside tmp_path so a test
        # never writes outside its own tree.
        self.root = root

    def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
        self.workspaces.append(agent)
        return (self.root or Path("/tmp")) / "workspaces" / session_id / agent

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
    driver = _FakeDriver(["found A and B", "drafted it"], root=tmp_path)
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
    driver = _FakeDriver(root=tmp_path)
    runner = FactoryRunner(driver, store=store)
    import asyncio
    # no plan text -> the legal pipeline for a typed goal; every stage lands a row
    rows = asyncio.run(runner.run_task(sid, "m1", "some task", plan_text="not a plan"))
    assert len(rows) >= 8 and rows[0].agent == "ingestor"


def test_runner_writes_stage_agent_file_after_the_sync(tmp_path):
    """F5/P7: the stage agent file must be written into the workspace AFTER
    workspace_for()'s sync_mount, or the next stage's generate_all pass could
    clobber it. The fake records the order the runner used."""
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(root=tmp_path)
    runner = FactoryRunner(driver, store=store)
    import asyncio
    asyncio.run(runner.run_task(sid, "m1", "t", plan_text="```plan\ng|hunter|find it\n```"))
    # The workspace is the one run_turn SPAWNS in — named after the stage file
    # stem, not the bare agent. The old split (md in <agent>\, spawn in <fname>\)
    # left --agent pointing at a persona opencode could not see, and every stage
    # silently fell back to the default agent on the extraction class.
    assert driver.workspaces == ["hunter-stage-g"]


def test_runner_hands_prior_deliverables_forward(tmp_path):
    """The crew's hand-off is FILES, not just summaries: prior stages' md
    deliverables are copied into the next stage's workspace (a stage's cwd is
    its own directory, and cross-workspace reads hit opencode's permission
    wall — the phase-2/3 crews could not read sibling stage output)."""
    import asyncio
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(root=tmp_path)

    class _LocalFake(_FakeDriver):
        def workspace_for(self, session_id, agent, matter_ref,
                          classification="LOCAL_PREFERRED"):
            self.workspaces.append(agent)
            ws = tmp_path / "workspaces" / session_id / agent
            ws.mkdir(parents=True, exist_ok=True)
            return ws

    runner = FactoryRunner(_LocalFake(), store=store)
    prior = tmp_path / "workspaces" / sid / "hunter-stage-x"
    prior.mkdir(parents=True)
    (prior / "precedent-map.md").write_text("the map", encoding="utf-8")
    asyncio.run(runner.run_task(sid, "m1", "t",
                                plan_text="```plan\nd|clerk|write it\n```"))
    copied = tmp_path / "workspaces" / sid / "clerk-stage-d" / \
        "from-hunter-stage-x--precedent-map.md"
    assert copied.read_text(encoding="utf-8") == "the map"


def test_legal_pipeline_is_the_fallback_and_carries_the_task():
    """One prompt -> the whole crew: a typed goal (no plan block) builds the
    legal pipeline with the ask interpolated into every stage instruction."""
    from harness.session.factory import fallback_plan
    plan = fallback_plan("", "HIGH", "see if i can win the case and what to file")
    assert plan.source == "legal-pipeline"
    assert len(plan.stages) >= 8
    assert all("see if i can win the case" in s["instruction"] for s in plan.stages)
    agents = [s["agent"] for s in plan.stages]
    assert agents[0] == "ingestor" and agents[-1] == "auditor"
    assert "clerk" in agents and "adversary" in agents and "evaluator" in agents


def test_pipeline_yaml_agents_all_exist_in_the_scaffold():
    """Drift-guard: every pipeline persona must be a mount scaffold agent, or the
    stage spawn falls back to the default agent (the Task-7 lesson)."""
    import yaml
    from pathlib import Path
    doc = yaml.safe_load(
        (Path(__file__).parents[1] / "data" / "module-e" /
         "legal_pipeline.yaml").read_text(encoding="utf-8"))
    known = {"ingestor", "hunter", "strategist", "adversary", "evaluator",
             "clerk", "citation", "auditor", "negotiator", "wargamer",
             "architect", "verifier", "ambiguity"}
    for spec in doc["pipeline"]:
        assert spec["agent"] in known, f"unknown pipeline agent {spec['agent']}"
        assert "{task}" in spec["instruction"]


def test_run_task_seeds_the_session_digest_into_stage_one(tmp_path):
    """Run-2+'s memory: the digest rides as stage 1's previous-stage summary."""
    import asyncio
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(root=tmp_path)
    runner = FactoryRunner(driver, store=store)
    asyncio.run(runner.run_task(sid, "m1", "assess my case",
                                session_digest="Last checkpoint: map written"))
    first_prompt = driver.calls[0][2]
    assert "prior session" in first_prompt
    assert "Last checkpoint: map written" in first_prompt


# -- the guard's block flag (M1/S4): the stage run owns the authority file -------

def _guard_allowed(tmp_path: Path, sid: str, ws_name: str) -> dict:
    g = tmp_path / "workspaces" / sid / ".ironfleet-guard" / ws_name
    return json.loads((g / "allowed.json").read_text(encoding="utf-8"))


def test_factory_blocks_the_guard_on_verify_stages(tmp_path):
    """M1/S4: verify and filings stage runs write block:true — the guard ENFORCES
    there, not merely annotates. verify is a legal-pipeline stage name."""
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    runner = FactoryRunner(_FakeDriver(root=tmp_path), store=store)
    asyncio.run(runner.run_task(sid, "m1", "t",
                                plan_text="```plan\nverify|citation|check it\n```"))
    assert _guard_allowed(tmp_path, sid, "citation-stage-verify")["block"] is True


def test_factory_leaves_research_stages_annotate_only(tmp_path):
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    runner = FactoryRunner(_FakeDriver(root=tmp_path), store=store)
    asyncio.run(runner.run_task(sid, "m1", "t",
                                plan_text="```plan\nresearch|hunter|find it\n```"))
    assert _guard_allowed(tmp_path, sid, "hunter-stage-research")["block"] is False


def test_matter_guard_block_stages_override_wins(tmp_path):
    """The matter record's guard_block_stages REPLACES the default list — an
    operator blocking on research (or unblocking filings) needs one edit, in the
    served record the proxy already reads."""
    rec = tmp_path / "matters" / "m1"
    rec.mkdir(parents=True)
    (rec / "matter.json").write_text(json.dumps(
        {"matter_ref": "m1", "classification": "LOCAL_PREFERRED",
         "guard_block_stages": ["research"]}), encoding="utf-8")
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    runner = FactoryRunner(_FakeDriver(root=tmp_path), store=store)
    asyncio.run(runner.run_task(sid, "m1", "t",
        plan_text="```plan\nresearch|hunter|find it\nverify|citation|check it\n```"))
    assert _guard_allowed(tmp_path, sid, "hunter-stage-research")["block"] is True
    assert _guard_allowed(tmp_path, sid, "citation-stage-verify")["block"] is False
