# B — Signup + default admin/admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fresh store seeds admin/admin (forced password change); public signup requests; only user.admin approves; approved users sign in as reader.

**Architecture:** Two new `users` columns (`state`, `must_change_password`) added additively (CREATE TABLE + guarded ALTER for pre-B DBs). The gate lives in `get_principal` (one choke). Signup/password routes join the existing unauthenticated/principal auth routes. Spec: `docs/superpowers/specs/2026-11-11-b-signup-default-admin-design.md`.

**Tech Stack:** FastAPI + sqlite (row_factory Row), React 19, vitest (renderToString, no jsdom), pytest.

## Global Constraints
- No new dependencies.
- Never `pw_hash` in any list/row payload; audit events for signup/approve/reject/password-change.
- Windows: `write_text` needs `encoding="utf-8"`; Python via `.venv/Scripts/python.exe`.
- User commits; no co-author trailer.

---

### Task 1: Backend — columns, signup, gate, seed default

**Files:**
- Modify: `src/harness/workflow/db.py` (users CREATE TABLE + ALTER in `connect`)
- Modify: `src/harness/service/auth.py`, `src/harness/service/users.py`
- Modify: `src/harness/api/deps.py`, `src/harness/api/routes/core.py`, `src/harness/api/schemas.py`, `src/harness/api/__main__.py`
- Test: `tests/test_b_signup.py` (new; mirror the fixture style used by `tests/test_api_layering.py`)

**Interfaces:**
- Produces: `auth.signup(con, username, password) -> {"user_id", "state": "pending"}`;
  `auth.set_password(con, principal, password) -> {"ok": True}`;
  `login(...)` and `/auth/me` gain `must_change_password: bool`;
  `users.patch` accepts `state: "active" | "rejected"`;
  deps `_AUTH_OK = {"/api/v1/auth/refresh", "/api/v1/auth/me", "/api/v1/auth/password"}`;
  schemas `SignupIn`, `PasswordIn`.

- [ ] **Step 1: Failing tests** — `tests/test_b_signup.py` (fresh-db service+API asserts):
  signup→login 401→admin approve→login 200 role reader; reject→401 + re-signup 409;
  default seed (create_user must_change_password=True)→login ok with flag→`GET /matters` 403
  `password_change_required`→`/auth/me` 200→`POST /auth/password` clears→`/matters` 200;
  non-admin patch `{state}` → 403; pre-B DB (table created without the columns, then
  `connect`) gains both columns with existing rows `active`/0.
- [ ] **Step 2:** `.venv/Scripts/python.exe -m pytest tests/test_b_signup.py -q` → FAIL.
- [ ] **Step 3: Implement** per the spec's Design section (all seven files listed above;
  drop the `getpass` prompt — no env var now seeds admin/admin + forced change, loudly printed).
- [ ] **Step 4:** `pytest tests/test_b_signup.py tests/test_api_layering.py -q` → PASS (layering
  guards "no permission checks in routes" — signup stays check-free because the service does it).
- [ ] **Step 5:** Full suite `.venv/Scripts/python.exe -m pytest -q` → PASS (any login-shape tests
  that unpack the old login payload get `must_change_password` added).

### Task 2: UI — signup card, forced change, Users state column

**Files:**
- Modify: `web/src/App.jsx` (export `Login` with `initialView` prop for tests; add `ChangePassword`; gate the shell on `me.data.must_change_password`)
- Modify: `web/src/screens/Users.jsx` (State cell + Approve/Reject; role select hidden on pending rows)
- Test: `web/src/auth.test.jsx` (new)

**Interfaces:**
- Consumes: `POST /auth/signup`, `POST /auth/password`, `/auth/me.must_change_password`, `PATCH /users/{uid}` with `{state}`.
- Produces: `Login({ onDone, initialView = "signin" })`, `ChangePassword({ onDone })` (both exported).

- [ ] **Step 1: Failing tests** — `web/src/auth.test.jsx`: `renderToString(<Login initialView="signup"/>)`
  contains "Request an account" + "Send request"; `initialView="sent"` contains "An administrator must
  approve it"; `<ChangePassword/>` has two password fields + "Save and continue";
  `<UsersView/>` with a `state:"pending"` fixture row shows Pending + Approve + Reject and no role
  select; a `must_change_password` admin row reads "Must set password".
- [ ] **Step 2:** `cd web && npx vitest run src/auth.test.jsx` → FAIL (not exported).
- [ ] **Step 3: Implement** per the spec's UI section.
- [ ] **Step 4:** `npx vitest run` (all files) → PASS; `npx vite build` → green.

### Task 3: Browser verify (same pattern as A's check script)

- [ ] Fresh store + Live server (worker demo): drive with playwright —
  login screen → "Request an account" → submit `newguy` → sent card; sign in
  `admin`/`admin` → Change-password card blocks the shell → set new password → shell;
  Users & roles → `newguy` Pending → Approve; sign out, sign in `newguy` → reader shell.
  Console clean; screenshot; user commits.
