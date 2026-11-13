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
          # the fixture's run is parked at an approval: decided, not paused (M10 guard)
          "POST /api/v1/executions/{eid}/pause": (409, "invalid_transition"),
          "POST /api/v1/executions/{eid}/redirect": (409, "lease_conflict"),
          "POST /api/v1/matters/{mid}/close": (409, "invalid_transition"),
          # the fixture's run is live: a matter with running work is not deletable
          "DELETE /api/v1/matters/{mid}": (409, "invalid_transition"),
          "DELETE /api/v1/settings/providers": (404, "not_found")}
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


def test_pause_only_a_running_execution_and_redirect_keeps_a_park(api_world):
    """M10: pausing (then resuming) a run parked at an approval would let the worker run
    past it; redirect must not unpark it either."""
    c, h, A, B = api_world.client, api_world.h("admin"), api_world.A, api_world.B
    ex = lambda eid: c.get(f"/api/v1/executions/{eid}", headers=h).json()  # noqa: E731
    pending = [t for t in ex(B["eid"])["tasks"] if t["state"] == "pending"]
    r = c.post(f"/api/v1/executions/{B['eid']}/redirect", headers=h,
               json={"task_id": pending[0]["task_id"], "instruction": "narrower"})
    assert r.status_code == 202 and ex(B["eid"])["state"] == "waiting_human", r.text
    assert c.post(f"/api/v1/approvals/{A['apid']}/approve", json={},
                  headers=h).status_code == 200
    assert ex(A["eid"])["state"] == "executing"
    assert c.post(f"/api/v1/executions/{A['eid']}/pause", headers=h).status_code == 202
    assert ex(A["eid"])["state"] == "paused"
    again = c.post(f"/api/v1/executions/{A['eid']}/pause", headers=h)
    assert (again.status_code, code(again)) == (409, "invalid_transition")
    assert c.post(f"/api/v1/executions/{A['eid']}/resume", headers=h).status_code == 202
    assert ex(A["eid"])["state"] == "executing"


def test_healthz_needs_no_token(api_world):
    r = api_world.client.get("/healthz")
    assert r.status_code == 200 and r.json()["stores"] == "ok"


def test_document_text_is_the_extracted_reading_view(api_world):  # M13.4
    w = api_world
    r = w.client.get(f"/api/v1/documents/{w.A['doc_id']}/text", headers=w.h("reader"))
    assert r.json() == {"doc_id": w.A["doc_id"], "text": "hello"}


def test_document_chunks_match_the_corpus_by_content(api_world):  # M13.5
    from harness.corpus import CorpusStore, DocRecord, split_structure
    w = api_world
    url = f"/api/v1/documents/{w.A['doc_id']}/chunks"
    assert w.client.get(url, headers=w.h("reader")).json()["chunks"] == []   # not ingested
    n = len(split_structure("doc-x", "hello"))
    CorpusStore(Path(w.app.state.store_root) / "corpus.sqlite3").ingest(
        w.A["mid"], DocRecord(doc_id="doc-x", text="hello", source_name="a.txt"),
        [[0.0]] * n, "m", "p")
    got = w.client.get(url, headers=w.h("reader")).json()["chunks"]
    assert [c["text"] for c in got] == ["hello"] and isinstance(got[0]["i"], int)


def test_document_viewer_failure_contract(api_world, monkeypatch):  # UX-5
    """The viewer's states read these exact answers: /meta is the row (no list page);
    a parser failure is 422 unreadable_document; a gone file is 404 document_file_missing
    on bytes, text and chunks; a doc of another matter 404s like an unknown one."""
    from harness import ingest_generic
    w = api_world
    h, doc = w.h("reader"), w.A["doc_id"]
    code = lambda r: (r.status_code, r.json()["error"]["code"])  # noqa: E731
    meta = w.client.get(f"/api/v1/documents/{doc}/meta", headers=h).json()
    assert (meta["doc_id"], meta["matter_id"], meta["filename"]) == (doc, w.A["mid"], "a.txt")
    assert code(w.client.get(f"/api/v1/documents/{w.B['doc_id']}/meta", headers=h)) == (404, "matter_not_found")
    assert code(w.client.get("/api/v1/documents/doc-nope/meta", headers=h)) == (404, "document_not_found")

    def boom(_):
        raise RuntimeError('parse failed: a.txt: Traceback (most recent call last):\n  File "pathlib"')
    monkeypatch.setattr(ingest_generic, "extract_text", boom)
    r = w.client.get(f"/api/v1/documents/{doc}/text", headers=h)
    assert code(r) == (422, "unreadable_document"), r.text
    assert "Traceback" not in r.text and "damaged or in a format" in r.json()["error"]["message"]
    monkeypatch.undo()
    for f in (Path(w.app.state.store_root) / "documents" / w.A["mid"]).iterdir():
        f.unlink()
    for tail in ("", "/text", "/chunks"):
        assert code(w.client.get(f"/api/v1/documents/{doc}{tail}", headers=h)) == (404, "document_file_missing")
    assert w.client.get(f"/api/v1/documents/{w.B['doc_id']}", headers=h).status_code == 404


