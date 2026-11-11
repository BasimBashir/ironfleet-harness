# tests/test_b_signup.py — B (2026-11-11): public signup, admin-approved accounts,
# default admin/admin with a forced first-password change, pre-B db migration.
from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def world(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from harness.api.app import create_app
    from harness.service import auth, system

    monkeypatch.setattr(auth, "_ITER", 1000)          # pbkdf2 speed, tests only
    root = tmp_path / "store"
    root.mkdir()
    con = system.open_db(root)
    aid = auth.create_user(con, "admin", "admin", role_id="admin")
    ed = auth.create_user(con, "ed", "pw", role_id="editor")
    atok, etok = (auth._issue(con, u)["token"] for u in (aid, ed))
    con.close()
    client = TestClient(create_app(root, sse_heartbeat_s=0.05, sse_poll_s=0.01, sse_max_s=0.25))
    yield SimpleNamespace(client=client, root=root,
                          h=lambda t=atok: {"Authorization": f"Bearer {t}"}, etok=etok)
    client.close()


def code(r):
    try:
        return r.json().get("error", {}).get("code")
    except ValueError:
        return None


def test_signup_pends_then_admin_approves(world):
    c = world.client
    r = c.post("/api/v1/auth/signup", json={"username": "newguy", "password": "pw"})
    assert r.status_code == 201 and r.json()["state"] == "pending"
    assert code(c.post("/api/v1/auth/login",
                       json={"username": "newguy", "password": "pw"})) == "invalid_credentials"
    guy = next(u for u in c.get("/api/v1/users", headers=world.h()).json()
               if u["username"] == "newguy")
    assert guy["state"] == "pending" and guy["role_id"] == "reader" and guy["is_active"] is False
    assert c.patch(f"/api/v1/users/{guy['user_id']}", json={"state": "active"},
                   headers=world.h()).status_code == 200
    ok = c.post("/api/v1/auth/login", json={"username": "newguy", "password": "pw"}).json()
    assert ok["must_change_password"] is False
    h = {"Authorization": "Bearer " + ok["token"]}
    me = c.get("/api/v1/auth/me", headers=h).json()
    assert me["user"]["username"] == "newguy" and me["roles"] == ["reader"]
    assert me["must_change_password"] is False


def test_reject_keeps_username_reserved(world):
    c = world.client
    uid = c.post("/api/v1/auth/signup",
                 json={"username": "ghost", "password": "pw"}).json()["user_id"]
    assert c.patch(f"/api/v1/users/{uid}", json={"state": "rejected"},
                   headers=world.h()).status_code == 200
    rows = c.get("/api/v1/users", headers=world.h()).json()
    assert next(u for u in rows if u["username"] == "ghost")["state"] == "rejected"
    assert code(c.post("/api/v1/auth/login",
                       json={"username": "ghost", "password": "pw"})) == "invalid_credentials"
    assert c.post("/api/v1/auth/signup",
                  json={"username": "ghost", "password": "x"}).status_code == 409


def test_only_user_admin_decides(world):
    c = world.client
    uid = c.post("/api/v1/auth/signup",
                 json={"username": "nx", "password": "pw"}).json()["user_id"]
    r = c.patch(f"/api/v1/users/{uid}", json={"state": "active"},
                headers={"Authorization": f"Bearer {world.etok}"})
    assert (r.status_code, code(r)) == (403, "permission_denied")


def test_default_seed_forces_password_change(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from harness.api.app import create_app
    from harness.service import auth, system

    monkeypatch.setattr(auth, "_ITER", 1000)
    root = tmp_path / "store2"
    root.mkdir()
    con = system.open_db(root)
    uid = auth.create_user(con, "boots", "admin", role_id="admin", must_change_password=True)
    con.close()
    c = TestClient(create_app(root, sse_heartbeat_s=0.05, sse_poll_s=0.01, sse_max_s=0.25))
    try:
        ok = c.post("/api/v1/auth/login", json={"username": "boots", "password": "admin"}).json()
        assert ok["must_change_password"] is True
        h = {"Authorization": "Bearer " + ok["token"]}
        blocked = c.get("/api/v1/matters", headers=h)
        assert (blocked.status_code, code(blocked)) == (403, "password_change_required")
        assert c.get("/api/v1/auth/me", headers=h).status_code == 200
        r = c.post("/api/v1/auth/refresh", headers=h)   # refresh rotates the token
        assert r.status_code == 200
        h = {"Authorization": "Bearer " + r.json()["token"]}
        assert c.post("/api/v1/auth/password", json={"password": "real-pw"},
                      headers=h).status_code == 200
        assert c.get("/api/v1/matters", headers=h).status_code == 200
        assert c.get("/api/v1/auth/me", headers=h).json()["must_change_password"] is False
        assert uid.startswith("u-")
    finally:
        c.close()


def test_signup_and_decisions_are_audited(world):
    c = world.client
    c.post("/api/v1/auth/signup", json={"username": "aud", "password": "pw"})
    uid = c.post("/api/v1/auth/signup",
                 json={"username": "aud2", "password": "pw"}).json()["user_id"]
    c.patch(f"/api/v1/users/{uid}", json={"state": "rejected"}, headers=world.h())
    c.post("/api/v1/auth/password", json={"password": "np"}, headers=world.h())
    con = sqlite3.connect(world.root / "platform.db")
    acts = {r[0] for r in con.execute("SELECT action FROM audit_events")}
    con.close()
    assert {"user.signup_requested", "user.rejected", "user.password_changed"} <= acts


def test_pre_b_db_gains_columns(tmp_path):
    from harness.workflow.db import connect

    p = tmp_path / "old" / "platform.db"
    p.parent.mkdir()
    old = sqlite3.connect(p)
    old.executescript(
        "CREATE TABLE users(user_id TEXT PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT,"
        " role_id TEXT, is_active INTEGER DEFAULT 1, created_at TEXT);"
        "INSERT INTO users VALUES('u-old','old','x','reader',1,'t');")
    old.commit()
    old.close()
    con = connect(p)
    cols = {r["name"] for r in con.execute("PRAGMA table_info(users)")}
    assert {"state", "must_change_password"} <= cols
    row = con.execute("SELECT state, must_change_password FROM users").fetchone()
    assert row["state"] == "active" and row["must_change_password"] == 0
    con.close()
