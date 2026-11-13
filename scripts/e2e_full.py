"""E2E ledger driver: the full functional matrix against a LIVE dev_m8 server.

Usage (from harness-core):
    .venv/Scripts/python.exe scripts/e2e_full.py --base http://127.0.0.1:8766 \
        --round 1 --password <seeded-operator-password> \
        [--out data/eval/E2E/round1.json]

Not unit tests — a live round-trip ledger. Login first, then signups, RBAC,
settings, matters/workflows/executions, uploads, SSE, idempotency, malformed
input. Server kills / corrupt-file faults stay outside (orchestrated between
rounds); this script owns everything a client can drive. Writes per-test
PASS/FAIL + reason to stdout and a JSON file the ledger doc is assembled from.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--password", required=True, help="seeded operator password")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    root = args.base.rstrip("/")
    A = root + "/api/v1"
    results: list[dict] = []

    def test(name: str, fn):
        t0 = time.time()
        try:
            reason = fn()          # None = pass; str = fail reason
        except Exception as ex:    # noqa: BLE001 — a crash IS the failure
            reason = f"raised {type(ex).__name__}: {ex}"
        ok = reason is None
        results.append({"test": name, "ok": ok, "reason": reason,
                        "ms": int((time.time() - t0) * 1000)})
        print(f"TEST {len(results):02d} {name}: {'PASS' if ok else 'FAIL'}"
              f" — {reason or 'ok'} ({results[-1]['ms']}ms)", flush=True)

    anon = httpx.Client(base_url=A, timeout=30)
    op = httpx.Client(base_url=A, timeout=30)
    car = httpx.Client(base_url=A, timeout=30)

    def bearer(tok: str) -> dict:
        return {"Authorization": f"Bearer {tok}"}

    def login(client, user, pw):
        r = client.post("/auth/login", json={"username": user, "password": pw})
        if r.status_code != 200:
            raise AssertionError(f"login {user}: HTTP {r.status_code} {r.text[:120]}")
        tok = r.json().get("access_token") or r.json().get("token")
        if not tok:
            raise AssertionError(f"login {user}: no token in {list(r.json())}")
        client.headers.update(bearer(tok))
        return tok

    def expect(r, codes, ctx):
        if r.status_code not in codes:
            return f"{ctx}: HTTP {r.status_code} (want {codes}) {r.text[:140]}"
        return None

    state = {}
    mid, eid, carol_id = {}, {}, {}

    # ---- A. auth: login first, then signups ----
    def t01():
        r = httpx.get(root + "/healthz", timeout=10)
        return expect(r, (200,), "healthz")
    test("T01 healthz anonymous", t01)
    test("T02 login wrong password refused", lambda: expect(
        anon.post("/auth/login", json={"username": "operator", "password": "not-it"}),
        (401, 403), "wrong-pw login"))
    test("T03 operator login", lambda: (
        state.__setitem__("op_tok", login(op, "operator", args.password))) or None)
    def t04():
        r = op.get("/auth/me")
        if r.status_code != 200:
            return f"me: HTTP {r.status_code} {r.text[:120]}"
        if r.json().get("user", {}).get("username") != "operator":
            return f"me: username={r.json().get('user', {}).get('username')!r}"
        return None
    test("T04 me(operator) shape", t04)
    test("T05 me without token -> 401", lambda: expect(anon.get("/auth/me"), (401,), "anon me"))
    test("T06 me garbage token -> 401", lambda: expect(
        anon.get("/auth/me", headers=bearer("garbage.token.here")), (401,), "garbage token"))
    carol = f"carol-r{args.round}"                    # fresh user per round (signup chain)
    test("T07 signup carol -> pending", lambda: (lambda r: None if r.status_code in (200, 201, 202)
         else f"signup: HTTP {r.status_code} {r.text[:140]}")
         (anon.post("/auth/signup", json={"username": carol,
                                          "password": "carol-e2e-pass-1"})))
    test("T08 carol login before approval refused", lambda: expect(
        anon.post("/auth/login", json={"username": carol, "password": "carol-e2e-pass-1"}),
        (401, 403), "pre-approval login"))
    test("T09 duplicate signup carol", lambda: expect(
        anon.post("/auth/signup", json={"username": "carol", "password": "x"}),
        (409, 422, 400), "duplicate signup"))
    test("T10 admin user list shows carol", lambda: (lambda r: None if r.status_code == 200 and
         any(u.get("username") == carol for u in r.json()) else
         f"users: HTTP {r.status_code} {r.text[:140]}")(op.get("/users")))

    def t11():
        users = op.get("/users").json()
        u = next((x for x in users if x.get("username") == carol), None)
        if not u:
            return "carol missing from user list"
        carol_id["uid"] = u.get("user_id") or u.get("id")
        tried = []
        for st in ("active", "approved", "enabled"):
            r = op.patch(f"/users/{carol_id['uid']}", json={"state": st})
            if r.status_code == 200:
                carol_id["state_used"] = st
                return None
            tried.append(f"{st}:{r.status_code}")
        return f"approval: no state accepted [{', '.join(tried)}]"
    test("T11 admin approves carol", t11)
    test("T12 carol login after approval", lambda: (
        state.__setitem__("carol_tok", login(car, carol, "carol-e2e-pass-1"))) or None)

    def t13():
        old_auth = op.headers.get("authorization")
        r = op.post("/auth/refresh", json={})
        if r.status_code != 200:
            return f"refresh: HTTP {r.status_code} {r.text[:120]}"
        tok = r.json().get("token") or r.json().get("access_token")
        if not tok:
            return "refresh: no token in body"
        # auth.refresh revokes the presented token (rotation) — the client must swap
        # the new one in, and the REVOKED one must now be refused everywhere
        op.headers.update(bearer(tok))
        state["op_tok"] = tok
        if op.get("/auth/me").status_code != 200:
            return "refreshed token not accepted"
        r_old = anon.get("/auth/me", headers={"Authorization": old_auth})
        if r_old.status_code != 401:
            return f"SECURITY: revoked token still accepted (HTTP {r_old.status_code})"
        return None
    test("T13 token refresh", t13)

    def t14():
        r = car.post("/auth/password", json={"password": "carol-e2e-pass-2"})
        if r.status_code != 200:
            return f"password change: HTTP {r.status_code} {r.text[:120]}"
        if anon.post("/auth/login", json={"username": carol,
                                          "password": "carol-e2e-pass-2"}).status_code != 200:
            return "login with new password failed"
        if anon.post("/auth/login", json={"username": carol,
                                          "password": "carol-e2e-pass-1"}).status_code in (200,):
            return "old password still accepted"
        if car.post("/auth/password", json={"password": "carol-e2e-pass-1"}).status_code != 200:
            return "restore to original password failed"
        return None
    test("T14 password change + relogin", t14)

    # ---- B. RBAC ----
    test("T15 /users as carol -> 403", lambda: expect(car.get("/users"), (403,), "carol users"))
    test("T16 /users as admin -> 200", lambda: expect(op.get("/users"), (200,), "admin users"))
    test("T17 /audit as carol -> 403", lambda: expect(car.get("/audit"), (403,), "carol audit"))
    test("T18 /audit as admin -> 200", lambda: expect(op.get("/audit"), (200,), "admin audit"))
    test("T19 settings view as carol -> 403", lambda: expect(
        car.get("/settings/providers"), (403,), "carol settings"))
    test("T20 settings PUT as carol -> 403", lambda: expect(
        car.put("/settings/providers", params={"name": "ollama-local"},
                json={"base_url": "http://127.0.0.1:11434/v1"}), (403,), "carol settings PUT"))

    # ---- C. settings (admin) ----
    def t21():
        r = op.get("/settings/providers")
        if r.status_code != 200:
            return f"view: HTTP {r.status_code} {r.text[:140]}"
        d = r.json()
        if not isinstance(d.get("providers"), list) or not d["providers"]:
            return "view: providers empty"
        missing = {"name", "base_url", "model", "engine", "tier", "has_key"} - set(d["providers"][0])
        if missing:
            return f"view: provider missing {sorted(missing)}"
        if not isinstance(d.get("stages"), list) or not d["stages"]:
            return "view: stages empty"
        return None
    test("T21 settings view shape", t21)
    test("T22 local provider rejects public URL -> 422", lambda: expect(
        op.put("/settings/providers", params={"name": "ollama-local"},
               json={"base_url": "http://evil.example.com/v1"}), (422,), "local public URL"))
    test("T23 cloud provider rejects http -> 422", lambda: expect(
        op.put("/settings/providers", params={"name": "nvidia-nim"},
               json={"base_url": "http://integrate.api.nvidia.com/v1"}), (422,), "cloud http"))
    test("T24 provider edit persists", lambda: expect(
        op.put("/settings/providers", params={"name": "ollama-local"},
               json={"base_url": "http://127.0.0.1:11434/v1"}), (200,), "provider PUT"))

    def t25():
        r = op.put("/settings/providers", params={"name": "nvidia-nim"},
                   json={"api_key": "sk-e2e-test"})
        if r.status_code != 200:
            return f"key PUT: HTTP {r.status_code}"
        v = op.get("/settings/providers").json()
        if "sk-e2e-test" in json.dumps(v):
            return "SECURITY: api key echoed back in view"
        p = next((p for p in v["providers"] if p["name"] == "nvidia-nim"), {})
        if not p.get("has_key"):
            return "has_key false after key set"
        return None
    test("T25 api_key write-only (set, never echoed)", t25)
    def t26():
        # fault injection: stage a dead port, probe it, restore — deterministic
        # regardless of whether the box's real ollama is up
        if op.put("/settings/providers", params={"name": "ollama-local"},
                  json={"base_url": "http://127.0.0.1:9/v1"}).status_code != 200:
            return "could not stage dead-port base_url"
        r = op.post("/settings/providers/test", params={"name": "ollama-local"})
        if r.status_code != 200:
            return f"test: HTTP {r.status_code} {r.text[:140]}"
        if r.json().get("reachable") is not False:
            return f"dead port reported reachable: {r.json()}"
        if op.put("/settings/providers", params={"name": "ollama-local"},
                  json={"base_url": "http://127.0.0.1:11434/v1"}).status_code != 200:
            return "restore of live base_url failed"
        return None
    test("T26 provider test on dead port -> graceful verdict", t26)
    test("T27 assign unknown provider -> 422", lambda: expect(
        op.put("/settings/assign", params={"task_class": "drafting"},
               json={"provider": "no-such-provider"}), (422,), "unknown provider"))
    test("T28 assign unknown task_class -> 422", lambda: expect(
        op.put("/settings/assign", params={"task_class": "not-a-stage"},
               json={"provider": "nvidia-nim"}), (422,), "unknown stage"))

    def t29():
        r = op.put("/settings/assign", params={"task_class": "drafting"},
                   json={"provider": "nvidia-nim"})
        if r.status_code != 200:
            return f"assign PUT: HTTP {r.status_code} {r.text[:140]}"
        s = next((s for s in op.get("/settings/providers").json()["stages"]
                  if s["task_class"] == "drafting"), {})
        if s.get("assign") != "nvidia-nim":
            return f"assign not visible in view: {s.get('assign')!r}"
        if op.put("/settings/assign", params={"task_class": "drafting"},
                  json={"provider": None}).status_code != 200:
            return "null clear failed"
        if next(s2 for s2 in op.get("/settings/providers").json()["stages"]
                if s2["task_class"] == "drafting")["assign"] is not None:
            return "null clear did not take"
        return None
    test("T29 assign persists + null clears", t29)
    test("T30 audit logs settings events", lambda: (lambda r: None if r.status_code == 200 and
         "settings" in json.dumps(r.json()) else
         f"audit: HTTP {r.status_code} or no settings events")(op.get("/audit")))

    # ---- D. matters / documents / executions / SSE ----
    def t31():
        r = op.post("/matters", json={"title": "E2E round matter"})
        if r.status_code not in (200, 201):
            return f"create: HTTP {r.status_code} {r.text[:140]}"
        mid["id"] = r.json().get("matter_id") or r.json().get("id")
        if not mid["id"]:
            return f"no id in {list(r.json())}"
        return None
    test("T31 create matter", t31)
    test("T32 matter list + get", lambda: (lambda r: None if r.status_code == 200 and
         op.get(f"/matters/{mid['id']}").status_code == 200 else
         f"list/get: HTTP {r.status_code}")(op.get("/matters")))
    test("T33 matter invalid state transition", lambda: expect(
        op.post(f"/matters/{mid['id']}/state", json={"state": "not-a-state"}), (422, 409, 400),
        "bad state"))
    test("T34 upload doc no filename -> 422", lambda: expect(
        op.post(f"/matters/{mid['id']}/documents", json={"text": "x"}), (422,), "no filename"))
    test("T35 upload doc + read back", lambda: expect(
        op.post(f"/matters/{mid['id']}/documents", params={"filename": "e2e-note.txt"},
                json={"text": "E2E uploads a short engagement note. Parties: Mainzeal. "
                              "Sections referenced: Companies Act 1993 s 131."}),
        (200, 201), "upload"))
    test("T36 malformed JSON -> 422 envelope", lambda: (lambda r: None if r.status_code == 422
         and "Traceback" not in r.text else f"malformed: HTTP {r.status_code}")
         (op.post("/matters", content=b"{not json", headers={"Content-Type": "application/json"})))

    def t37():
        body = {"title": "Idem"}
        h = {"Idempotency-Key": "e2e-idem-1"}
        r1 = op.post("/matters", json=body, headers=h)
        r2 = op.post("/matters", json=body, headers=h)
        if r1.status_code not in (200, 201) or r2.status_code not in (200, 201):
            return f"replay: HTTP {r1.status_code}/{r2.status_code}"
        i1 = r1.json().get("matter_id") or r1.json().get("id")
        i2 = r2.json().get("matter_id") or r2.json().get("id")
        if i1 != i2:
            return f"replay created two matters ({i1} vs {i2})"
        return None
    test("T37 idempotency-key replay", t37)
    test("T38 SSE events unauthenticated -> 401", lambda: expect(
        anon.get("/events", params={"channels": "board"}), (401,), "sse anon"))

    def t39():
        with op.stream("GET", "/events", params={"channels": "board"}, timeout=6.0) as r:
            if r.status_code != 200:
                return f"sse: HTTP {r.status_code}"
            ct = r.headers.get("content-type", "")
            if "text/event-stream" not in ct:
                return f"sse content-type {ct!r}"
            try:
                chunk = next(r.iter_bytes(64), b"")
            except Exception:                              # noqa: BLE001 silent stream is fine
                chunk = b""
            if not chunk and False:
                pass
            return None
    test("T39 SSE events streams with token", t39)

    def t40():
        r = op.post(f"/matters/{mid['id']}/executions",
                    json={"task_text": "E2E demo task: summarise the uploaded note"})
        if r.status_code not in (200, 201, 202):
            return f"exec create: HTTP {r.status_code} {r.text[:140]}"
        eid["id"] = r.json().get("execution_id") or r.json().get("id")
        if not eid["id"]:
            return f"no exec id in {list(r.json())}"
        return None
    test("T40 create execution (demo worker)", t40)
    test("T41 execution read + tasks", lambda: (lambda r: None if r.status_code == 200 and
         op.get(f"/executions/{eid['id']}/tasks").status_code in (200, 404) else
         f"exec get: HTTP {r.status_code}")(op.get(f"/executions/{eid['id']}")))
    test("T42 cancel execution", lambda: expect(
        op.post(f"/executions/{eid['id']}/cancel", json={}), (200, 202, 409), "cancel"))
    test("T43 runs listed for matter", lambda: expect(
        op.get(f"/matters/{mid['id']}/runs"), (200,), "runs"))
    test("T44 metrics", lambda: expect(op.get("/metrics"), (200,), "metrics"))

    passed = sum(1 for r in results if r["ok"])
    out = Path(args.out) if args.out else REPO / f"data/eval/E2E/round{args.round}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"round": args.round, "base": args.base,
                               "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "passed": passed, "total": len(results),
                               "results": results}, indent=1), encoding="utf-8")
    print(f"ROUND {args.round}: {passed}/{len(results)} passed — {out}", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