def test_evidence_links_an_upload_only_by_exact_sha(api_world):  # UX-5
    from harness.lifecycle import dossier
    from harness.service import system
    w = api_world
    con = system.open_db(Path(w.app.state.store_root))
    sha = con.execute("SELECT sha256 FROM documents WHERE doc_id=?", (w.A["doc_id"],)).fetchone()[0]
    for label, s in (("E1", sha), ("E2", sha.upper()), ("E3", sha[:16]), ("E4", "")):
        dossier.append(con, w.A["mid"], "evidence", {"op": "add", "label": label, "file": "a.txt", "sha256": s})
    # matter B holds an identical upload: it must never be offered from matter A
    con.close()
    items = w.client.get(f"/api/v1/matters/{w.A['mid']}/evidence", headers=w.h("reader")).json()["items"]
    assert {r["label"]: r["doc_id"] for r in items} == {"E1": w.A["doc_id"], "E2": w.A["doc_id"], "E3": None, "E4": None}


def test_artifact_sources_tie_quotes_to_upload_and_passage(api_world):  # UX-5
    """The citation guard's verdicts over a deliverable, each resolved to the upload and the
    passage index GET /documents/{id}/chunks would show — or null when not an upload."""
    from harness.corpus import CorpusStore, DocRecord, split_structure
    from harness.service import system
    w = api_world
    root = Path(w.app.state.store_root)
    con = system.open_db(root)
    path = con.execute("SELECT path FROM documents WHERE doc_id=?", (w.A["doc_id"],)).fetchone()[0]
    quote = "the tenant shall pay the rent monthly in advance"
    body = f"# Lease\n\nPreamble words here.\n\n## Rent\n\n{quote} without any deduction."
    store = CorpusStore(root / "corpus.sqlite3")
    law = "a company is insolvent when it cannot pay its debts as they fall due"
    store.ingest(w.A["mid"], DocRecord(doc_id="doc-law", text=law, source_name="Companies Act 1993, s 4"),
                 [[0.0]] * len(split_structure("doc-law", law)), "m", "p")   # first: its rowid precedes the upload's
    n = len(split_structure("doc-u", body))
    store.ingest(w.A["mid"], DocRecord(doc_id="doc-u", text=body, source_name=Path(path).name), [[0.0]] * n, "m", "p")
    draft = f'Line one.\nThe lease says "{quote}".\nAnd "{law}".\nBut "these six words are not anywhere".'
    con.execute("UPDATE artifacts SET content=? WHERE artifact_id=?", (draft, w.A["art"]))
    con.close()
    r = w.client.get(f"/api/v1/artifacts/{w.A['art']}/sources", headers=w.h("reader"))
    assert r.status_code == 200, r.text
    q = r.json()["quotes"]
    assert [(x["verdict"], x["line"]) for x in q] == [("VERIFIED", 2), ("VERIFIED", 3), ("NOT_IN_CORPUS", 4)]
    assert (q[0]["doc_id"], q[0]["filename"]) == (w.A["doc_id"], "a.txt")
    chunks = store.doc_chunks(w.A["mid"], __import__("hashlib").sha256(body.encode()).hexdigest())
    ids = [c["i"] for c in chunks]                        # the viewer's passage ids (corpus rowids)
    assert quote in chunks[ids.index(q[0]["chunk"])]["text"]          # the very passage the viewer shows
    assert q[0]["passage"] == ids.index(q[0]["chunk"]) + 1 and q[0]["chunk"] != q[0]["passage"]   # id is not a position
    assert (q[1]["doc_id"], q[1]["chunk"], q[1]["passage"], q[1]["source_name"]) == (None, None, None, "Companies Act 1993, s 4")
    assert q[2]["doc_id"] is None and q[2]["source_name"] is None
    assert w.client.get(f"/api/v1/artifacts/{w.A['art']}/sources", headers=w.h("outsider")).status_code == 404


