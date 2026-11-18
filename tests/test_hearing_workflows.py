"""M6 step 7: the /hearing-pack and /mock-hearing workflows (NEXT_STEPS §9 M6).

Data files data/module-e/workflows/{hearing_pack,mock_hearing}.yaml are picked by
fallback_plan when the goal starts with the slash command; load_legal_pipeline(name=...)
reads them. One fake-driver run each proves the stages execute end to end.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from harness.session.factory import FactoryRunner, fallback_plan, load_legal_pipeline
from harness.session.store import SessionStore, TurnRow


class _FakeDriver:
    def __init__(self, root: Path):
        self.calls: list[str] = []
        self.root = root

    def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
        ws = self.root / "workspaces" / session_id / agent
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
        self.calls.append(agent)
        # a well-behaved agent writes the deliverable its instruction names
        for name in re.findall(r"\bWrite ([\w.-]+\.md)", prompt):
            (self.root / "workspaces" / session_id / agent / name).write_text("x", encoding="utf-8")
        return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                       agent=agent, tools_used=[], output_summary=f"{agent} done",
                       docs_touched=[], trace_refs=[])


def test_loader_reads_named_workflow_files():
    pack = load_legal_pipeline("hearing_pack")
    mock = load_legal_pipeline("mock_hearing")
    assert [s["agent"] for s in pack] == ["bench", "clerk"]
    assert [s["agent"] for s in mock] == ["hearing-coach"]
    assert all("{task}" in s["instruction"] for s in pack + mock)


def test_slash_goals_pick_the_workflow_files():
    pack = fallback_plan("", "LOW", "/hearing-pack for matter m1")
    mock = fallback_plan("", "LOW", "/mock-hearing m1")
    plain = fallback_plan("drafting", "LOW", "draft a response")
    assert pack.source == "legal-pipeline:hearing_pack"
    assert mock.source == "legal-pipeline:mock_hearing"
    assert plain.source == "legal-pipeline"          # unchanged default
    assert [s["stage"] for s in pack.stages] == ["pack-bench", "pack-assemble"]
    assert [s["stage"] for s in mock.stages] == ["rehearsal"]
    assert all("/hearing-pack for matter m1" in s["instruction"] for s in pack.stages)


def test_hearing_pack_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_DURABLE", raising=False)
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(tmp_path)
    runner = FactoryRunner(driver, store=store)
    rows = asyncio.run(runner.run_task(sid, "m1", "/hearing-pack m1"))
    assert [r.agent for r in rows] == ["bench", "clerk"]
    assert driver.calls == ["bench-stage-pack-bench", "clerk-stage-pack-assemble"]


def test_mock_hearing_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_DURABLE", raising=False)
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _FakeDriver(tmp_path)
    runner = FactoryRunner(driver, store=store)
    rows = asyncio.run(runner.run_task(sid, "m1", "/mock-hearing m1"))
    assert [r.agent for r in rows] == ["hearing-coach"]
    assert driver.calls == ["hearing-coach-stage-rehearsal"]


def test_stage_that_writes_nothing_is_nudged_once_then_flagged(tmp_path, monkeypatch):
    """The live t9 failure: the agent's turn ended on "Now let me read…" with
    citation-check.md unwritten. One nudge turn; still nothing -> the summary
    says [NO DELIVERABLE] instead of passing the stray text off as the result."""
    monkeypatch.delenv("HARNESS_DURABLE", raising=False)

    class _Lazy(_FakeDriver):
        async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
            self.calls.append(agent)
            return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                           agent=agent, tools_used=[], output_summary="Now let me read.",
                           docs_touched=[], trace_refs=[])

    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _Lazy(tmp_path)
    stage = {"stage": "verify", "agent": "citation",
             "instruction": "Write citation-check.md listing VERIFIED citations."}
    row = asyncio.run(FactoryRunner(driver, store=store)._run_stage(
        sid, "m1", "t", stage, "", ""))
    assert driver.calls == ["citation-stage-verify"] * 2
    assert row.output_summary.startswith("[NO DELIVERABLE: citation-check.md not written]")


def test_stage_prompt_names_the_forwarded_files(tmp_path, monkeypatch):
    """The 2026-11-17 Win11 failure: the agent read the sibling intake workspace,
    opencode refused it and ended the turn. The prompt now names the in-cwd copies."""
    monkeypatch.delenv("HARNESS_DURABLE", raising=False)
    prompts = []

    class _Rec(_FakeDriver):
        async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
            prompts.append(prompt)
            return await super().run_turn(session_id, matter_ref, agent, prompt, **kw)

    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    driver = _Rec(tmp_path)
    driver.workspace_for(sid, "ingestor-stage-intake", "m1")
    (tmp_path / "workspaces" / sid / "ingestor-stage-intake" / "case-summary.md").write_text(
        "facts", encoding="utf-8")
    stage = {"stage": "research", "agent": "hunter", "instruction": "Write research-memo.md."}
    asyncio.run(FactoryRunner(driver, store=store)._run_stage(sid, "m1", "t", stage, "", ""))
    assert "from-ingestor-stage-intake--case-summary.md" in prompts[0]
    assert "never from another directory" in prompts[0]
