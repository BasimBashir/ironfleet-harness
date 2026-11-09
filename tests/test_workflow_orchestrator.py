"""M4 commit 1: the SQLite-lease orchestrator (D4, 2026-11-07) — claims, leases,
crash recovery, halt-on-failure (D3) and the derived matter state. Pure sqlite3
against a tmp_path db file; the one live-crash test spawns a real child process
and kills it mid-stage (acceptance point 1)."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness.workflow import orchestrator
from harness.workflow.db import connect


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


def _stages(*keys):
    return [{"stage": k, "agent": f"a-{k}", "instruction": f"do {k}"} for k in keys]


# -- schema -------------------------------------------------------------------

def test_connect_creates_executions_and_tasks(tmp_path):
    c = connect(tmp_path / "platform.db")
    cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)").fetchall()}
    assert {"task_id", "execution_id", "seq", "key", "state", "lease_owner",
            "lease_expires_at", "attempts", "max_attempts", "result_summary"} <= cols
    c.close()


# -- create / claim ------------------------------------------------------------

def test_create_execution_makes_one_pending_task_per_stage(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "the task", _stages("a", "b"))
    rows = con.execute("SELECT seq, key, state FROM tasks WHERE execution_id=?"
                       " ORDER BY seq", (eid,)).fetchall()
    assert [(r["seq"], r["key"], r["state"]) for r in rows] == [
        (1, "a", "pending"), (2, "b", "pending")]
    assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                       (eid,)).fetchone()["state"] == "executing"


def test_claim_takes_lowest_seq_and_gates_on_completion(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a", "b"))
    t1 = orchestrator.claim(con, "owner-1", lease_s=60)
    assert t1["key"] == "a" and t1["state"] == "running"
    # b is not claimable while a is incomplete
    assert orchestrator.claim(con, "owner-2", lease_s=60) is None
    orchestrator.complete(con, t1["task_id"], "owner-1", result_summary="A done")
    t2 = orchestrator.claim(con, "owner-2", lease_s=60)
    assert t2["key"] == "b"


def test_two_owners_race_one_task_exactly_one_wins(tmp_path):
    db = tmp_path / "platform.db"
    c1, c2 = connect(db), connect(db)
    eid = orchestrator.create_execution(c1, "m1", "s1", "t", _stages("a"))
    w1 = orchestrator.claim(c1, "owner-1", lease_s=60)
    w2 = orchestrator.claim(c2, "owner-2", lease_s=60)
    # one of the two got it; the other got nothing (the lease is live)
    got = [w for w in (w1, w2) if w is not None]
    assert len(got) == 1 and got[0]["key"] == "a"
    c1.close(); c2.close()


def test_expired_lease_is_reclaimed_live_lease_is_not(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a"))
    t = orchestrator.claim(con, "dead-owner", lease_s=60)
    assert orchestrator.claim(con, "owner-2", lease_s=60) is None   # lease live
    orchestrator.heartbeat(con, t["task_id"], "dead-owner", lease_s=60)
    # force the lease into the past, then a different owner reclaims it
    con.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                (time.time() - 1, t["task_id"]))
    con.commit()
    t2 = orchestrator.claim(con, "owner-2", lease_s=60)
    assert t2 is not None and t2["lease_owner"] == "owner-2"
    assert t2["attempts"] == 2


def test_heartbeat_by_non_owner_is_refused(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a"))
    t = orchestrator.claim(con, "owner-1", lease_s=60)
    assert orchestrator.heartbeat(con, t["task_id"], "thief", lease_s=60) is False
    row = con.execute("SELECT lease_owner FROM tasks WHERE task_id=?",
                      (t["task_id"],)).fetchone()
    assert row["lease_owner"] == "owner-1"


def test_stale_owner_cannot_complete(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a"))
    t = orchestrator.claim(con, "owner-1", lease_s=60)
    con.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                (time.time() - 1, t["task_id"]))
    con.commit()
    t2 = orchestrator.claim(con, "owner-2", lease_s=60)     # reclaim after expiry
    assert orchestrator.complete(con, t["task_id"], "owner-1",
                                 result_summary="stale") is False
    assert orchestrator.complete(con, t["task_id"], "owner-2",
                                 result_summary="fresh") is True
    row = con.execute("SELECT state, result_summary FROM tasks WHERE task_id=?",
                      (t["task_id"],)).fetchone()
    assert row["state"] == "completed" and row["result_summary"] == "fresh"


def test_max_attempts_exhaustion_fails_task_and_execution(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a"), max_attempts=2)
    t = orchestrator.claim(con, "o1", lease_s=60)
    con.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                (time.time() - 1, t["task_id"]))
    con.commit()
    t2 = orchestrator.claim(con, "o2", lease_s=60)           # attempts -> 2
    con.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                (time.time() - 1, t["task_id"]))
    con.commit()
    assert orchestrator.claim(con, "o3", lease_s=60) is None  # past max -> failed
    row = con.execute("SELECT state FROM tasks WHERE task_id=?", (t["task_id"],)).fetchone()
    assert row["state"] == "failed"
    assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                       (eid,)).fetchone()["state"] == "failed"


def test_stage_failure_halts_later_tasks_stay_pending(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a", "b", "c"))
    t = orchestrator.claim(con, "o1", lease_s=60)
    orchestrator.fail(con, t["task_id"], "o1", error="boom")
    assert orchestrator.claim(con, "o2", lease_s=60) is None
    states = [r["state"] for r in con.execute(
        "SELECT state FROM tasks WHERE execution_id=? ORDER BY seq", (eid,))]
    assert states == ["failed", "pending", "pending"]
    assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                       (eid,)).fetchone()["state"] == "failed"


# -- run() ---------------------------------------------------------------------

async def test_run_executes_in_order_and_hands_prev_summary_forward(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a", "b", "c"))
    seen: list[tuple[str, str]] = []

    async def body(task, prev_summary):
        seen.append((task["key"], prev_summary))
        return f"{task['key']} output"

    await orchestrator.run(con, eid, body, owner="o1", lease_s=60)
    assert [k for k, _ in seen] == ["a", "b", "c"]
    assert seen[0][1] == ""                       # no previous stage yet
    assert seen[1][1] == "a output" and seen[2][1] == "b output"
    assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                       (eid,)).fetchone()["state"] == "completed"


async def test_run_halts_on_body_exception(con):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a", "b"))

    async def body(task, prev_summary):
        if task["key"] == "a":
            raise RuntimeError("stage a blew up")
        return "never"

    await orchestrator.run(con, eid, body, owner="o1", lease_s=60)
    states = [r["state"] for r in con.execute(
        "SELECT state FROM tasks WHERE execution_id=? ORDER BY seq", (eid,))]
    assert states == ["failed", "pending"]


# -- matter_state (derived, never stored) --------------------------------------

@pytest.mark.parametrize("exec_state,task_state,expected", [
    ("waiting_human", "completed", "waiting_on_you"),
    ("executing", "running", "running"),
    ("failed", "failed", "blocked"),
    ("completed", "completed", "review_required"),
])
def test_matter_state_truth_table(con, exec_state, task_state, expected):
    eid = orchestrator.create_execution(con, "m1", "s1", "t", _stages("a"))
    con.execute("UPDATE executions SET state=? WHERE execution_id=?", (exec_state, eid))
    con.execute("UPDATE tasks SET state=? WHERE execution_id=?", (task_state, eid))
    con.commit()
    assert orchestrator.matter_state(con, "m1") == expected


def test_matter_state_with_no_executions_is_draft(con):
    assert orchestrator.matter_state(con, "m1") == "draft"


# -- acceptance 1: kill -9 mid-pipeline, restart resumes without double dispatch --

def test_kill9_mid_pipeline_resumes_without_double_dispatch(tmp_path):
    db = tmp_path / "platform.db"
    log = tmp_path / "stages.log"
    child = tmp_path / "child.py"
    child.write_text(
        "import sys, time, asyncio\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from harness.workflow import orchestrator\n"
        "from harness.workflow.db import connect\n"
        "con = connect(sys.argv[2])\n"
        "eid = orchestrator.create_execution(con, 'm1', 's1', 't', [\n"
        "    {'stage': k, 'agent': 'a', 'instruction': k} for k in ('s1', 's2', 's3')])\n"
        "async def body(task, prev):\n"
        "    with open(sys.argv[3], 'a', encoding='utf-8') as f:\n"
        "        f.write('start:' + task['key'] + '\\n')\n"
        "    if task['key'] == 's2':\n"
        "        time.sleep(300)          # killed here, mid-stage\n"
        "    with open(sys.argv[3], 'a', encoding='utf-8') as f:\n"
        "        f.write('done:' + task['key'] + '\\n')\n"
        "    return task['key'] + ' done'\n"
        "asyncio.run(orchestrator.run(con, eid, body, owner='child', lease_s=1))\n",
        encoding="utf-8")
    src = str(Path(__file__).parents[1] / "src")
    proc = subprocess.Popen([sys.executable, str(child), src, str(db), str(log)])
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            if log.exists() and "start:s2" in log.read_text(encoding="utf-8"):
                break
            time.sleep(0.2)
        else:
            proc.kill()
            pytest.fail("child never reached stage s2")
        proc.kill()                       # TerminateProcess on Windows == SIGKILL
        proc.wait(timeout=10)
        time.sleep(1.5)                   # lease_s=1 expires
        # restart: a fresh owner runs whatever is claimable
        con = connect(db)
        eid = con.execute("SELECT execution_id FROM executions").fetchone()["execution_id"]

        async def body(task, prev):
            with log.open("a", encoding="utf-8") as f:
                f.write(f"start:{task['key']}\n")
            with log.open("a", encoding="utf-8") as f:
                f.write(f"done:{task['key']}\n")
            return task["key"] + " done"

        asyncio.run(orchestrator.run(con, eid, body, owner="restart", lease_s=60))
        con.close()
    finally:
        if proc.poll() is None:
            proc.kill()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines.count("done:s1") == 1
    assert lines.count("start:s2") == 2          # interrupted stage re-runs once more
    assert lines.count("done:s2") == 1           # and completes exactly once
    assert lines.count("start:s3") == 1 and lines.count("done:s3") == 1


# -- M8: gate survives compilation; a refused park halts (no approval bypass) ----

def test_compiled_plan_keeps_the_moot_gate(con):
    import json
    stages = _stages("filings") + [{"stage": "moot", "agent": "clerk", "instruction": "m",
                                     "gate": "moot", "approval": "filing"}]
    eid = orchestrator.create_execution(con, "m1", "s1", "t", stages)
    plan = json.loads(con.execute("SELECT compiled_plan_json FROM executions WHERE"
                                  " execution_id=?", (eid,)).fetchone()[0])
    assert plan[1]["gate"] == "moot" and "gate" not in plan[0]


async def test_refused_park_halts_the_execution_never_skips_the_approval(con):
    # a filing approval with no PASSED moot record is refused (M6); the stage must not
    # leave the next task claimable, or a restarted worker would run past the approval
    from harness.workflow.approvals import MootRequired
    stages = [{"stage": "moot", "agent": "clerk", "instruction": "m", "approval": "filing"},
              {"stage": "advice", "agent": "clerk", "instruction": "a"}]
    eid = orchestrator.create_execution(con, "m1", "s1", "t", stages)

    async def body(task, prev):
        return "drafted"

    with pytest.raises(MootRequired):
        await orchestrator.run(con, eid, body, owner="o1", lease_s=30)
    assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                       (eid,)).fetchone()["state"] == "failed"
    assert orchestrator.claim(con, "o2", lease_s=30) is None
    assert con.execute("SELECT state FROM tasks WHERE execution_id=? AND key='advice'",
                       (eid,)).fetchone()["state"] == "pending"