def test_document_ingest_without_source_targets_the_matter_uploads(api_world, monkeypatch):  # M13.8
    """UI 'Ingest documents' posts no source: the service must default to the matter's
    own uploads dir — a user is never shown a store path. UX-5: each upload's status
    follows what the ingest report says happened to its own stored file."""
    from harness.service import ingest
    w = api_world
    h = w.h("admin")
    up = w.client.post(f"/api/v1/matters/{w.A['mid']}/documents?filename=b.docx",
                       content=b"x", headers=h).json()
    up2 = w.client.post(f"/api/v1/matters/{w.A['mid']}/documents?filename=c.txt",
                        content=b"y", headers=h).json()
    seen = {}

    def fake(mid, source):
        seen["source"] = source
        names = {d["doc_id"]: Path(d["path"]).name for d in (up, up2)}
        return {"ingested": [f"{w.A['doc_id']}-a.txt"], "skipped_by_resume": [],
                "skipped": [f"{names[up['doc_id']]}: unsupported file type '.docx'"]}
    monkeypatch.setattr(ingest, "ingest_source", fake)
    r = w.client.post(f"/api/v1/matters/{w.A['mid']}/documents/ingest", json={}, headers=h)
    assert r.status_code == 202, r.text
    assert seen["source"] == str(Path(w.app.state.store_root) / "documents" / w.A["mid"])
    st = {d["doc_id"]: d["ingest_status"] for d in w.client.get(
        f"/api/v1/matters/{w.A['mid']}/documents", headers=h).json()["items"]}
    assert st == {w.A["doc_id"]: "ingested", up["doc_id"]: "skipped", up2["doc_id"]: "pending"}


def test_matter_rows_carry_last_activity_from_the_event_log(api_world):  # UX-1 gap
    w = api_world
    h = w.h("admin")
    m = w.client.post("/api/v1/matters", json={"title": "activity"}, headers=h).json()
    assert m["last_activity_at"]                      # matter.created is itself an event
    w.client.post(f"/api/v1/matters/{m['matter_id']}/lifecycle", json={"to": "INTAKE"}, headers=h)
    later = w.client.get(f"/api/v1/matters/{m['matter_id']}", headers=h).json()["last_activity_at"]
    assert later > m["last_activity_at"]              # ISO-8601 UTC strings order by time


def test_document_ingest_without_documents_is_a_422(api_world):  # M13.8
    w = api_world
    mid = w.client.post("/api/v1/matters", json={"title": "no docs"},
                        headers=w.h("admin")).json()["matter_id"]
    r = w.client.post(f"/api/v1/matters/{mid}/documents/ingest", json={},
                      headers=w.h("admin"))
    assert (r.status_code, code(r)) == (422, "validation_failed"), r.text
    assert "no uploaded documents" in r.json()["error"]["message"]


def test_skill_upload_validates_and_lands_in_the_store(api_world):  # M13.6
    from test_api_authz import SKILL
    c, h = api_world.client, api_world.h("admin")
    r = c.post("/api/v1/skills?name=my-skill", content=SKILL, headers=h)
    assert r.status_code == 201, r.text
    got = (Path(api_world.app.state.store_root) / "skills" / "my-skill" / "SKILL.md")
    assert "name: my-skill" in got.read_text(encoding="utf-8")
    for name, body in (("no-fm", b"# just markdown"), ("Bad_Name", SKILL),
                       ("affidavit-formatter", SKILL), ("short", b"---\ndescription: x\n---\n")):
        r = c.post(f"/api/v1/skills?name={name}", content=body, headers=h)
        assert (r.status_code, code(r)) == (422, "validation_failed"), (name, r.text)


