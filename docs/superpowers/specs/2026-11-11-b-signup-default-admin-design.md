# B — Signup + default admin/admin + admin-approved signups (design)

Ask #8 of the 2026-11-11 nine-ask request: "make signup option and make a user admin
as default admin-user and only he/she can accept new signups use admin and admin for
user and pass." Accepted pushback: the default admin/admin is a bootstrap credential —
first sign-in must force a real password. Mockup picks (2026-11-11, this session):
signup = link under the login card; approvals = State column in the users table;
approved role = fixed reader.

## Goal

A fresh store boots with `admin` / `admin` (forced to set a real password at first
sign-in). Anyone can request an account from the public login screen; only a user with
`user.admin` can approve; approved accounts sign in as `reader`.

## Scope

Backend: `users` table columns, auth + users services, auth routes, the
must-change-password gate, `seed-operator` defaults.
UI: login card signup link, forced change-password card, Users table State column.
Out: email/verification, password reset, signup rate limiting, role choice at
approval (admin can promote later in Users & roles).

## Design

### Schema (additive only, `workflow/db.py`)
`users` gains two columns: `state TEXT DEFAULT 'active'` (`pending` | `active` |
`rejected`) and `must_change_password INTEGER DEFAULT 0`. The fresh `CREATE TABLE`
gets them; `connect()` also `ALTER TABLE users ADD COLUMN` for pre-B databases
(guarded by `PRAGMA table_info`), so existing users become `active` / no forced
change. `rejected` keeps the username reserved.

### Auth (`service/auth.py`)
- `create_user(..., must_change_password=False)` — writes the new column; state
  starts `active` (admin-created users are immediately usable, as today).
- `signup(con, username, password)` — no principal: creates role `reader`,
  `is_active=0`, `state='pending'`. Username taken (any state) → 409 `user_exists`.
  Audits `user.signup_requested`.
- `login(...)` response gains `must_change_password: bool`.
- `set_password(con, principal, new)` — rehashes, clears the flag, audits
  `user.password_changed`.
- `principal_for` carries `must_change_password` so `me` and the gate see it;
  `/auth/me` payload gains the flag.

### The gate (`api/deps.py`, one place)
`get_principal` — the single authentication choke every protected route uses —
raises 403 `password_change_required` when the principal has the flag set and the
request path is not `/api/v1/auth/refresh`, `/api/v1/auth/me` or
`/api/v1/auth/password`. No middleware, no per-route changes; `refresh`/`me` keep
working so the UI can learn the state and fix it.

### Admin decisions (`service/users.py`)
`patch` accepts `state`: `active` → `is_active=1, state='active'` (approve);
`rejected` → `is_active=0, state='rejected'`. Audits `user.approved` /
`user.rejected`. The last-admin guard is unchanged (approving can't break it).
`list_users` rows gain `state`; still never `pw_hash`.

### Routes (`api/routes/core.py`, `api/schemas.py`)
- `POST /auth/signup` — unauthenticated, 201, body `{username, password}`.
- `POST /auth/password` — authenticated, body `{password}`.
- `UserPatchIn` gains `state: str | None`.

### seed-operator (`api/__main__.py`)
`--username` defaults to `admin`. Password: `HARNESS_OPERATOR_PASSWORD` if set
(as today, no forced change); otherwise the account is seeded `admin`/`admin`
with the forced-change flag and the command says so loudly — the getpass prompt
goes away, which is the point of ask #8.

### UI
- **Login (`App.jsx`)**: `view` state `signin | signup | sent`. "Request an account →"
  under the card swaps to the signup form; submit → `POST /auth/signup` → the
  "Request sent. An administrator must approve it before you can sign in." card.
  409 shows in the existing field-error slot.
- **Forced change (`App.jsx`)**: when `/auth/me` reports `must_change_password`, the
  app renders a standalone Change-password card instead of the shell (no nav):
  new password + confirm → `POST /auth/password` → reload `me` → the shell appears.
  Pending/rejected users can't reach this (login blocks inactive accounts).
- **Users table (`Users.jsx`)**: State cell per mockup — `Pending` rows get
  Approve / Reject buttons (patch `{state}`); `Rejected` rows show plain text;
  an admin still owing a password change reads `Must set password`. Role select
  is hidden on pending rows (they are readers once approved; promote after).

### Read-only / firm-mode invariants untouched
`accept_m10.py` journeys (rita the reader, dispatch gating) don't touch signup;
`login` semantics for active users are unchanged.

## Testing

- pytest: signup → login 401 → approve → login 200 as reader; reject → 401 and
  username stays reserved (409 on re-signup); default seed → login ok with
  `must_change_password`, any other call 403 `password_change_required`, `/auth/me`
  works, `POST /auth/password` clears it; non-admin patch-state 403; pre-B database
  (old `users` table) gains the columns on open, existing rows `active`.
- vitest (renderToString only, no jsdom): signup/sent states of the Login card;
  ChangePassword card; UsersView pending row renders Approve/Reject.
- Full suites + `vite build` + a browser pass on the three screens
  (signup request, admin approve, forced change) before hand-off.
