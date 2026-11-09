"""M7 authz: the matrix (every route x {no token, outsider, reader, editor,
admin}), cross-matter fails closed, cross_read grants reads only, and the
layering rule (no authz decisions / SQL / workflow+lifecycle imports in
harness/api). Parametrized off app.routes: a new route with no ROUTES entry
fails test_every_route_is_in_the_matrix."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DENIED = {"unauthenticated", "permission_denied", "matter_not_found"}
PLAN = "```plan\ns1|clerk|do it\n```"
WF = [{"stage": "s", "agent": "a", "instruction": "i"}]

# "METHOD path" -> (kind, body, query). kinds:
#   public  — no auth;  authed — any principal;  gwrite — platform matter.write;
#   audit   — audit.read;  read / write — matter-scoped (membership role perms)
ROUTES = {
    "POST /api/v1/auth/login": ("public", None, ""),
    "POST /api/v1/auth/refresh": ("authed", None, ""),
    "GET /api/v1/auth/me": ("authed", None, ""),
    "GET /api/v1/matters": ("authed", None, ""),
    "POST /api/v1/matters": ("gwrite", {"title": "t"}, ""),
    "GET /api/v1/matters/{mid}": ("read", None, ""),
    "PATCH /api/v1/matters/{mid}": ("write", {"priority": "high"}, ""),
    "POST /api/v1/matters/{mid}/state": ("write", {"to": "active"}, ""),
    "GET /api/v1/matters/{mid}/members": ("read", None, ""),
    "PUT /api/v1/matters/{mid}/members/{uid}": ("write", {"role_id": "reader"}, ""),
    "DELETE /api/v1/matters/{mid}/members/{uid}": ("write", None, ""),
    "POST /api/v1/matters/{mid}/documents": ("write", b"bytes", "filename=b.txt"),
    "POST /api/v1/matters/{mid}/documents/ingest": ("write", {"source": "x"}, ""),
    "GET /api/v1/matters/{mid}/documents": ("read", None, ""),
    "GET /api/v1/documents/{doc_id}": ("read", None, ""),
    "GET /api/v1/matters/{mid}/evidence": ("read", None, ""),
    "GET /api/v1/matters/{mid}/artifacts": ("read", None, ""),
    "GET /api/v1/artifacts/{aid}": ("read", None, ""),
    "POST /api/v1/artifacts/{aid}/review": ("write", {"decision": "approve"}, ""),
    "GET /healthz": ("public", None, ""),
    "GET /api/v1/audit": ("audit", None, ""),
    "GET /api/v1/workflows": ("authed", None, ""),
    "POST /api/v1/workflows": ("gwrite", {"name": "w", "definition": WF}, ""),
    "POST /api/v1/matters/{mid}/executions": ("write", {"task_text": "t",
                                                        "plan_block": PLAN}, ""),
    "GET /api/v1/executions/{eid}": ("read", None, ""),
    "GET /api/v1/executions/{eid}/tasks": ("read", None, ""),
    "POST /api/v1/executions/{eid}/pause": ("write", None, ""),
    "POST /api/v1/executions/{eid}/resume": ("write", None, ""),
    "POST /api/v1/executions/{eid}/cancel": ("write", {"reason": "r"}, ""),
    "POST /api/v1/executions/{eid}/redirect": ("write", {"task_id": "nope",
                                                         "instruction": "i"}, ""),
    "GET /api/v1/agents": ("authed", None, ""),
    "POST /api/v1/agents": ("gwrite", {"name": "n"}, ""),
    "PATCH /api/v1/agents/{aid}": ("gwrite", {"role": "r"}, ""),
    "GET /api/v1/matters/{mid}/runs": ("read", None, ""),
    "GET /api/v1/runs/{rid}": ("read", None, ""),
    "POST /api/v1/runs/{rid}/interject": ("write", {"text": "hi"}, ""),
    "POST /api/v1/runs/{rid}/cancel": ("write", None, ""),
    "GET /api/v1/approvals": ("authed", None, ""),
    "GET /api/v1/matters/{mid}/approvals": ("read", None, ""),
    "POST /api/v1/approvals/{apid}/approve": ("write", {"note": "ok"}, ""),
    "POST /api/v1/approvals/{apid}/reject": ("write", {"note": "no"}, ""),
    "POST /api/v1/matters/{mid}/requests": ("write", {"question": "q"}, ""),
    "POST /api/v1/requests/{qid}/answer": ("write", {"text": "a"}, ""),
    "GET /api/v1/matters/{mid}/conversations": ("read", None, ""),
    "POST /api/v1/matters/{mid}/conversations": ("write", {"title": "c"}, ""),
    "GET /api/v1/conversations/{cid}/messages": ("read", None, ""),
    "POST /api/v1/conversations/{cid}/messages": ("write", {"text": "hello"}, ""),
    "GET /api/v1/matters/{mid}/lifecycle": ("read", None, ""),
    "POST /api/v1/matters/{mid}/lifecycle": ("write", {"to": "INTAKE"}, ""),
    "GET /api/v1/matters/{mid}/next-actions": ("read", None, ""),
    "POST /api/v1/matters/{mid}/next-actions/{aid}/complete": ("write", {"note": "n"}, ""),
    "GET /api/v1/matters/{mid}/dossier/facts": ("read", None, ""),
    "POST /api/v1/matters/{mid}/dossier/facts": ("write", {"updates": {"summary": "s"}}, ""),
    "GET /api/v1/matters/{mid}/intake/questions": ("read", None, ""),
    "POST /api/v1/matters/{mid}/intake/answers": ("write", {"question_id": "summary",
                                                            "answer": "x"}, ""),
    "GET /api/v1/matters/{mid}/strategy": ("read", None, ""),
    "GET /api/v1/matters/{mid}/strategy/{v}/diff": ("read", None, "against=1"),
    "GET /api/v1/matters/{mid}/predictions": ("read", None, ""),
    "GET /api/v1/matters/{mid}/flaws": ("read", None, ""),
    "GET /api/v1/matters/{mid}/hearing-pack": ("read", None, ""),
    "POST /api/v1/matters/{mid}/mock-hearing": ("write", None, ""),
    "GET /api/v1/matters/{mid}/debrief/questions": ("read", None, ""),
    "POST /api/v1/matters/{mid}/debrief": ("write", {"answers": {"date": "2026-11-01"}}, ""),
    "GET /api/v1/matters/{mid}/deadlines": ("read", None, ""),
    "GET /api/v1/matters/{mid}/lawyer-now": ("read", None, ""),
    "GET /api/v1/matters/{mid}/closure-checklist": ("read", None, ""),
    "POST /api/v1/matters/{mid}/close": ("write", {"note": "done"}, ""),
    "GET /api/v1/events": ("read", None, "channels=matter:{mid}"),
}


def _routes(app):
    # the published spec, not app.routes: fastapi >=0.16x wraps included routers
    return {f"{m.upper()} {path}" for path, ops in app.openapi()["paths"].items()
            for m in ops}


def _fill(path: str, ids: dict, agent: str) -> str:
    if "/agents/{aid}" in path:
        path = path.replace("{aid}", agent)
    elif "/artifacts/{aid}" in path:
        path = path.replace("{aid}", ids["art"])
    elif "/next-actions/{aid}" in path:
        path = path.replace("{aid}", ids["next"])
    for k in ("mid", "eid", "rid", "apid", "qid", "cid", "doc_id", "uid", "v"):
        path = path.replace("{" + k + "}", ids[k])
    return path


def call(w, key: str, role: str | None, ids: dict):
    method, path = key.split(" ", 1)
    _, body, query = ROUTES[key]
    url = _fill(path, ids, w.agent)
    if query:
        url += "?" + query.replace("{mid}", ids["mid"])
    headers = w.h(role) if role else {}
    kw = {"content": body} if isinstance(body, bytes) else (
        {"json": body} if body is not None else {})
    return w.client.request(method, url, headers=headers, **kw)


def code(r) -> str | None:
    try:
        body = r.json()
    except ValueError:
        return None
    return body.get("error", {}).get("code") if isinstance(body, dict) else None


def test_every_route_is_in_the_matrix(api_world):
    live = _routes(api_world.app)
    assert live - set(ROUTES) == set(), "route(s) missing a matrix entry"
    assert set(ROUTES) - live == set(), "matrix entry for a route that no longer exists"


_EXPECT = {
    "authed": {None: "unauthenticated"},
    "gwrite": {None: "unauthenticated", "reader": "permission_denied"},
    "audit": {None: "unauthenticated", "reader": "permission_denied",
              "editor": "permission_denied", "outsider": "permission_denied"},
    "read": {None: "unauthenticated", "outsider": "matter_not_found"},
    "write": {None: "unauthenticated", "outsider": "matter_not_found",
              "reader": "permission_denied"},
}
_STATUS = {"unauthenticated": 401, "permission_denied": 403, "matter_not_found": 404}


@pytest.mark.parametrize("key", sorted(k for k, v in ROUTES.items() if v[0] != "public"))
def test_authz_matrix(api_world, key):
    w = api_world
    expect = _EXPECT[ROUTES[key][0]]
    # deny-side roles first (they must not mutate), then the allowed ones
    for role in (None, "outsider", "reader", "editor", "admin"):
        r = call(w, key, role, w.A)
        if role in expect:
            want = expect[role]
            assert (r.status_code, code(r)) == (_STATUS[want], want), (key, role, r.text)
        else:
            assert r.status_code < 500 and code(r) not in DENIED, (key, role, r.text)


def test_cross_matter_fails_closed_then_cross_read_reads_only(api_world):
    """Editor is a member of A only: every B-scoped and id-scoped route on B's
    resources is 404 (never 403 — existence does not leak). The auditor role
    (matter.cross_read, no membership) reads B, but every write is 403."""
    w = api_world
    scoped = [k for k, (kind, _, _) in ROUTES.items() if kind in ("read", "write")]
    for key in scoped:
        r = call(w, key, "editor", w.B)
        assert (r.status_code, code(r)) == (404, "matter_not_found"), (key, r.text)
    for key in scoped:
        r = call(w, key, "auditor", w.B)
        if ROUTES[key][0] == "read":
            assert r.status_code < 400, (key, r.text)
        else:
            assert (r.status_code, code(r)) == (403, "permission_denied"), (key, r.text)


def test_board_channel_never_carries_other_matters(api_world):
    w = api_world
    r = w.client.get("/api/v1/events?channels=board", headers=w.h("editor"))
    assert r.status_code == 200
    mids = set(re.findall(r'"matter_id": "([^"]+)"', r.text))
    assert mids == {w.A["mid"]}, mids


API_DIR = Path(__file__).resolve().parents[1] / "src" / "harness" / "api"
_FORBIDDEN = [
    (r"\brequire\(", "authz decision"),
    (r"\b(matter_perms|global_perms|readable_matters)\b", "authz decision"),
    (r"\b(SELECT|INSERT INTO|UPDATE \w+ SET|DELETE FROM)\b", "raw SQL"),
    (r"(from|import) harness\.(workflow|lifecycle)\b", "engine import"),
]


def test_api_layer_holds_no_authz_sql_or_engine_imports():
    hits = []
    for f in sorted(API_DIR.rglob("*.py")):
        text = f.read_text(encoding="utf-8")
        for pat, why in _FORBIDDEN:
            hits += [f"{f.name}: {why}: {m.group(0)}" for m in re.finditer(pat, text)]
    assert hits == []
