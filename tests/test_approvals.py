"""M4 commit 2: approval parking — a stage with `approval:` parks the execution
in waiting_human after it completes, survives a db close/reopen (a process
restart), resumes after decide(approve) and ends on decide(reject)."""
from __future__ import annotations

import asyncio

import pytest

from harness.service import approvals as svc_approvals
from harness.workflow import approvals, orchestrator
from harness.workflow.db import connect


def _stages(*specs):
    return [{"stage": k, "agent": f"a-{k}", "instruction": k,
             **({"approval": kind} if kind else {})}
            for k, kind in specs]


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


def _seed_passed_moot(con, eid, verdict="PASSED"):
    """M6: seed the moot.verdict audit record a filing approval requires."""
    from harness.moot.gate import record_verdict
    con.execute("BEGIN IMMEDIATE")
    record_verdict(con, matter_id="m1", execution_id=eid, verdict=verdict,
                   rounds=2, run_id=f"run-{eid}", docs=["filings-roadmap.md"])
    con.execute("COMMIT")


async def test_park_then_approve_resumes_and_finishes(con, tmp_path):
    eid = orchestrator.create_execution(
        con, "m1", "s1", "t", _stages(("draft", "filing"), ("review", None)))
    _seed_passed_moot(con, eid)
    ran: list[str] = []

    async def body(task, prev):
        ran.append(task["key"])
        return f"{task['key']} done"

    await orchestrator.run(con, eid, body, owner="o1", lease_s=60)
    # the approval stage completed, then the execution parked
    assert ran == ["draft"]
    exec_row = con.execute("SELECT state, current_wait_ref FROM executions"
                           " WHERE execution_id=?", (eid,)).fetchone()
    assert exec_row["state"] == "waiting_human" and exec_row["current_wait_ref"]
    pend = svc_approvals.pending(con, "m1")
    assert len(pend) == 1 and pend[0]["kind"] == "filing" and pend[0]["state"] == "pending"
    # nothing claimable while parked
    assert orchestrator.claim(con, "o2", lease_s=60) is None

    # "restart": close and reopen the db file, still parked, nothing claimable
    con.close()
    con2 = connect(tmp_path / "platform.db")
    assert con2.execute("SELECT state FROM executions WHERE execution_id=?",
                        (eid,)).fetchone()["state"] == "waiting_human"
    assert orchestrator.claim(con2, "o2", lease_s=60) is None
    assert len(svc_approvals.pending(con2, "m1")) == 1

    svc_approvals.decide(con2, pend[0]["approval_id"], approve=True,
                     decided_by="lawyer", note="looks right")
    assert con2.execute("SELECT state FROM executions WHERE execution_id=?",
                        (eid,)).fetchone()["state"] == "executing"
    await orchestrator.run(con2, eid, body, owner="o2", lease_s=60)
    assert ran == ["draft", "review"]
    assert con2.execute("SELECT state FROM executions WHERE execution_id=?",
                        (eid,)).fetchone()["state"] == "completed"
    con2.close()


async def test_reject_cancels_the_execution(con):
    eid = orchestrator.create_execution(
        con, "m1", "s1", "t", _stages(("draft", "filing"), ("review", None)))
    _seed_passed_moot(con, eid)

    async def body(task, prev):
        return "done"

    await orchestrator.run(con, eid, body, owner="o1", lease_s=60)
    pend = svc_approvals.pending(con, "m1")
    svc_approvals.decide(con, pend[0]["approval_id"], approve=False,
                     decided_by="lawyer", note="no")
    row = con.execute("SELECT state FROM executions WHERE execution_id=?", (eid,)).fetchone()
    assert row["state"] == "cancelled"
    assert orchestrator.claim(con, "o2", lease_s=60) is None


def test_double_decide_raises(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages(("a", "filing")))
    _seed_passed_moot(con, eid)
    # park manually the way run() does after an approval stage
    t = orchestrator.claim(con, "o1", lease_s=60)
    orchestrator.complete(con, t["task_id"], "o1", result_summary="drafted")
    approvals.request(con, matter_id="m1", execution_id=eid, task_id=t["task_id"],
                      kind="filing", payload={"stage": "a"})
    con.execute("UPDATE executions SET state='waiting_human', current_wait_ref=?"
                " WHERE execution_id=?", (t["task_id"], eid))
    con.commit()
    aid = svc_approvals.pending(con, "m1")[0]["approval_id"]
    svc_approvals.decide(con, aid, approve=True, decided_by="l", note="")
    with pytest.raises(ValueError):
        svc_approvals.decide(con, aid, approve=False, decided_by="l", note="")


def test_filing_approval_requires_a_passed_moot_record(con):
    """M6: nothing reaches approval without a moot record — request() refuses a
    filing approval with no moot.verdict, with CAPPED, and parks with PASSED."""
    from harness.workflow.approvals import MootRequired
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages(("a", "filing")))
    t = orchestrator.claim(con, "o1", lease_s=60)
    with pytest.raises(MootRequired):
        approvals.request(con, matter_id="m1", execution_id=eid,
                          task_id=t["task_id"], kind="filing", payload={})
    assert con.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    _seed_passed_moot(con, eid, verdict="CAPPED")
    with pytest.raises(MootRequired):
        approvals.request(con, matter_id="m1", execution_id=eid,
                          task_id=t["task_id"], kind="filing", payload={})
    _seed_passed_moot(con, eid, verdict="PASSED")
    aid = approvals.request(con, matter_id="m1", execution_id=eid,
                            task_id=t["task_id"], kind="filing", payload={})
    assert aid.startswith("apr-")


def test_every_decision_lands_in_the_audit_chain(con):
    from harness.workflow import audit
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages(("a", "filing")))
    _seed_passed_moot(con, eid)
    t = orchestrator.claim(con, "o1", lease_s=60)
    orchestrator.complete(con, t["task_id"], "o1", result_summary="d")
    approvals.request(con, matter_id="m1", execution_id=eid, task_id=t["task_id"],
                      kind="filing", payload={})
    con.execute("UPDATE executions SET state='waiting_human' WHERE execution_id=?", (eid,))
    con.commit()
    aid = svc_approvals.pending(con, "m1")[0]["approval_id"]
    svc_approvals.decide(con, aid, approve=True, decided_by="l", note="ok")
    actions = [r["action"] for r in con.execute(
        "SELECT action FROM audit_events ORDER BY rowid").fetchall()]
    assert "approval.requested" in actions and "approval.decided" in actions
    ok, bad = audit.verify(con)
    assert ok and bad is None
