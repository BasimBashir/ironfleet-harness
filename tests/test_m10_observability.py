"""M10 T2: turn-based chat (the worker answers in-thread when the execution a
message started completes), run events on GET /runs/{rid}, GET /metrics (02 §14:
derived queries over trace.db + the workflow tables; audit.read) and healthz
queue/error keys."""
from __future__ import annotations

from test_api_authz import PLAN, code


def _dispatch(w) -> str:
    r = w.client.post(f"/api/v1/matters/{w.A['mid']}/executions",
                      json={"task_text": "t", "plan_block": PLAN}, headers=w.h("admin"))
    assert r.status_code in (200, 201, 202), r.text
    return r.json()["execution_id"]


def _drain(root):
    from harness.service import worker
    worker.drain(root, worker.demo_body(root))


def test_chat_instruction_in_lead_reply_out(api_world):
    from harness.service import approvals, system
    w, h = api_world, api_world.h("admin")
    cid = w.A["cid"]
    r = w.client.post(f"/api/v1/conversations/{cid}/messages",
                      json={"text": "what is the limitation period?"}, headers=h)
    assert r.status_code in (200, 201, 202), r.text
    eid = r.json()["execution"]["execution_id"]
    _drain(w.root)
    # parks on the filing approval: no reply yet (never answer before completion)
    msgs = w.client.get(f"/api/v1/conversations/{cid}/messages", headers=h).json()["items"]
    assert [m["role"] for m in msgs if m["execution_id"] == eid] == ["user"]
    con = system.open_db(w.root)
    try:
        apid = con.execute("SELECT approval_id FROM approvals WHERE execution_id=?"
                           " AND state='pending'", (eid,)).fetchone()[0]
        approvals.decide(con, apid, approve=True, decided_by="admin")
    finally:
        con.close()
    _drain(w.root)
    msgs = w.client.get(f"/api/v1/conversations/{cid}/messages", headers=h).json()["items"]
    lead = [m for m in msgs if m["execution_id"] == eid and m["role"] == "lead"]
    assert len(lead) == 1, msgs
    assert eid in lead[0]["text"] and "intake" in lead[0]["text"] and "close" in lead[0]["text"]
    ev = w.client.get(f"/api/v1/runs/{eid}", headers=h).json()["events"]
    assert "chat.replied" in {e["type"] for e in ev}


def test_execution_without_a_message_gets_no_reply(api_world):
    from harness.service import system
    w = api_world
    _drain(w.root)                                  # fixture execution: no message row
    con = system.open_db(w.root)
    try:
        assert con.execute("SELECT COUNT(*) FROM messages WHERE role='lead'").fetchone()[0] == 0
    finally:
        con.close()


def test_get_run_carries_its_events(api_world):
    w, h = api_world, api_world.h("admin")
    eid = _dispatch(w)
    _drain(w.root)
    run = w.client.get(f"/api/v1/runs/{eid}", headers=h).json()
    types = [e["type"] for e in run["events"]]
    assert "task.running" in types and "task.completed" in types
    assert all({"id", "ts", "type", "task_id"} <= set(e) for e in run["events"])
    assert any(e["task_id"] for e in run["events"])
    # another run's events never bleed into this one
    other = w.client.get(f"/api/v1/runs/{w.A['eid']}", headers=h).json()["events"]
    assert all(e["id"] not in {x["id"] for x in run["events"]} for e in other)


def test_metrics_shape_and_authz(api_world):
    from harness.service import usage, system
    from harness.trace import DispatchRecord, TraceStore
    w = api_world
    con = system.open_db(w.root)
    try:
        ts = TraceStore(usage._trace_db(con))
    finally:
        con.close()
    for ms, st in ((100, "ok"), (300, "ok"), (900, "error")):
        ts.append(DispatchRecord(matter_ref=w.A["mid"], task_class="t", classification="LOCAL_ONLY",
                                 provider="ollama", model="m1", engine="llama.cpp",
                                 latency_ms=ms, status=st))
    r = w.client.get("/api/v1/metrics", headers=w.h("admin"))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["dispatches"]["total"] == 3 and m["dispatches"]["errors"] == 1
    assert m["dispatches"]["by_engine"] == {"llama.cpp": 3}
    lat = m["latency"][0]
    assert (lat["provider"], lat["model"], lat["n"]) == ("ollama", "m1", 3)
    assert lat["p50_ms"] == 300 and lat["p95_ms"] == 900
    assert m["tasks"]["pending"] >= 1 and "running" in m["tasks"]
    assert m["executions"].get("waiting_human", 0) == 2      # the fixture's parked runs
    for role in ("reader", "editor", "outsider"):
        r = w.client.get("/api/v1/metrics", headers=w.h(role))
        assert (r.status_code, code(r)) == (403, "permission_denied")


def test_metrics_with_no_trace_db(api_world):
    r = api_world.client.get("/api/v1/metrics", headers=api_world.h("admin"))
    assert r.status_code == 200
    assert r.json()["dispatches"] == {"total": 0, "errors": 0, "by_engine": {}}
    assert r.json()["latency"] == []


def test_healthz_reports_queue_depth_and_trace_errors(api_world):
    w = api_world
    assert w.client.get("/healthz").json()["queue_depth"] == 0   # fixture runs are parked
    _dispatch(w)
    body = w.client.get("/healthz").json()
    assert body["queue_depth"] == 1          # one claimable task, nothing else
    assert body["trace_errors"] == 0
