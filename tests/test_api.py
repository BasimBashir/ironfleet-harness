"""M7 contract tests: every endpoint's declared status for an allowed caller,
the error envelope, auth, cursor paging, Idempotency-Key replay/conflict, SSE
replay + heartbeat + live tail, and the committed OpenAPI file (drift fails;
regenerate with UPDATE_OPENAPI=1)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from test_api_authz import ROUTES, call, code

# admin outcomes that are domain answers, not the declared success status
DOMAIN = {"POST /api/v1/executions/{eid}/resume": (409, "invalid_transition"),
          "POST /api/v1/executions/{eid}/redirect": (409, "lease_conflict"),
          "POST /api/v1/matters/{mid}/close": (409, "invalid_transition")}
PAGED = {"GET /api/v1/matters", "GET /api/v1/matters/{mid}/documents",
         "GET /api/v1/matters/{mid}/evidence", "GET /api/v1/matters/{mid}/artifacts",
         "GET /api/v1/audit", "GET /api/v1/approvals",
         "GET /api/v1/conversations/{cid}/messages", "GET /api/v1/matters/{mid}/next-actions",
         "GET /api/v1/matters/{mid}/strategy", "GET /api/v1/matters/{mid}/predictions",
         "GET /api/v1/matters/{mid}/flaws", "GET /api/v1/matters/{mid}/deadlines"}
ENVELOPE = {"code", "message", "details", "trace_id"}


def _declared(app) -> dict:
    """METHOD path -> the declared success status, read from the published spec."""
    return {f"{m.upper()} {path}": int(next(s for s in op["responses"] if s.startswith("2")))
            for path, ops in app.openapi()["paths"].items() for m, op in ops.items()}


@pytest.mark.parametrize("key", sorted(k for k, v in ROUTES.items() if v[0] != "public"))
def test_contract_allowed_caller(api_world, key):
    w = api_world
    r = call(w, key, "admin", w.A)
    if key in DOMAIN:
        assert (r.status_code, code(r)) == DOMAIN[key], r.text
        assert set(r.json()["error"]) == ENVELOPE
        return
    assert r.status_code == _declared(w.app)[key], (key, r.text)
    if key in PAGED:
        assert {"items", "next_cursor"} <= set(r.json()), key


def test_healthz_needs_no_token(api_world):
    r = api_world.client.get("/healthz")
    assert r.status_code == 200 and r.json()["stores"] == "ok"


def test_error_envelope_shapes(api_world):
    c, h = api_world.client, api_world.h("admin")
    for r, status, want in (
            (c.get("/api/v1/matters"), 401, "unauthenticated"),
            (c.get("/api/v1/nope", headers=h), 404, "not_found"),
            (c.post("/api/v1/matters", json={}, headers=h), 422, "validation_failed"),
            (c.get("/api/v1/matters?limit=999", headers=h), 422, "validation_failed"),
            (c.post(f"/api/v1/matters/{api_world.A['mid']}/state", json={"to": "queued"},
                    headers=h), 409, "invalid_transition")):
        assert r.status_code == status and set(r.json()["error"]) == ENVELOPE
        assert r.json()["error"]["code"] == want


def test_login_me_refresh(api_world):
    c = api_world.client
    bad = c.post("/api/v1/auth/login", json={"username": "admin", "password": "no"})
    assert (bad.status_code, code(bad)) == (401, "invalid_credentials")
    tok = c.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"}).json()
    h = {"Authorization": f"Bearer {tok['token']}"}
    me = c.get("/api/v1/auth/me", headers=h).json()
    assert me["user"]["username"] == "admin" and "audit.read" in me["permissions"]
    new = c.post("/api/v1/auth/refresh", headers=h).json()["token"]
    assert c.get("/api/v1/auth/me", headers=h).status_code == 401          # rotated out
    assert c.get("/api/v1/auth/me",
                 headers={"Authorization": f"Bearer {new}"}).status_code == 200


def test_cursor_walk(api_world):
    c, h = api_world.client, api_world.h("admin")
    for i in range(3):
        assert c.post("/api/v1/matters", json={"title": f"p{i}"}, headers=h).status_code == 201
    seen, cursor = [], None
    while True:
        q = "/api/v1/matters?limit=2" + (f"&cursor={cursor}" if cursor else "")
        body = c.get(q, headers=h).json()
        assert len(body["items"]) <= 2
        seen += [m["matter_id"] for m in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5 == len(set(seen))
    r = c.get("/api/v1/matters?cursor=!!", headers=h)
    assert (r.status_code, code(r)) == (422, "validation_failed")


def test_idempotency_replay_and_conflict(api_world):
    c = api_world.client
    h = {**api_world.h("admin"), "Idempotency-Key": "k-1"}
    r1 = c.post("/api/v1/matters", json={"title": "idem"}, headers=h)
    r2 = c.post("/api/v1/matters", json={"title": "idem"}, headers=h)
    assert r1.status_code == r2.status_code == 201
    assert r2.json() == r1.json() and r2.headers.get("idempotent-replayed") == "true"
    listed = c.get("/api/v1/matters?q=idem", headers=api_world.h("admin")).json()["items"]
    assert len(listed) == 1
    r3 = c.post("/api/v1/matters", json={"title": "other"}, headers=h)
    assert (r3.status_code, code(r3)) == (409, "idempotency_conflict")
    # keyed per principal: the same key from another user is a fresh request
    r4 = c.post("/api/v1/matters", json={"title": "idem"},
                headers={**api_world.h("editor"), "Idempotency-Key": "k-1"})
    assert r4.status_code == 201 and r4.json()["matter_id"] != r1.json()["matter_id"]


def _frames(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        f = dict(line.split(": ", 1) for line in block.splitlines()
                 if line and not line.startswith(":"))
        if "id" in f:
            out.append({"id": int(f["id"]), "event": f["event"], "data": json.loads(f["data"])})
    return out


def test_sse_replay_heartbeat_and_live_tail(api_world):
    w = api_world
    mid, h = w.A["mid"], w.h("admin")
    url = f"/api/v1/events?channels=matter:{mid}"
    r = w.client.get(url, headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert ": hb" in r.text
    frames = _frames(r.text)
    ids = [f["id"] for f in frames]
    assert ids == sorted(ids) and len(ids) > 3
    assert {f["data"]["matter_id"] for f in frames} == {mid}
    cut = ids[len(ids) // 2]
    again = _frames(w.client.get(url, headers={**h, "Last-Event-ID": str(cut)}).text)
    assert [f["id"] for f in again] == [i for i in ids if i > cut]
    # live tail: an event written while the stream is open arrives on it
    from fastapi.testclient import TestClient
    w.app.state.sse["max_s"] = 1.5
    got = {}

    def listen():
        with TestClient(w.app) as c2:
            got["r"] = c2.get(url, headers={**h, "Last-Event-ID": str(ids[-1])})

    t = threading.Thread(target=listen)
    t.start()
    time.sleep(0.3)
    assert w.client.post(f"/api/v1/matters/{mid}/conversations", json={"title": "live"},
                         headers=h).status_code == 201
    t.join(5)
    live = _frames(got["r"].text)
    assert [f["event"] for f in live] == ["conversation.created"]


def test_intake_answer_before_first_transition_still_enters_intake(api_world):
    """lawyer_now.evaluate (run on every facts change) creates the cases row with
    state NULL; the first transition must still be allowed to INTAKE."""
    c, h, mid = api_world.client, api_world.h("admin"), api_world.A["mid"]
    r = c.post(f"/api/v1/matters/{mid}/intake/answers", headers=h,
               json={"question_id": "claim_amount", "answer": 30000})
    assert r.status_code == 202 and r.json()["current"]["id"] == "summary"
    assert c.get(f"/api/v1/matters/{mid}/lawyer-now", headers=h).json() == {
        "state": "flagged", "triggers": ["claim_above_self_help"], "help": []}
    bad = c.post(f"/api/v1/matters/{mid}/lifecycle", json={"to": "ASSESS"}, headers=h)
    assert (bad.status_code, code(bad)) == (409, "invalid_transition")
    ok = c.post(f"/api/v1/matters/{mid}/lifecycle", json={"to": "INTAKE"}, headers=h)
    assert ok.status_code == 200 and ok.json()["stage"] == "INTAKE"
    assert ok.json()["next_allowed"] == ["ASSESS"]


def test_sse_bad_channel(api_world):
    r = api_world.client.get("/api/v1/events?channels=elsewhere", headers=api_world.h("admin"))
    assert (r.status_code, code(r)) == (422, "validation_failed")


OPENAPI = Path(__file__).resolve().parents[1] / "docs" / "enterprise" / "openapi-v1.json"


def test_openapi_committed_and_current(api_world):
    spec = json.loads(json.dumps(api_world.app.openapi()))
    if os.environ.get("UPDATE_OPENAPI") == "1":
        OPENAPI.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    assert OPENAPI.is_file(), "run with UPDATE_OPENAPI=1 once to generate the spec"
    assert json.loads(OPENAPI.read_text(encoding="utf-8")) == spec, \
        "OpenAPI drift — regenerate with UPDATE_OPENAPI=1 and review the diff"
    for key in ROUTES:                    # every 04 §5 / 08 §16 path is published
        method, path = key.split(" ", 1)
        assert method.lower() in spec["paths"][path], key