def test_settings_view_put_write_only_key_and_test(api_world):  # M13.7
    w = api_world
    h = w.h("admin")
    r = w.client.get("/api/v1/settings/providers", headers=h)
    body = r.json()
    assert r.status_code == 200
    names = {p["name"] for p in body["providers"]}
    assert {"ollama-local", "ollama-embed", "nvidia-nim"} <= names
    ollama = next(p for p in body["providers"] if p["name"] == "ollama-local")
    assert ollama["tier"] == "local" and ollama["has_key"] is False
    assert [s["task_class"] for s in body["stages"]]      # routing rows as data
    # row edit persists to the store; the key lands in the keychain and is never echoed
    r = w.client.put("/api/v1/settings/providers?name=ollama-local", headers=h,
                     json={"base_url": "http://127.0.0.1:11434/v1",
                           "model": "thomson1-chat:latest", "api_key": "sk-secret-1"})
    assert r.status_code == 200 and "sk-secret-1" not in r.text, r.text
    from harness.keychain import get_key
    assert get_key("ollama-local") == "sk-secret-1"
    f = Path(w.app.state.store_root) / "model-settings.json"
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["providers"]["ollama-local"]["model"] == "thomson1-chat:latest"
    # local rows stay on the loopback; cloud rows must be https
    bad = w.client.put("/api/v1/settings/providers?name=ollama-local", headers=h,
                       json={"base_url": "http://evil.example.com/v1"})
    assert (bad.status_code, code(bad)) == (422, "validation_failed"), bad.text
    bad = w.client.put("/api/v1/settings/providers?name=nvidia-nim", headers=h,
                       json={"base_url": "http://integrate.api.nvidia.com/v1"})
    assert (bad.status_code, code(bad)) == (422, "validation_failed"), bad.text
    unknown = w.client.put("/api/v1/settings/providers?name=who", headers=h, json={})
    assert (unknown.status_code, code(unknown)) == (404, "not_found")
    # Test: the conftest seam answers, so no network — and Test never stores a key
    r = w.client.post("/api/v1/settings/providers/test?name=ollama-local", headers=h)
    assert r.status_code == 200 and r.json() == {
        "name": "ollama-local", "reachable": False, "auth_ok": False,
        "admission": "refused", "verified": False, "models": 0}, r.text


def test_assign_persists_and_the_gate_applies_it(api_world, monkeypatch):  # M13.7
    from harness.providers.config import ProviderConfig, ProviderRegistry
    from harness.policy import MatterPolicy
    import harness.bootstrap as bs
    w = api_world
    h = w.h("admin")
    r = w.client.put("/api/v1/settings/assign?task_class=drafting", headers=h,
                     json={"provider": "nvidia-nim"})
    assert r.status_code == 200 and r.json() == {"task_class": "drafting",
                                                 "assign": "nvidia-nim"}, r.text
    bad = w.client.put("/api/v1/settings/assign?task_class=drafting", headers=h,
                       json={"provider": "nope"})
    assert (bad.status_code, code(bad)) == (422, "validation_failed"), bad.text
    bad = w.client.put("/api/v1/settings/assign?task_class=nonexistent", headers=h,
                       json={"provider": "ollama-local"})
    assert (bad.status_code, code(bad)) == (422, "validation_failed"), bad.text
    clear = w.client.put("/api/v1/settings/assign?task_class=drafting", headers=h,
                         json={"provider": None})
    assert clear.status_code == 200 and clear.json()["assign"] is None
    # re-set, then prove the live gate build applies the order (store root via env)
    w.client.put("/api/v1/settings/assign?task_class=drafting", headers=h,
                 json={"provider": "nvidia-nim"})
    monkeypatch.setenv("HARNESS_HOME", str(w.app.state.store_root))
    monkeypatch.setattr(bs, "_probe_ollama", lambda *a, **k: ProviderRegistry())
    gate, rt, _ = bs.build_gate(Path(w.app.state.store_root) / "trace-t.db",
                                Path("data/routing-a1.yaml"))
    reg = ProviderRegistry()
    for n, t in (("ollama-local", "local"), ("nvidia-nim", "cloud")):
        reg.upsert(ProviderConfig(name=n, base_url="http://127.0.0.1:9/v1", model="m",
                                  models=[], engine="ollama" if t == "local" else "cloud",
                                  tier=t, admitted="full"))
    pol = MatterPolicy(matter_ref="m", classification="LOCAL_PREFERRED")
    got = [c.name for c in rt.route("drafting", pol, reg)]
    assert got[0] == "nvidia-nim" and set(got) == {"nvidia-nim", "ollama-local"}, got


