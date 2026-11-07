# 07 — Case lifecycle data model (M5 addendum to 03)

**Date:** 2026-11-07 · **Status:** implemented in `harness-core` (build plan
`plans/2026-11-07-m5-platform-case-lifecycle.md`) · **Addendum to:**
[03-data-model.md](03-data-model.md) · **Spec:** NEXT_STEPS §3 (states §3.1, dossier §3.3,
safety rails §3.4) · **Prototype proven in:** `ironfleet-legal` v0.4 (unpublished),
`ironfleet-legal/mcp/dossier.py`, graded by `ironfleet-legal/tests/grade_dummy_case.py`.

## 0. What this adds and why

03 models the platform's execution machinery (Matter, WorkflowExecution, Task, Approval, AuditEvent).
What it does **not** yet model is the *case* itself: the loop that runs INTAKE → … → COURT →
DEBRIEF → RE-STRATEGY → … → CLOSED, whose state must survive restarts, whose deadlines fire
while nobody is looking, and whose every prediction is compared with what the court actually
did. The plugin prototype carried this as nine append-only JSONL registers in the matter
workspace. On the platform it becomes tables in the **same `platform.db`** (D4's store — one
connection factory, WAL already on, audit chain already append-only): the dossier is SQL, the
state machine is a row, and every transition lands in `audit_events` in the same transaction.

Ground rules carried over unchanged from the prototype and §3.4:

- **Mechanical stays mechanical.** Due dates come from the kernels
  (`module_e/vendored/court_calendar.court_filing_deadline`,
  `module_e/kernel_tools.statutory_demand`), never from a model or a caller-supplied `due`.
  `match` on a prediction is judgement, supplied as data, never computed.
- **Projections are computed at read, never stored.** "Latest" is always a query.
- **Validation at the boundary:** a bad entity, a non-serialisable event, an illegal state
  transition fails loudly at the write, never mid-transaction.

## 1. Entities

All tables live in `platform.db`, keyed by `matter_id` (the 03 §2.5 Matter PK; today the
matter ref string). Timestamps ISO-8601 text, as everywhere. `actor` is the writer (user id
or agent run id); every append also writes an `audit_events` row (03 §2.19) in the same
transaction.

### 1.1 cases — the §3.1 state machine's row

One row per matter, created lazily on first lifecycle write.

| field | meaning |
|---|---|
| `matter_id` PK | joins Matter |
| `state` | validated §3.1 state (see §2 below) |
| `lawyer_now` | 0/1 — the §3.4 "get a lawyer now" flag |
| `lawyer_now_reason` | JSON array of triggered rules |
| `needs_restrategy` | 0/1 — set by the deadline sentinel on a missed deadline (§3.4) |
| `created_at`, `updated_at` | |

### 1.2 case_events — CaseEvent (court events log + the dossier's append-only spine)

`event_id` PK (ordered, `ce-…`), `matter_id`, `event_type` (hearing/minute/judgment/
directions/…), `event_date` (YYYY-MM-DD, **required** — anchors the prediction diff and the
outcome log), `payload_json` (judge_said, orders, next_date, source_file — small; large
content by reference), `actor`, `ts`.

### 1.3 strategy_versions — StrategyVersion

`version` PK per matter (`matter_id`, `version`), `file`, `why_changed` (required non-empty —
a re-strategy must name what the court decided that the previous version got wrong),
`next_actions_json`, `actor`, `ts`. The chain is the versions ordered; `latest` = max(version).

### 1.4 proposals — Proposal

`proposal_id` PK, `matter_id`, `what`, `why`, `asked_at_ts`, `response` (pending/done/
refused), `responded_at_ts`, `actor`, `ts` — what we told the user to do, and whether they did.

### 1.5 predictions — Prediction + its Outcome register

