"""M10 T1: users/roles admin API (05 §12, 03 §2.3-2.5). Only user.admin may list,
create or change users and list roles; deactivation kills live tokens; a role
change applies on the next request; matter access still needs membership."""
from __future__ import annotations

import pytest
from test_api_authz import code

U = "/api/v1/users"


def test_admin_crud_happy_path(api_world):
    w, h = api_world, api_world.h("admin")
    r = w.client.post(U, json={"username": "newbie", "password": "pw"}, headers=h)
    assert r.status_code == 201, r.text
    uid = r.json()["user_id"]
    assert r.json()["role_id"] == "reader" and r.json()["is_active"] is True
    assert "pw_hash" not in r.json()
    listed = w.client.get(U, headers=h).json()
    assert uid in {u["user_id"] for u in listed}
    assert all("pw_hash" not in u for u in listed)
    r = w.client.patch(f"{U}/{uid}", json={"role_id": "editor"}, headers=h)
    assert (r.status_code, r.json()["role_id"]) == (200, "editor")
    r = w.client.patch(f"{U}/{uid}", json={"is_active": False}, headers=h)
    assert (r.status_code, r.json()["is_active"]) == (200, False)
    roles = {x["role_id"]: x for x in w.client.get("/api/v1/roles", headers=h).json()}
    assert {"admin", "editor", "reader"} <= set(roles)
    assert "user.admin" in roles["admin"]["permissions"]
    assert "user.admin" not in roles["editor"]["permissions"]
    audit = w.client.get("/api/v1/audit?limit=200", headers=h).json()["items"]
    assert {"user.created", "user.updated"} <= {a["action"] for a in audit}


def test_create_validation_and_conflict(api_world):
    w, h = api_world, api_world.h("admin")
    r = w.client.post(U, json={"username": "z", "password": "pw", "role_id": "nope"},
                      headers=h)
    assert (r.status_code, code(r)) == (422, "validation_failed")
    r = w.client.post(U, json={"username": "admin", "password": "pw"}, headers=h)
    assert (r.status_code, code(r)) == (409, "user_exists")
    r = w.client.patch(f"{U}/u-missing", json={"role_id": "reader"}, headers=h)
    assert (r.status_code, code(r)) == (404, "user_not_found")


@pytest.mark.parametrize("role", ["editor", "reader", "outsider", "auditor"])
def test_member_without_user_admin_cannot_see_or_act(api_world, role):
    w, h = api_world, api_world.h(role)
    uid = w.users["spare"]
    for r in (w.client.get(U, headers=h),
              w.client.get("/api/v1/roles", headers=h),
              w.client.post(U, json={"username": "sneak", "password": "pw"}, headers=h),
              w.client.patch(f"{U}/{uid}", json={"role_id": "admin"}, headers=h),
              w.client.patch(f"{U}/{w.users[role]}", json={"role_id": "admin"}, headers=h)):
        assert (r.status_code, code(r)) == (403, "permission_denied"), r.text
    # nothing changed: the self-promotion attempt did not land
    me = w.client.get("/api/v1/auth/me", headers=h).json()
    assert "user.admin" not in me["permissions"]


def test_deactivated_user_live_token_stops_working(api_world):
    w = api_world
    assert w.client.get("/api/v1/auth/me", headers=w.h("reader")).status_code == 200
    r = w.client.patch(f"{U}/{w.users['reader']}", json={"is_active": False},
                       headers=w.h("admin"))
    assert r.status_code == 200
    r = w.client.get("/api/v1/auth/me", headers=w.h("reader"))
    assert (r.status_code, code(r)) == (401, "unauthenticated")


def test_role_change_takes_effect_on_next_request(api_world):
    w = api_world
    assert w.client.get(U, headers=w.h("reader")).status_code == 403
    w.client.patch(f"{U}/{w.users['reader']}", json={"role_id": "admin"},
                   headers=w.h("admin"))
    perms = w.client.get("/api/v1/auth/me", headers=w.h("reader")).json()["permissions"]
    assert "user.admin" in perms
    assert w.client.get(U, headers=w.h("reader")).status_code == 200


def test_cannot_remove_the_last_active_user_admin(api_world):
    w, h = api_world, api_world.h("admin")
    aid = w.users["admin"]
    for body in ({"is_active": False}, {"role_id": "reader"}):
        r = w.client.patch(f"{U}/{aid}", json=body, headers=h)
        assert (r.status_code, code(r)) == (409, "invalid_transition"), r.text
    me = w.client.get("/api/v1/auth/me", headers=h).json()   # rolled back: still admin
    assert "user.admin" in me["permissions"]
    # with a second admin in place, the first may step down
    w.client.patch(f"{U}/{w.users['editor']}", json={"role_id": "admin"}, headers=h)
    assert w.client.patch(f"{U}/{aid}", json={"is_active": False}, headers=h).status_code == 200


def test_new_user_needs_membership_for_matter_access(api_world):
    w, h = api_world, api_world.h("admin")
    uid = w.client.post(U, json={"username": "late", "password": "pw",
                                 "role_id": "editor"}, headers=h).json()["user_id"]
    tok = w.client.post("/api/v1/auth/login",
                        json={"username": "late", "password": "pw"}).json()["token"]
    lh = {"Authorization": f"Bearer {tok}"}
    mid = w.A["mid"]
    r = w.client.get(f"/api/v1/matters/{mid}", headers=lh)
    assert (r.status_code, code(r)) == (404, "matter_not_found")
    assert w.client.put(f"/api/v1/matters/{mid}/members/{uid}", json={"role_id": "reader"},
                        headers=h).status_code == 200
    assert w.client.get(f"/api/v1/matters/{mid}", headers=lh).status_code == 200
    r = w.client.patch(f"/api/v1/matters/{mid}", json={"title": "x"}, headers=lh)
    assert (r.status_code, code(r)) == (403, "permission_denied")