def test_add_provider_and_assign_any_provider_to_any_stage(api_world, monkeypatch):
    from harness.providers.config import ProviderConfig, ProviderRegistry
    from harness.policy import MatterPolicy
    import harness.bootstrap as bs
    w = api_world
    h = w.h("admin")
    url = "/api/v1/settings/providers"
    r = w.client.post(url, headers=h, json={"name": "groq-x", "engine": "cloud", "model": "llama-9",
                                            "base_url": "https://api.groq.com/v1", "api_key": "k1"})
    assert r.status_code == 201 and "k1" not in r.text, r.text
    for bad, want in (({"name": "groq-x"}, 409),                      # duplicate
                      ({"name": "Bad Name"}, 422),
                      ({"name": "ok", "engine": "nope"}, 422),
                      ({"name": "ok", "base_url": "http://plain.example/v1"}, 422)):
        r = w.client.post(url, headers=h, json={"name": "x", "engine": "cloud", "model": "m",
                                                "base_url": "https://a.example/v1", **bad})
        assert r.status_code == want, (bad, r.text)
    p = next(p for p in w.client.get(url, headers=h).json()["providers"] if p["name"] == "groq-x")
    assert p["custom"] and p["tier"] == "cloud" and p["model"] == "llama-9"
    # edit in place; any stage takes it, except the structurally local-only ones (A-4)
    assert w.client.put(f"{url}?name=groq-x", headers=h, json={"model": "llama-10"}).status_code == 200
    assert w.client.put("/api/v1/settings/assign?task_class=extraction", headers=h,
                        json={"provider": "groq-x"}).status_code == 200
    bad = w.client.put("/api/v1/settings/assign?task_class=embedding", headers=h,
                       json={"provider": "groq-x"})
    assert (bad.status_code, code(bad)) == (422, "validation_failed"), bad.text
    # the live registry read and the gate both see it, though routing YAML never names it
    monkeypatch.setenv("HARNESS_HOME", str(w.app.state.store_root))
    spec = next(s for s in bs._provider_specs() if s["name"] == "groq-x")
    assert spec["model"] == "llama-10" and spec["declared"]["weights_revision"] == "llama-10"
    monkeypatch.setattr(bs, "_probe_ollama", lambda *a, **k: ProviderRegistry())
    _, rt, _ = bs.build_gate(Path(w.app.state.store_root) / "trace-t.db",
                             Path("data/routing-a1.yaml"))
    reg = ProviderRegistry()
    for n, t in (("ollama-local", "local"), ("groq-x", "cloud")):
        reg.upsert(ProviderConfig(name=n, base_url="http://127.0.0.1:9/v1", model="m", models=[],
                                  engine="ollama" if t == "local" else "cloud", tier=t,
                                  admitted="full"))
    pol = MatterPolicy(matter_ref="m", classification="LOCAL_PREFERRED")
    assert [c.name for c in rt.route("extraction", pol, reg)] == ["groq-x", "ollama-local"]


