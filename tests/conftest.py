import pytest

@pytest.fixture
def harness_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    return tmp_path / "home"

@pytest.fixture
def api_world(tmp_path, monkeypatch):
    """M7: a store with matters A and B (identical resource sets, admin-created),
    users admin/editor/reader on A, `out` (editor role, no membership) and `aud`
    (cross_read-only role, no membership), plus bearer tokens. Seeded through the
    service layer (fixtures may touch the db; test bodies go through HTTP)."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from harness.api.app import create_app
    from harness.lifecycle import dossier
    from harness.service import (auth, catalog, conversations, documents, executions,
                                 ingest, matters, system)
    from harness.workflow import approvals

    monkeypatch.setattr(auth, "_ITER", 1000)          # pbkdf2 speed, tests only
    monkeypatch.setattr(system, "doctor_report", lambda **_: "doctor ok (test)")
    monkeypatch.setattr(ingest, "ingest_source", lambda m, s, *a, **k: {"ingested": s})
    import harness.keychain as _keychain
    from harness.service import settings as _settings
    monkeypatch.setattr(_keychain, "_kv", {})         # M13.7: no OS keyring touches
    async def _canned_probe(name, spec, **_):         # the Test probe dials the network
        return {"name": name, "reachable": False,
                "auth_ok": False, "admission": "refused",
                "verified": False, "models": 0}
    monkeypatch.setattr(_settings, "_probe_one", _canned_probe)
    root = tmp_path / "store"
    root.mkdir()
    con = system.open_db(root)
    con.execute("INSERT OR IGNORE INTO roles VALUES('auditor','Auditor')")
    con.execute("INSERT OR IGNORE INTO role_permissions VALUES('auditor','matter.read'),"
                "('auditor','matter.cross_read')")
    spec = {"admin": ("admin", "admin"), "editor": ("ed", "editor"),
            "reader": ("rd", "reader"), "outsider": ("out", "editor"),
            "auditor": ("aud", "auditor"), "spare": ("x", "reader")}
    users = {r: auth.create_user(con, u, "pw", role_id=role) for r, (u, role) in spec.items()}
    tokens = {r: auth._issue(con, users[r])["token"] for r in users}
    adm = {"user_id": users["admin"], "username": "admin", "role_id": "admin"}
    plan = "```plan\ns1|clerk|do it\n```"

    def world(title):
        mid = matters.create(con, adm, {"title": title})["matter_id"]
        matters.put_member(con, adm, mid, users["spare"], {"role_id": "reader"})
        eid = executions.create(con, adm, mid, {"task_text": "t", "plan_block": plan})[
            "execution_id"]
        apid = approvals.request(con, matter_id=mid, execution_id=eid,
                                 task_id=f"{eid}-t1", kind="review", payload={})
        qid = catalog.create_request(con, adm, mid, {"question": "q?"})["approval_id"]
        cid = conversations.create_conversation(con, adm, mid, {"title": "c"})[
            "conversation_id"]
        doc = documents.upload(con, adm, mid, b"hello", filename="a.txt",
                               store_root=root)["doc_id"]
        art = f"art-{mid}"
        con.execute("INSERT INTO artifacts(artifact_id, matter_id, execution_id, kind,"
                    " title, content, review_state, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (art, mid, eid, "memo", "m", "body", "pending", "t", "t"))
        nxt = dossier.append(con, mid, "proposals", {"what": "call court", "why": "y"},
                             actor="admin")["proposal_id"]
        dossier.append(con, mid, "strategy", {"version": 1, "file": "s.md",
                                              "why_changed": "init", "next_actions": []},
                       actor="admin")
        return {"mid": mid, "eid": eid, "rid": eid, "apid": apid, "qid": qid, "cid": cid,
                "doc_id": doc, "art": art, "next": nxt, "uid": users["spare"], "v": "1"}

    A, B = world("Matter A"), world("Matter B")
    for r in ("editor", "reader"):
        matters.put_member(con, adm, A["mid"], users[r], {"role_id": r})
    agent = catalog.create_agent(con, adm, {"name": "clerk"})["agent_id"]
    con.close()
    app = create_app(root, sse_heartbeat_s=0.05, sse_poll_s=0.01, sse_max_s=0.25)
    client = TestClient(app)
    yield SimpleNamespace(client=client, app=app, root=root, tokens=tokens, users=users,
                          A=A, B=B, agent=agent,
                          h=lambda r: {"Authorization": f"Bearer {tokens[r]}"})
    client.close()


@pytest.fixture
def fake_transport():  # canned OpenAI-compatible completion, used across tests
    async def _call(provider, payload):
        return {
            "id": "chatcmpl-test", "object": "chat.completion",
            "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "mock answer citing [Act, s 1]"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_server_meta": {"engine": provider.engine or "unknown",
                              "weights_revision": provider.declared_provenance.get("weights_revision", "")},
        }
    return _call