`prediction_id` PK, `matter_id`, `strategy_version` FK, `claim`, `actor`, `ts`.
`outcomes`(`outcome_id` PK, `prediction_id` UNIQUE, `match` 0/1 — supplied as data,
`actual`, `court_date`, `actor`, `ts`). A prediction with no outcomes row is *unresolved* —
computed at read, never stored.

### 1.6 deadlines — Deadline (the sentinel's register)

`deadline_id` PK, `matter_id`, `what`, `due` (kernel-computed only; a caller-supplied `due`
is refused at the API), `rule` (the kernel call that produced it), `source` (always
`"kernel"`), `service_date`, `kind` (filing/statutory_demand), `status` (open/due_soon/
overdue/met — open→due_soon at ≤7 days is computed at read; **open→overdue when `due` < today
is a write the sentinel makes**, and that write also sets `cases.needs_restrategy=1`),
`missed_consequence`, `actor`, `ts`. Reminder ladder: computed rungs at T-14/T-7/T-3/T-1 —
data the sentinel returns, never a scheduled job (durability comes from the row, not a timer).

### 1.7 flaws — Flaw (the moot-gate ledger, register #9)

`flaw_id`, `matter_id`, `class`, `severity` (critical/material/minor), `doc`, `status`
(open/fixed/dismissed), `detector`, `detail`, `actor`, `ts` — append-only events,
**last status per `flaw_id` wins** at read; `gate_blocked` = any open critical/material.

### 1.8 facts / evidence — the dossier's first two registers

`facts`(`matter_id`, `field`, `value_json`, `actor`, `ts`, op=set) — latest value per field at
read. `evidence`(`evidence_id` PK, `matter_id`, `op` (add/remove), `label`, `file`,
`sha256`, `actor`, `ts`) — exhibit register; the 03 §2.8 Evidence row remains the citable-unit
layer above it.

## 2. The §3.1 state machine

`STATES` (NEXT_STEPS §3.1, verbatim): `INTAKE, ASSESS, STRATEGY, PRE_ACTION, DRAFT, MOOT,
APPROVE, FILE_SERVE, AWAIT, RESPOND, HEARING_PREP, COURT, DEBRIEF, RE_STRATEGY, JUDGMENT,
ENFORCE, APPEAL, SETTLE, CLOSED`.

`TRANSITIONS`: the §3.1 chain order, plus settlement/discontinuance (`SETTLE`) allowed from
any state at or after `PRE_ACTION`, and `CLOSED` from `JUDGMENT`/`ENFORCE`/`APPEAL`/`SETTLE`.
`lifecycle.statemachine.transition()` refuses any jump not in the map (loud error, no write),
updates `cases.state`, and writes the audit event in one transaction. `COURT` is entered by
the operator ("I attended"); `DEBRIEF` is entered by `debrief.ingest_court_event`;
`RE_STRATEGY` by the same (it is where the loop turns); `restrategy.cut_strategy` requires the
case be in `RE_STRATEGY` (or `AWAIT`/`RESPOND` for an out-of-court re-plan).

## 3. Service-layer API (what M7's REST endpoints will wrap)

`harness/lifecycle/`: `dossier.append/read` (entity enum = the registers above, projections at
read exactly as the plugin), `statemachine.transition/state`, `debrief.ingest_court_event` +
`record_outcome`, `restrategy.cut_strategy`, `deadlines.register` (kernel-only) +
`deadlines.sentinel`, `lawyer_now.evaluate`. All take the open `platform.db` connection; all
mechanical and local, no network, no model.

## 4. Deliberately not modeled here

- Corpus CRUD on the platform (R-CL2 harness side) — tracked in §8, separate step.
- The web/API surfaces — M7. The lifecycle functions above are the service layer M7 wraps.
- The M6 moot-gate platform stage — `flaws` lands here; the gate workflow itself is M6.
- Scheduled reminder *jobs*: the ladder is computed data; whoever wakes the platform (M7's
  SSE or a CLI poll) calls `deadlines.sentinel` and gets the rungs.
