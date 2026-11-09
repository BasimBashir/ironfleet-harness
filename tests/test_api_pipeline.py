"""M7 acceptance (06 Phase 5): the whole pipeline through HTTP only — create
matter -> execution -> the platform worker runs -> approval parks -> approve
via the API -> completes -> SSE shows the sequence. The test body never
touches the db; _worker stands in for the runner process (orchestrator.run
with a fake stage body), exactly as plan §0.2 assigns execution."""
from __future__ import annotations

import asyncio


def _worker(root, eid: str) -> None:
    from harness.service import system
    from harness.workflow import orchestrator
    con = system.open_db(root)

    async def body(task, prev):
        return f"{task['key']} done"

    try:
        asyncio.run(orchestrator.run(con, eid, body, owner="worker-1", lease_s=30))
    finally:
        con.close()


def _in_order(seq: list[str], want: list[str]) -> bool:
    it = iter(seq)
    return all(any(x == w for x in it) for w in want)


def test_pipeline_over_http(api_world):
    c = api_world.client
    tok = c.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    h = {"Authorization": f"Bearer {tok.json()['token']}"}
    mid = c.post("/api/v1/matters", json={"title": "Pipeline"}, headers=h).json()["matter_id"]
    wf = c.post("/api/v1/workflows", headers=h, json={"name": "draft-review", "definition": [
        {"stage": "draft", "agent": "clerk", "instruction": "draft it", "approval": "review"},
        {"stage": "final", "agent": "clerk", "instruction": "finalise"}]})
    assert wf.status_code == 201
    ex = c.post(f"/api/v1/matters/{mid}/executions", headers=h,
                json={"task_text": "go", "workflow_id": wf.json()["workflow_id"]})
    assert ex.status_code == 202 and ex.json()["state"] == "executing"
    eid = ex.json()["execution_id"]

    _worker(api_world.root, eid)
    assert c.get(f"/api/v1/executions/{eid}", headers=h).json()["state"] == "waiting_human"
    assert c.get(f"/api/v1/matters/{mid}", headers=h).json()["state"] == "waiting_on_you"
    pend = c.get(f"/api/v1/matters/{mid}/approvals", headers=h).json()
    assert [a["kind"] for a in pend] == ["review"]

    ok = c.post(f"/api/v1/approvals/{pend[0]['approval_id']}/approve", headers=h,
                json={"note": "lgtm"})
    assert ok.status_code == 200 and ok.json()["state"] == "approved"

    _worker(api_world.root, eid)
    done = c.get(f"/api/v1/executions/{eid}", headers=h).json()
    assert done["state"] == "completed"
    assert [t["state"] for t in done["tasks"]] == ["completed", "completed"]
    assert c.get(f"/api/v1/matters/{mid}", headers=h).json()["state"] == "review_required"

    stream = c.get(f"/api/v1/events?channels=matter:{mid}", headers=h).text
    types = [ln[len("event: "):] for ln in stream.splitlines() if ln.startswith("event: ")]
    assert _in_order(types, ["matter.created", "execution.created", "task.running",
                             "task.completed", "approval.requested", "approval.decided",
                             "task.running", "task.completed", "execution.completed"]), types