def test_hard_deletes_remove_content_and_keep_the_audit_chain(api_world):  # 2026-11-13
    import hashlib
    from harness.corpus import CorpusStore, _mtable, split_structure
    from harness.service import system
    w, h, A = api_world, api_world.h("admin"), api_world.A
    root = Path(w.app.state.store_root)
    text = "The transaction is voidable under section 297 of the Companies Act. " * 40
    up = w.client.post(f"/api/v1/matters/{A['mid']}/documents?filename=memo.txt",
                       content=text.encode(), headers=h).json()
    from harness.ingest_generic import extract_text
    text = extract_text(root / up["path"])      # what ingest indexes
    store = CorpusStore(root / "corpus.sqlite3")
    with store._c() as c:     # seed the lexical index (ingest proper needs 1:1 vectors)
        t = {k: _mtable(A["mid"], k) for k in ("docs", "fts", "cites")}
        c.execute(f"CREATE TABLE {t['docs']}(doc_id TEXT PRIMARY KEY, source_name TEXT,"
                  " sha256 TEXT, words INTEGER, chunk_count INTEGER, ts TEXT)")
        c.execute(f"CREATE VIRTUAL TABLE {t['fts']} USING fts5(doc_id, heading, body)")
        c.execute(f"CREATE TABLE {t['cites']}(key TEXT, fts_rowid INTEGER)")
        c.execute(f"INSERT INTO {t['docs']} VALUES('c1','memo.txt',?,1,1,'t')",
                  (hashlib.sha256(text.encode()).hexdigest(),))
        c.executemany(f"INSERT INTO {t['fts']} VALUES(?,?,?)",
                      [(ch.doc_id, ch.heading, ch.text) for ch in split_structure("c1", text)])
    assert w.client.get(f"/api/v1/documents/{up['doc_id']}/chunks", headers=h).json()["chunks"]
    # document: file, row and searchable passages all go
    r = w.client.delete(f"/api/v1/documents/{up['doc_id']}", headers=h)
    assert r.status_code == 204, r.text
    assert not (root / up["path"]).exists()
    assert store.search_lexical(A["mid"], "voidable transaction") == []
    assert w.client.get(f"/api/v1/documents/{up['doc_id']}", headers=h).status_code == 404
    # draft
    assert w.client.delete(f"/api/v1/artifacts/{A['art']}", headers=h).status_code == 204
    assert w.client.get(f"/api/v1/artifacts/{A['art']}", headers=h).status_code == 404
    # matter: refused while its run is live, then everything goes but the audit chain
    r = w.client.delete(f"/api/v1/matters/{A['mid']}", headers=h)
    assert (r.status_code, code(r)) == (409, "invalid_transition"), r.text
    w.client.post(f"/api/v1/executions/{A['eid']}/cancel", json={"reason": "r"}, headers=h)
    assert w.client.delete(f"/api/v1/matters/{A['mid']}", headers=h).status_code == 204
    assert w.client.get(f"/api/v1/matters/{A['mid']}", headers=h).status_code == 404
    assert not (root / "documents" / A["mid"]).exists()
    con = system.open_db(root)
    acts = {r["action"] for r in con.execute(
        "SELECT action FROM audit_events WHERE matter_id=?", (A["mid"],))}
    assert not con.execute("SELECT 1 FROM tasks WHERE execution_id=?", (A["eid"],)).fetchone()
    con.close()
    assert {"matter.created", "document.deleted", "artifact.deleted", "matter.deleted"} <= acts
    assert w.client.get(f"/api/v1/matters/{w.B['mid']}", headers=h).status_code == 200


def test_delete_added_provider_only(api_world):
    w, h = api_world, api_world.h("admin")
    url = "/api/v1/settings/providers"
    w.client.post(url, headers=h, json={"name": "gone-x", "engine": "cloud", "model": "m",
                                        "base_url": "https://a.example/v1", "api_key": "k"})
    w.client.put("/api/v1/settings/assign?task_class=drafting", headers=h, json={"provider": "gone-x"})
    assert w.client.delete(f"{url}?name=gone-x", headers=h).status_code == 204
    body = w.client.get(url, headers=h).json()
    assert "gone-x" not in {p["name"] for p in body["providers"]}
    assert next(s for s in body["stages"] if s["task_class"] == "drafting")["assign"] is None
    from harness.keychain import get_key
    assert get_key("gone-x") is None
    r = w.client.delete(f"{url}?name=nvidia-nim", headers=h)
    assert (r.status_code, code(r)) == (409, "conflict"), r.text
    assert w.client.delete(f"{url}?name=nope", headers=h).status_code == 404


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


def test_seed_operator_creates_missing_store(harness_home, monkeypatch):
    from harness.api.__main__ import main
    from harness.paths import resolve_store_root
    from harness.service import auth, system
    monkeypatch.setattr(auth, "_ITER", 1000)
    monkeypatch.delenv("HARNESS_OPERATOR_PASSWORD", raising=False)
    root = resolve_store_root()[0]
    assert not Path(root).exists()        # the guide's fresh-store case
    assert main(["seed-operator"]) == 0
    con = system.open_db(root)
    try:
        assert con.execute("SELECT 1 FROM users WHERE username='admin'").fetchone()
    finally:
        con.close()
