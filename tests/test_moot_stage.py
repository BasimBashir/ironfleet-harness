"""M6 platform: the moot stage as a workflow stage (NEXT_STEPS §9 M6).

FactoryRunner._run_stage sees `gate: moot` and runs the round loop instead of
one turn: mechanical pre-pass, adversarial attack turns, clerk revise,
keep-if-better compare, and a PASSED/CAPPED moot.verdict in the audit chain.
Driven with a fake driver; the corpus is a temp CorpusStore with fake vectors.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from harness.corpus import CorpusStore, DocRecord, chunk_text
from harness.lifecycle import dossier
from harness.moot import gate as moot_gate
from harness.session.factory import FactoryRunner
from harness.session.store import SessionStore, TurnRow
from harness.workflow.db import connect
from harness.workflow import orchestrator

MATTER = "m1"
DOC = "filings-roadmap.md"


def _fake_embed(texts):
    return [[float((ord(t[i % len(t) or 1]) + i) % 17) for i in range(64)]
            for t in texts]


class _MootDriver:
    """Records calls; answers per call index. The workspace dirs are real so the
    clerk's revise turn can actually write the document under test."""

    def __init__(self, summaries, root):
        self.calls: list[tuple[str, str]] = []
        self.summaries = list(summaries)
        self.root = root

    def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
        ws = self.root / "workspaces" / session_id / agent
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
        self.calls.append((agent, prompt))
        i = len(self.calls) - 1
        text = self.summaries[i] if i < len(self.summaries) else ""
        return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                       agent=agent, tools_used=[], output_summary=text,
                       docs_touched=[], trace_refs=[])


def _store(root: Path) -> CorpusStore:
    store = CorpusStore(root / "corpus.sqlite3")
    text = ("The High Court Rules 2016 govern filing. A proceeding is commenced by "
            "filing a statement of claim in the High Court registry. Service of the "
            "claim on the defendant starts the response period under the rules.")
    doc = DocRecord(doc_id="doc-rules", text=text, source_name="hcr.md")
    store.ingest(MATTER, doc, vectors=_fake_embed(chunk_text(doc.doc_id, text)),
                 model="fake", provider="fake")
    return store


def _clean_draft() -> str:
    return ("# Filings roadmap\n\n"
            "File the statement of claim in the High Court registry. "
            "\"The High Court Rules 2016 govern filing. A proceeding is commenced "
            "by filing a statement of claim in the High Court registry.\" [E.1.1]\n")


def _flawed_draft() -> str:
    # fabricated authority + unregistered exhibit + wrong deadline context
    return ("# Filings roadmap\n\n"
            "File in the Supreme Court of Atlantis under the Rules of 1842. "
            "See Exhibit Z. The deadline is 2026-01-01, within 99 days of service.\n")


def _run(tmp_path, monkeypatch, summaries, draft, durable=True):
    # monkeypatch, not os.environ: a raw set leaks HARNESS_DURABLE into later
    # test files in the full suite and flips their legacy path to durable.
    store = SessionStore(tmp_path)
    sid = store.new_session(MATTER)
    driver = _MootDriver(summaries, tmp_path)
    runner = FactoryRunner(driver, store=store)
    stage = {"stage": "moot", "agent": "clerk", "gate": "moot",
             "approval": "filing", "instruction": "moot the draft"}
    # the clerk's workspace holds the drafted deliverable under test
    ws = tmp_path / "workspaces" / sid / "clerk-stage-moot"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / DOC).write_text(draft, encoding="utf-8")
    _store(tmp_path)
    if durable:
        monkeypatch.setenv("HARNESS_DURABLE", "1")
        con = connect(tmp_path / "platform.db")
        eid = orchestrator.create_execution(con, MATTER, sid, "t", [stage])
        con.close()
    else:
        monkeypatch.delenv("HARNESS_DURABLE", raising=False)
        eid = None
    row = asyncio.run(runner._run_stage(sid, MATTER, "t", stage, "filings", "drafted"))
    return runner, driver, eid, row


