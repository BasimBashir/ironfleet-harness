"""M8 T1: the API serves the built web client at / (API routes and OpenAPI
untouched), and the worker drains executions with the named harbour-freight
demo body — the moot stage still goes through the real mechanical pre-pass and
records its verdict, so the filing approval guard (M6) is exercised, not skipped."""
from __future__ import annotations

import json
import time

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from harness.service import auth, system
    monkeypatch.setattr(auth, "_ITER", 1000)
    root = tmp_path / "store"
    root.mkdir()
    con = system.open_db(root)
    uid = auth.create_user(con, "admin", "pw", role_id="admin")
    con.close()
    return root, {"user_id": uid, "username": "admin", "role_id": "admin"}


def _dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / "index.html").write_text("<!doctype html><div id=root>M8-SHELL</div>",
                                  encoding="utf-8")
    return d


def test_web_client_served_at_root_api_unchanged(store, tmp_path):
    from fastapi.testclient import TestClient

    from harness.api.app import create_app
    root, _ = store
    bare = create_app(root)
    web = create_app(root, web_dist=_dist(tmp_path))
    assert web.openapi()["paths"] == bare.openapi()["paths"]
    with TestClient(web) as c:
        r = c.get("/")
        assert r.status_code == 200 and "M8-SHELL" in r.text
        assert r.headers["cache-control"] == "no-cache"   # an update must show at once
        miss = c.get("/api/v1/no-such-route")
        assert miss.status_code == 404 and "error" in miss.json()
        assert c.get("/healthz").status_code == 200


def test_no_web_dist_means_no_static_mount(store):
    from fastapi.testclient import TestClient

    from harness.api.app import create_app
    root, _ = store
    with TestClient(create_app(root, web_dist=None)) as c:
        r = c.get("/")
        assert r.status_code == 404 and "error" in r.json()


def _pipeline_execution(root, adm):
    from harness.service import executions, matters, system
    con = system.open_db(root)
    try:
        mid = matters.create(con, adm, {"title": "Harbour Freight"})["matter_id"]
        plan = "```plan\nfilings|clerk|draft the roadmap\nmoot|clerk|moot it\nadvice|clerk|advise\n```"
        eid = executions.create(con, adm, mid, {"task_text": "recover the debt",
                                                "plan_block": plan})["execution_id"]
        # the moot stage carries the M6 gate + filing approval, as legal_pipeline.yaml does
        stages = json.loads(con.execute("SELECT compiled_plan_json FROM executions"
                                        " WHERE execution_id=?", (eid,)).fetchone()[0])
        for s in stages:
            if s["stage"] == "moot":
                s.update({"gate": "moot", "approval": "filing"})
        con.execute("UPDATE executions SET compiled_plan_json=? WHERE execution_id=?",
                    (json.dumps(stages), eid))
        con.execute("UPDATE tasks SET approval_kind='filing' WHERE execution_id=?"
                    " AND key='moot'", (eid,))
        return mid, eid
    finally:
        con.close()


def test_demo_body_parks_on_filing_after_a_recorded_moot_pass(store):
    from harness.service import worker
    from harness.moot.gate import last_verdict
    from harness.service import approvals, system
    root, adm = store
    mid, eid = _pipeline_execution(root, adm)

    worker.drain(root, worker.demo_body(root))
    con = system.open_db(root)
    try:
        ex = con.execute("SELECT state FROM executions WHERE execution_id=?", (eid,)).fetchone()
        assert ex["state"] == "waiting_human"
        v = last_verdict(con, mid, eid)
        assert v and v["verdict"] == "PASSED"
        actor = con.execute("SELECT actor FROM audit_events WHERE action='moot.verdict'"
                            " AND matter_id=?", (mid,)).fetchone()["actor"]
        assert "demo" in actor                    # never passes for a real moot round
        apr = con.execute("SELECT approval_id, kind FROM approvals WHERE execution_id=?",
                          (eid,)).fetchone()
        assert apr["kind"] == "filing"
        summary = con.execute("SELECT result_summary FROM tasks WHERE execution_id=?"
                              " AND key='filings'", (eid,)).fetchone()[0]
        assert summary.startswith("[demo body")   # labelled, never passed off as agent output
        approvals.decide(con, apr["approval_id"], approve=True, decided_by="admin")
    finally:
        con.close()

    worker.drain(root, worker.demo_body(root))
    con = system.open_db(root)
    try:
        assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                           (eid,)).fetchone()["state"] == "completed"
    finally:
        con.close()


def test_live_body_drives_the_crew_and_registers_deliverables(store, monkeypatch):
    """--worker live: each claimed stage runs through FactoryRunner._run_stage on
    the real driver (faked here), and its named deliverable becomes a pending draft."""
    import re
    from contextlib import nullcontext

    from harness.session import driver as drv
    from harness.session.store import TurnRow
    from harness.service import executions, matters, system, worker
    root, adm = store
    calls = []

    class _Driver:
        def __init__(self, store, base):
            self.base = base

        def open_gate(self):
            return nullcontext()

        def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
            ws = self.base / session_id / agent
            ws.mkdir(parents=True, exist_ok=True)
            return ws

        async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
            calls.append(agent)
            for name in re.findall(r"\bWrite ([\w.-]+\.md)", prompt):
                (self.workspace_for(session_id, agent, matter_ref) / name).write_text(
                    "draft", encoding="utf-8")
            return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                           agent=agent, tools_used=[], output_summary=f"{agent} wrote it",
                           docs_touched=[], trace_refs=[])

    monkeypatch.setattr(drv, "SessionDriver", _Driver)
    con = system.open_db(root)
    mid = matters.create(con, adm, {"title": "Live"})["matter_id"]
    eid = executions.create(con, adm, mid, {
        "task_text": "go", "plan_block": "```plan\nintake|clerk|Write intake-note.md\n```"}
    )["execution_id"]
    con.close()

    bind, d = worker.live_body(root)
    with d.open_gate():
        worker.drain(root, bind)
    con = system.open_db(root)
    try:
        assert calls == ["clerk-stage-intake"]
        assert con.execute("SELECT state FROM executions WHERE execution_id=?",
                           (eid,)).fetchone()["state"] == "completed"
        art = con.execute("SELECT review_state FROM artifacts WHERE matter_id=?",
                          (mid,)).fetchall()
        assert [a["review_state"] for a in art] == ["pending"]
    finally:
        con.close()


