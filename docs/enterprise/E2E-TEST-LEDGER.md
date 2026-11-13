# E2E test ledger — live app, 2026-11-12

Live end-to-end testing of the running harness (API + web client + demo worker)
against a real store, with the server restarted between every round. Each test
is recorded as **test N: name — PASS/FAIL, reason, debugged**.

## How to run a round (the repeatable process)

1. Build the client: `cd web && npm run build`.
2. Start the server fresh on a throwaway store:
   `.venv/Scripts/python.exe scripts/dev_m8.py --store %TEMP%/ironfleet-e2e --port 8765`
   (the desktop preview config `harness-e2e` does this; it lands on 8766 when 8765 is taken).
3. Run the driver:
   `.venv/Scripts/python.exe scripts/e2e_full.py --base http://127.0.0.1:8766 --round N --password <operator password>`
4. Read the verdicts (`TEST n …: PASS|FAIL — reason`) and `data/eval/E2E/roundN.json`.
5. Any FAIL: decide whether the product or the driver is wrong, fix it, run the
   unit suites (`pytest tests/test_api.py tests/test_api_authz.py`), **restart the
   server**, and run round N+1. Stop when a full round passes.

The driver is `scripts/e2e_full.py` — 44 HTTP tests covering auth (login first,
then signup), RBAC, model settings, matters, documents, SSE, executions and metrics.
Signup names are per round (`carol-r{N}`) so restarts on a persistent store don't
collide.

## Summary

| Round | Server | Result | Outcome |
|---|---|---|---|
| 1 | fresh start | 19/44 | driver bugs (response shape, token rotation) — fixed in driver |
| 2 | restarted | 40/44 | **real product bug: provider Test → 500** — fixed; 3 driver issues fixed |
| 3 | restarted | 43/44 | T26 premise wrong (port 11434 had a live Ollama) — driver now stages a dead port |
| 4 | restarted | **44/44** | clean |
| F1–F3 | kill/restart | all PASS | fault injection: hard kill, corrupt settings file, oversize/concurrency |
| UI-1 | restarted | 7/8 | **real UI bug: every local provider showed "key set"** — fixed |
| 5 | restarted | **44/44** | regression round after the UI fix |
| UI-2 | same server | 8/8 | clean |

Product bugs found and fixed: **2**. Unit suites after each fix: `181 passed`.

## Round 1 — 19/44 (server: fresh start)

- test 4: T04 me(operator) shape — FAIL, reason: driver read `username` at top level; `/auth/me` returns `{"user": {"username": …}}`. debugged: driver reads `d["user"]["username"]`.
- test 13: T13 token refresh — FAIL (and caused T14–T44 cascade), reason: `auth.refresh` revokes the presented token (`service/auth.py:124`, by design); the driver kept using the old bearer, so every later call got 401 "bearer token required". debugged: driver swaps to the new token and now *asserts* the old one is refused (rotation is a feature, tested as such).
- tests 34–35, 39–42: KeyError `'id'` — FAIL, reason: cascade from T13 (no matter created), plus the driver read `id` instead of `matter_id`/`execution_id`. debugged: driver uses the service's id keys; each test fails with a message instead of raising.
- all remaining FAILs in round 1 were the same 401 cascade from T13.

Restart server → round 2.

## Round 2 — 40/44 (server: restarted, same store)

- test 7: T07 signup carol — FAIL, reason: 409 `user_exists` — `carol` persisted from round 1 (store survives restarts — correct behaviour). debugged: driver signs up `carol-r{round}`.
- test 8: T08 login before approval refused — FAIL, reason: 200 — it logged in the round-1 `carol`, who was already approved. debugged: same fix as T07; a new user is pending, and pending login is refused.
- test 26: T26 provider test — **FAIL, reason: HTTP 500 — real product bug.** `settings._probe_one` called `asyncio.run()` from inside the ASGI event loop → `RuntimeError: asyncio.run() cannot be called from a running event loop`. Unit suites never saw it because `tests/conftest.py` monkeypatches `_probe_one`. debugged: `_probe_one` and `test_provider` are now `async def` and `await register_provider` directly ([settings.py:120](../../src/harness/service/settings.py)); the route awaits it ([core.py:142](../../src/harness/api/routes/core.py)); the conftest canned probe is now `async def`. Only caller chain: route → `test_provider` → `_probe_one` (tree grep). `pytest tests/test_api.py tests/test_api_authz.py` → 181 passed.
- test 39: T39 SSE with token — FAIL, reason: 422 — driver asked for channel `matters`; valid channels are `board` and `matter:{id}`. debugged: driver subscribes to `board`.

Restart server → round 3.

## Round 3 — 43/44 (server: restarted)

- test 26: T26 provider test on dead port — FAIL, reason: 200 with `reachable: true` — the test assumed nothing listens on 11434, but a real Ollama does on this box. The 500 is gone (the fix works). debugged: driver now stages `http://127.0.0.1:9/v1` (closed port) on `ollama-local`, expects `reachable: false`, then restores 11434.

Restart server → round 4.

## Round 4 — 44/44 (server: restarted)

All 44 PASS. See round 5 for the full per-test list (identical verdicts).

## Fault-injection rounds (system breakages)