def test_moot_stage_passed_records_verdict_and_parks(tmp_path, monkeypatch):
    """Clean draft, no attacks: two clean rounds -> PASSED moot.verdict; the
    approval stage then parks (approvals.request accepts the PASSED record)."""
    runner, driver, eid, row = _run(tmp_path, monkeypatch, ["", "", "", "revised"], _clean_draft())
    assert row.agent == "clerk"
    con = connect(tmp_path / "platform.db")
    try:
        v = moot_gate.last_verdict(con, MATTER, eid)
        assert v and v["verdict"] == "PASSED" and v["rounds"] >= 2
        # the attack turns ran: opposing-counsel, procedural, evidence, revise
        agents = [c[0] for c in driver.calls]
        assert "opposing-counsel-stage-moot" in agents
        assert "procedural-examiner-stage-moot" in agents
        assert "evidence-examiner-stage-moot" in agents
        assert "clerk-stage-moot" in agents
        # the verdict is in the audit chain and the chain verifies
        from harness.workflow import audit
        ok, bad = audit.verify(con)
        assert ok and bad is None
        actions = [r["action"] for r in con.execute(
            "SELECT action FROM audit_events").fetchall()]
        assert "moot.verdict" in actions
    finally:
        con.close()


def test_moot_stage_capped_raises_and_no_verdict_passed(tmp_path, monkeypatch):
    """Blocking flaws the attacks keep open: after max rounds the stage raises
    (CAPPED), the verdict recorded is CAPPED, and no PASSED record exists — so
    approvals.request would refuse."""
    from harness.workflow.approvals import MootRequired
    monkeypatch.delenv("HARNESS_DURABLE", raising=False)
    attacks = "[CRITICAL] fabricated_case: invented court\n[MAJOR] wrong_deadline: no kernel date"
    summaries = [attacks] * 12 + ["revised"] * 4   # every attack turn re-attacks
    store = SessionStore(tmp_path)
    sid = store.new_session(MATTER)
    driver = _MootDriver(summaries, tmp_path)
    runner = FactoryRunner(driver, store=store)
    stage = {"stage": "moot", "agent": "clerk", "gate": "moot",
             "approval": "filing", "instruction": "moot"}
    ws = tmp_path / "workspaces" / sid / "clerk-stage-moot"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / DOC).write_text(_flawed_draft(), encoding="utf-8")
    _store(tmp_path)
    monkeypatch.setenv("HARNESS_DURABLE", "1")   # monkeypatched: no env leak into later files
    con = connect(tmp_path / "platform.db")
    eid = orchestrator.create_execution(con, MATTER, sid, "t", [stage])
    con.close()
    with pytest.raises(RuntimeError, match="CAPPED"):
        asyncio.run(runner._run_stage(sid, MATTER, "t", stage, "filings", "drafted"))
    con = connect(tmp_path / "platform.db")
    try:
        v = moot_gate.last_verdict(con, MATTER, eid)
        assert v and v["verdict"] == "CAPPED"
        from harness.workflow import approvals
        t = orchestrator.claim(con, "o1", lease_s=60)
        with pytest.raises(MootRequired):
            approvals.request(con, matter_id=MATTER, execution_id=eid,
                              task_id=t["task_id"], kind="filing", payload={})
        assert con.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
        # the flaw ledger carries the mechanical + agent rows
        open_rows = dossier.read(con, MATTER, "flaws")["open"]
        assert open_rows, "flaw ledger must hold the open rows"
    finally:
        con.close()