def test_two_matters_same_user_get_disjoint_workspaces(store, monkeypatch):
    """Confidentiality regression (2026-11-16): matter B's stages must never see
    matter A's files — not in their own workspace, not as a from-* forward."""
    import re
    from contextlib import nullcontext

    from harness.session import driver as drv
    from harness.session.store import TurnRow
    from harness.session.workspace import agent_workspace
    from harness.service import executions, matters, system, worker
    root, adm = store

    class _Driver:
        def __init__(self, store, base):
            self.base = base

        def open_gate(self):
            return nullcontext()

        def workspace_for(self, session_id, agent, matter_ref, classification="LOCAL_PREFERRED"):
            ws = agent_workspace(self.base, session_id, agent, matter_ref)  # the real guard
            (ws / "matter.json").write_text(json.dumps({"matter_ref": matter_ref}),
                                            encoding="utf-8")  # what sync_mount records
            return ws

        async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
            for name in re.findall(r"\bWrite ([\w.-]+\.md)", prompt):
                (self.workspace_for(session_id, agent, matter_ref) / name).write_text(
                    f"privileged to {matter_ref}", encoding="utf-8")
            return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref, display="",
                           agent=agent, tools_used=[], output_summary="ok",
                           docs_touched=[], trace_refs=[])

    monkeypatch.setattr(drv, "SessionDriver", _Driver)
    plan = ("```plan\nintake|ingestor|Write intake-note.md\n"
            "strategy|strategist|Write case-theory.md\n```")
    con = system.open_db(root)
    mids = [matters.create(con, adm, {"title": t})["matter_id"] for t in ("A", "B")]
    sids = []
    for mid in mids:
        eid = executions.create(con, adm, mid, {"task_text": "go", "plan_block": plan}
                                )["execution_id"]
        sids.append(con.execute("SELECT session_id FROM executions WHERE execution_id=?",
                                (eid,)).fetchone()["session_id"])
    con.close()
    bind, d = worker.live_body(root)
    with d.open_gate():
        worker.drain(root, bind)

    assert sids[0] != sids[1]
    for mid, sid in zip(mids, sids):
        files = list((root / "workspaces" / sid).glob("*/*.md"))
        # both deliverables plus the strategy stage's forward of the intake note
        assert len(files) == 3 and any(f.name.startswith("from-") for f in files)
        assert {f.read_text(encoding="utf-8") for f in files} == {f"privileged to {mid}"}


def test_worker_runs_inside_the_served_app(store):
    from fastapi.testclient import TestClient

    from harness.api.app import create_app
    root, _ = store
    app = create_app(root, worker="demo", worker_poll_s=0.02)
    with TestClient(app) as c:
        tok = c.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
        h = {"Authorization": f"Bearer {tok.json()['token']}"}
        mid = c.post("/api/v1/matters", json={"title": "W"}, headers=h).json()["matter_id"]
        eid = c.post(f"/api/v1/matters/{mid}/executions", headers=h, json={
            "task_text": "go", "plan_block": "```plan\na|clerk|x\nb|clerk|y\n```"}
        ).json()["execution_id"]
        deadline = time.time() + 10
        state = ""
        while time.time() < deadline:
            state = c.get(f"/api/v1/executions/{eid}", headers=h).json()["state"]
            if state == "completed":
                break
            time.sleep(0.05)
        assert state == "completed"


def test_worker_loop_survives_a_refused_park(store):
    # a filing stage with no moot gate: the M6 guard refuses the approval; the
    # execution halts (failed) and the worker keeps serving other executions
    import asyncio

    from harness.service import executions, matters, system, worker
    root, adm = store
    con = system.open_db(root)
    mid = matters.create(con, adm, {"title": "x"})["matter_id"]
    bad = executions.create(con, adm, mid, {"task_text": "t", "plan_block":
                            "```plan\nfilings|clerk|x\nadvice|clerk|y\n```"})["execution_id"]
    con.execute("UPDATE tasks SET approval_kind='filing' WHERE execution_id=? AND key='filings'", (bad,))
    con.close()

    async def go():
        t = asyncio.create_task(worker.loop(root, worker.demo_body(root), poll_s=0.01))
        await asyncio.sleep(0.3)
        c = system.open_db(root)
        good = executions.create(c, adm, mid, {"task_text": "t", "plan_block":
                                 "```plan\na|clerk|x\n```"})["execution_id"]
        c.close()
        await asyncio.sleep(0.5)
        assert not t.done(), "the loop died on a refused park"
        t.cancel()
        return good

    good = asyncio.run(go())
    con = system.open_db(root)
    st = {r[0]: r[1] for r in con.execute("SELECT execution_id, state FROM executions")}
    assert st[bad] == "failed" and st[good] == "completed"
    assert con.execute("SELECT state FROM tasks WHERE execution_id=? AND key='advice'",
                       (bad,)).fetchone()[0] == "pending"        # never ran past the approval
    con.close()
