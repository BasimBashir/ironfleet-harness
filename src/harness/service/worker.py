# src/harness/service/worker.py — the served app's execution worker (M8, M7 plan §0.2)
"""drain(root, body): run every claimable task now, through the existing
SQLite-lease orchestrator (D4). loop(): the same on a poll, as one asyncio task
in the API's lifespan. demo_body(root): the NAMED harbour-freight demo stage
body the M8 browser journey runs on (owner ruling 2026-11-09) — every summary is
labelled "[demo body", and the moot stage runs the real mechanical pre-pass and
records its verdict as actor "moot-gate (demo body ...)", so the M6 filing guard
is exercised, never bypassed. The production body (opencode driver lifetime
inside the API process) is the optional live leg, not built here."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from harness.lifecycle import statemachine
from harness.workflow import orchestrator

log = logging.getLogger("harness.worker")

_CASE_DOCS = (Path(__file__).resolve().parents[4] / "ironfleet-legal"
              / "dummy-case-harbour-freight" / "docs")
_DEMO_ROADMAP = """# Filings roadmap (demo body, not agent output)

1. Send the pre-action letter demanding payment of the unpaid invoices.
2. If unpaid when the response period ends, file the statement of claim.
3. Serve the claim and file proof of service.
"""


def _stages(con, execution_id: str) -> list[dict]:
    row = con.execute("SELECT compiled_plan_json FROM executions WHERE execution_id=?",
                      (execution_id,)).fetchone()
    return json.loads(row["compiled_plan_json"]) if row else []


def demo_body(root):
    """A stage body over the plugin's harbour-freight documents (read by path,
    never ingested). Returns bind(con) -> async body(task, prev) -> summary."""
    root = Path(root)
    names = sorted(p.name for p in _CASE_DOCS.glob("*")) if _CASE_DOCS.is_dir() else []

    def bind(con):
        async def body(task, prev_summary):
            eid = task["execution_id"]
            stage = next((s for s in _stages(con, eid) if s["stage"] == task["key"]), {})
            if stage.get("gate") == "moot":
                return _demo_moot(con, root, eid)
            return (f"[demo body, not agent output] {task['key']}: harbour-freight stage"
                    f" completed over {len(names)} case documents ({', '.join(names)}).")
        return body
    return bind


def live_body(root):
    """The production leg: the real crew (opencode driver behind the egress gate)
    runs each claimed stage through FactoryRunner._run_stage — the body run_task
    uses — and registers its named deliverables as pending drafts. Returns
    (bind, driver); the caller holds driver.open_gate() open while serving."""
    from harness.session.driver import SessionDriver
    from harness.session.factory import FactoryRunner, register_deliverables
    from harness.session.store import SessionStore
    root = Path(root)
    store = SessionStore(root)
    driver = SessionDriver(store, base=root / "workspaces")
    runner = FactoryRunner(driver, store=store, mode="shell-drives")

    def bind(con):
        async def body(task, prev_summary):
            eid = task["execution_id"]
            ex = con.execute("SELECT matter_id, session_id, input_task_text FROM executions"
                             " WHERE execution_id=?", (eid,)).fetchone()
            stage = next(s for s in _stages(con, eid) if s["stage"] == task["key"])
            prev = con.execute("SELECT key FROM tasks WHERE execution_id=? AND seq<?"
                               " ORDER BY seq DESC LIMIT 1", (eid, task["seq"])).fetchone()
            row = await runner._run_stage(ex["session_id"], ex["matter_id"],
                                          ex["input_task_text"], stage,
                                          prev["key"] if prev else "", prev_summary)
            register_deliverables(con, ex["matter_id"], eid, stage, driver.workspace_for(
                ex["session_id"], f"{stage['agent']}-stage-{stage['stage']}", ex["matter_id"]))
            return row.output_summary
        return body
    return bind, driver


def _demo_moot(con, root: Path, eid: str) -> str:
    from harness.moot import gate
    matter = con.execute("SELECT matter_id FROM executions WHERE execution_id=?",
                         (eid,)).fetchone()["matter_id"]
    ws = root / "workspaces" / f"demo-{eid}"
    ws.mkdir(parents=True, exist_ok=True)
    doc = ws / "filings-roadmap.md"
    doc.write_text(_DEMO_ROADMAP, encoding="utf-8")

    class _Corpus:                         # moot_check reads only .db_path
        db_path = str(root / "corpus.sqlite3")

    result = gate.moot_check(con, matter, str(doc), store=_Corpus())
    verdict = "PASSED" if result.get("ok") else "CAPPED"
    con.execute("BEGIN IMMEDIATE")
    gate.record_verdict(con, matter_id=matter, execution_id=eid, verdict=verdict,
                        rounds=0, run_id=f"moot-demo-{uuid.uuid4().hex[:8]}",
                        docs=[doc.name],
                        actor="moot-gate (demo body: mechanical pre-pass only)")
    con.execute("COMMIT")
    if verdict != "PASSED":
        raise RuntimeError(f"moot CAPPED: {result.get('blocking_count')} blocking flaws")
    return f"[demo body, not agent output] moot: mechanical pre-pass clean ({doc.name})."


def _first_claimable(con) -> str | None:
    # same ordering claim() uses, so run() starts on the execution it will claim from
    row = con.execute(
        "SELECT t.execution_id FROM tasks t JOIN executions e ON e.execution_id=t.execution_id"
        " WHERE e.state='executing' AND t.state IN ('pending','running')"
        " ORDER BY t.execution_id, t.seq LIMIT 1").fetchone()
    return row["execution_id"] if row else None


def _done(con) -> int:
    return con.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('completed','failed')"
                       ).fetchone()[0]


async def drain_async(root, body_factory) -> None:
    from harness.service import system
    con = system.open_db(Path(root))
    try:
        owner = orchestrator.new_owner()
        while (eid := _first_claimable(con)) is not None:
            before = _done(con)
            await orchestrator.run(con, eid, body_factory(con), owner=owner)
            statemachine.advance_after_run(con, eid)
            if _done(con) == before:       # nothing claimable here (leased elsewhere)
                return
    finally:
        con.close()


def drain(root, body_factory) -> None:
    asyncio.run(drain_async(root, body_factory))


async def loop(root, body_factory, *, poll_s: float = 1.0) -> None:
    while True:
        try:
            await drain_async(root, body_factory)
        except asyncio.CancelledError:
            raise
        except Exception:                                           # noqa: BLE001
            # the orchestrator has already halted that execution (D3); keep serving the rest
            log.exception("worker: execution halted")
        await asyncio.sleep(poll_s)