def test_moot_stage_supersedes_fixed_and_stale_rows(tmp_path, monkeypatch):
    """A stale blocking row from an earlier run and a round-1 attack the clerk
    fixed (not re-raised in round 2) both close as `fixed`: the run PASSES
    instead of every once-filed flaw blocking forever."""
    monkeypatch.setenv("HARNESS_DURABLE", "1")
    store = SessionStore(tmp_path)
    sid = store.new_session(MATTER)
    attack = "[CRITICAL] fabricated_case: invented court"
    driver = _MootDriver([attack, "", "", "revised"] + [""] * 12, tmp_path)
    runner = FactoryRunner(driver, store=store)
    stage = {"stage": "moot", "agent": "clerk", "gate": "moot",
             "approval": "filing", "instruction": "moot"}
    ws = tmp_path / "workspaces" / sid / "clerk-stage-moot"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / DOC).write_text(_clean_draft(), encoding="utf-8")
    _store(tmp_path)
    con = connect(tmp_path / "platform.db")
    eid = orchestrator.create_execution(con, MATTER, sid, "t", [stage])
    dossier.append(con, MATTER, "flaws", {
        "flaw_id": f"F-moot-{MATTER}-old-r0-0", "class": "wrong_deadline",
        "severity": "critical", "doc": DOC, "status": "open", "detector": "moot-check",
        "detail": "stale"})
    con.close()
    asyncio.run(runner._run_stage(sid, MATTER, "t", stage, "filings", "drafted"))
    con = connect(tmp_path / "platform.db")
    try:
        assert moot_gate.last_verdict(con, MATTER, eid)["verdict"] == "PASSED"
        assert dossier.read(con, MATTER, "flaws")["open"] == []
    finally:
        con.close()


def test_moot_stage_pipeline_yaml_has_gate_after_filings():
    """The legal pipeline data: filings no longer carries the approval; the moot
    stage does, with gate: moot, and sits between filings and advice."""
    import yaml
    doc = yaml.safe_load(
        (Path(__file__).parents[1] / "data" / "module-e" /
         "legal_pipeline.yaml").read_text(encoding="utf-8"))
    stages = [s["stage"] for s in doc["pipeline"]]
    assert stages.index("moot") == stages.index("filings") + 1
    by_name = {s["stage"]: s for s in doc["pipeline"]}
    assert by_name["filings"].get("approval") is None
    assert by_name["moot"].get("gate") == "moot"
    assert by_name["moot"].get("approval") == "filing"


def test_deferring_a_statutory_demand_does_not_raise_one(tmp_path):
    """Mac 1.0.1 retest: a roadmap that said "Defer the s 289 statutory demand (do NOT
    serve now)" got a critical wrong_form row it could never revise away -> CAPPED."""
    from harness.moot.objection import objection
    con = connect(tmp_path / "platform.db")
    kinds = lambda text: [o["kind"] for o in objection(
        con, MATTER, str((tmp_path / "d.md").write_text(text, encoding="utf-8")
                         and tmp_path / "d.md"))["objections"]]
    deferred = ("## Step 3 - Defer the s 289 statutory demand (do NOT serve now)\n"
                "4. Defer any s 289 statutory demand until ss 289/241 are confirmed.\n")
    assert "statutory_demand_not_computed" not in kinds(deferred)
    assert "statutory_demand_not_computed" in kinds("Serve a statutory demand for $12,000.\n")


def test_moot_attackers_get_the_draft_in_their_own_workspace(tmp_path, monkeypatch):
    """1.0.1 Windows: most refused reads were moot attackers reaching into the clerk's
    folder. Each attacker now finds the round's draft in its own workspace."""
    _, driver, _, _ = _run(tmp_path, monkeypatch, ["", "", "", "revised"], _clean_draft())
    attackers = {a for a, _ in driver.calls if a != "clerk-stage-moot"}
    assert attackers
    for a in attackers:
        assert list((tmp_path / "workspaces").glob(f"*/{a}/{DOC}")), a
    assert all("already in your workspace" in p for a, p in driver.calls if a in attackers)


def test_a_planned_statutory_demand_is_a_note_not_a_block(tmp_path):
    """1.0.2 Windows test: a roadmap recommending "serve a statutory demand" CAPPED every
    time — only an operator can register the kernel row. It is now a minor ledger row the
    approver sees; the draft is not blocked by it."""
    con = connect(tmp_path / "platform.db")
    p = tmp_path / "d.md"
    p.write_text("B3. Serve the statutory demand on the debtor company.\n", encoding="utf-8")
    r = moot_gate.moot_check(con, MATTER, str(p))
    sd = [f for f in r["flaws"] if f.get("kind") == "statutory_demand_not_computed"]
    assert sd and sd[0]["severity"] == "minor"
    assert not [f for f in r["flaws"] if f.get("kind") == "statutory_demand_not_computed"
                and f["severity"] in ("critical", "material")]