- test F1: hard kill mid-session — PASS, reason: staged a token, matter `m-48ce4ba239f3` and an uploaded document, killed the server (no graceful shutdown), restarted; the pre-kill token still authenticated, matter + document + settings all read back intact. debugged: n/a.
- test F2: corrupt `model-settings.json` (`{corrupt json!!!`) — PASS, reason: `GET /settings/providers` → 200 with stock providers (`_load` treats unreadable JSON as empty), `PUT /settings/assign` → 200 and rewrote a valid file (self-heal). debugged: n/a.
- test F3a: 2 MB document upload — PASS, reason: 201, stored and readable.
- test F3b: `text/plain` body on a JSON endpoint — PASS, reason: 422 envelope, no traceback leaked.
- test F3c: 12-way concurrent login + matter create — PASS, reason: all 12 → 201, no `database is locked`.
- test F (driver T26): provider unreachable — PASS, reason: dead port gives a `reachable: false` verdict, not an error.
- test F (driver T36): malformed JSON — PASS, reason: 422 envelope, no traceback.

Evidence: F-rounds ran as ad-hoc scripts; their output is in the session transcript, not a JSON file.

## UI round 1 — 7/8 (browser, server: restarted after round 4)

- test U1: sign in via form → matters board — PASS.
- test U2: Users & roles lists operator + approved signups with role selects — PASS.
- test U3: Model settings renders providers + per-stage assignment — PASS.
- test U4: provider key badge — **FAIL, reason: every local provider showed "key set"**. The OS keyring held empty-string entries for keyless locals (written by earlier probe registrations) and `has_key` was `get_key(...) is not None`, so `""` counted as a key. debugged: `has_key` is now `bool(get_key(...))` in `view` and `put_provider` ([settings.py:88](../../src/harness/service/settings.py)). 181 API tests pass.
- test U5: Sign out → login screen with "Request an account" — PASS.
- test U6: UI signup `dave-ui` → "Request sent… administrator must approve" — PASS.
- test U7: `dave-ui` login before approval → "bad username or password" (refused, no account-state leak) — PASS.
- test U8: admin approves, `dave-ui` signs in → nav shows only Matters / Approvals / New matter (no admin screens) — PASS.

Restart server → round 5.

## Round 5 — 44/44 (server: restarted after the has_key fix)

- test 1: T01 healthz anonymous — PASS, reason: 200.
- test 2: T02 login wrong password refused — PASS, reason: 401.
- test 3: T03 operator login — PASS, reason: token issued.
- test 4: T04 me(operator) shape — PASS, reason: `user.username == operator`.
- test 5: T05 me without token — PASS, reason: 401.
- test 6: T06 me garbage token — PASS, reason: 401.
- test 7: T07 signup carol-r5 — PASS, reason: 201, state pending.
- test 8: T08 login before approval — PASS, reason: refused.
- test 9: T09 duplicate signup — PASS, reason: 409.
- test 10: T10 admin user list shows carol-r5 — PASS.
- test 11: T11 admin approves — PASS, reason: PATCH state active → 200.
- test 12: T12 login after approval — PASS.
- test 13: T13 token refresh — PASS, reason: new token works, old token → 401.
- test 14: T14 password change + relogin — PASS, reason: old password refused, new accepted, restored.
- test 15: T15 /users as carol — PASS, reason: 403.
- test 16: T16 /users as admin — PASS, reason: 200.
- test 17: T17 /audit as carol — PASS, reason: 403.
- test 18: T18 /audit as admin — PASS, reason: 200.
- test 19: T19 settings view as carol — PASS, reason: 403.
- test 20: T20 settings PUT as carol — PASS, reason: 403.
- test 21: T21 settings view shape — PASS.
- test 22: T22 local provider public URL — PASS, reason: 422.
- test 23: T23 cloud provider http:// — PASS, reason: 422.
- test 24: T24 provider edit persists — PASS.
- test 25: T25 api_key write-only — PASS, reason: never echoed, `has_key` true.
- test 26: T26 provider test on dead port — PASS, reason: `reachable: false`, restored.
- test 27: T27 assign unknown provider — PASS, reason: 422.
- test 28: T28 assign unknown task_class — PASS, reason: 422.
- test 29: T29 assign persists + null clears — PASS.
- test 30: T30 audit logs settings events — PASS.
- test 31: T31 create matter — PASS, reason: 201.
- test 32: T32 matter list + get — PASS.
- test 33: T33 invalid state transition — PASS, reason: bogus state refused (4xx).
- test 34: T34 upload without filename — PASS, reason: 422.
- test 35: T35 upload — PASS, reason: 201 (status only; byte read-back was checked in F1, not here).
- test 36: T36 malformed JSON — PASS, reason: 422 envelope, no traceback.
- test 37: T37 Idempotency-Key replay — PASS, reason: same matter id returned.
- test 38: T38 SSE unauthenticated — PASS, reason: 401.
- test 39: T39 SSE with token (`board`) — PASS, reason: event-stream content type.
- test 40: T40 create execution (demo worker) — PASS.
- test 41: T41 execution read + tasks — PASS.
- test 42: T42 cancel execution — PASS.
- test 43: T43 runs listed for matter — PASS.
- test 44: T44 metrics — PASS.

## UI round 2 — 8/8 (same server as round 5)

U1–U8 repeated; U4 now shows "no key" on the four local providers and "key set"
on `nvidia-nim` / `nvidia-nim-tool` only. All PASS.

## Not covered

- Real model runs (executions use the demo worker; no LLM dispatch was exercised).
- UI coverage is the main paths (sign in, sign up, approve, users, settings), not every screen.
- F-rounds are not yet in `e2e_full.py`, so they are not one-command repeatable.
