# 06 — Migration & Implementation Roadmap (proposed)

**Date:** 2026-11-04 · **Status:** plan awaiting owner approval — nothing here is authorized to execute (brief §18) · **Companions:** [01](01-repository-audit.md) · [02](02-target-architecture.md) · [03](03-data-model.md) · [04](04-api-and-events.md) · [05](05-product-and-ux-specification.md).

## 0. Ordering, and why it differs from the brief's §15 sketch

The brief anticipated reordering ("security and durable execution may need to precede the frontend"). Audit findings make it mandatory:

- **Security precedes everything** (brief §15 Stage 9 → here Phase 1): two model-reachable confidentiality holes (S1, S2) cannot be left open while we build *more* ways to run agents. Every later phase piles more turns onto the same holes.
- **Durable execution precedes the frontend** (Stage 3 → Phase 3): the Matter Board's defining states (`Waiting on you`, Running, Blocked) are database facts produced by the orchestrator. Building screens against today's write-only `jobs` table would be screens over nothing (01 §5).
- **API before frontend, frontend before swarm/chat polish** (Stages 5–7 kept in order): principle 9.
- **RAG hardening last-but-one, not last** (Stage 8 → Phase 8): the golden-case bar (0/30 pass today, 01 §7) is unaffected by everything before it; doing it earlier would just re-baseline the numbers after each migration. It is eval-gated work with its own tempo.

**Cross-phase invariants (every phase):** full pytest suite green before merge; golden-case bench re-run whenever persona/prompt/RAG behaviour changes; no destructive migrations (additive ALTER pattern, 01 §11.2); every phase ends with the system usable by the operator exactly as before, plus the new capability. **Nothing is deleted until its replacement has carried its load for a full phase** (principle 10).

---

## Phase 1 — Security hardening

- **Objective:** close S1, S2, S3, S4, S9 (01 §6.3) before any new surface exists.
- **Scope:** corpus tool matter binding; builtin-tool denial; proxy matter binding; guard authority/log placement; env URL validation.
- **Components:** `corpus.py:552`, `module_e/personas.py` + `data/module-e/personas.yaml`, `scripts/stand_up_opencode.py:229-232, 279-282`, guard logic (`spike/guard_port.py`, `guard_cli.py`, TS plugin), `bootstrap.py:129-134`.
- **Dependencies:** none. This is the first commit.
- **Technical approach:**
  1. Remove the `matter` tool argument; the tool reads only its workspace binding (S1).
  2. Invert persona tool policy to deny-by-default for `bash`/`webfetch`/`websearch`/`edit`; explicit allow-list per persona; regenerate all persona files (S2).
  3. Per-run token: workspace sync mints a token bound to the matter; the proxy resolves matter from the token and ignores client-supplied matter/headers when a token is present (S3). Tokens rotate per sync; unauthenticated fallback removed once all mounts re-sync.
  4. Guard: relocate logic out of `spike/` into `module_e/` (behaviour-preserving move); authority file + guard log move to harness-owned paths outside the workspace; log becomes append-only; `block` defaults on for verify/filings stages, matter-policy configurable (S4).
  5. Validate `IRONFLEET_*_URL` overrides against a scheme/host allow-list (S9).
- **Testing:** new adversarial tests (tool-arg override must fail; persona without explicit grant must deny builtins; token-less requests rejected; guard log survives sync; malformed override refused). Full suite. **Golden-case re-run required** (persona behaviour changes).
- **Acceptance:** the audit's reproduction steps for S1/S2/S3 fail to reproduce; guard log preserves entries across re-syncs; suite green.
- **Rollback:** five small independent commits; revert any one without the others. Mounts re-sync on next run.
- **Risks:** persona behaviour change alters golden-case scores (accepted — that is the point; re-baseline and record). S1 fix breaks any caller passing `matter=` explicitly — callers are audited in-phase (bench scripts use the parameter path, so they migrate to explicit bindings).
- **Complexity:** **M** (~1–2 weeks equivalent).

## Phase 2 — Substrate relocation & application-service extraction

- **Objective:** production code out of `scripts/`/`spike/`; UI-trapped logic into callable services; store hygiene. Unblocks packaging (01 §12.1, §12.2).
- **Components:** `stand_up_opencode.py`, `run_spike_opencode.py` → `src/harness/` (re-export shims keep `scripts/` imports working during the phase); TUI's ~300 lines (01 §8 list) → `harness/service/` use-cases (ingest, doctor, persona, provider, dispatch-with-compact, session digest); `session/store.py` WAL + `busy_timeout` + orphan-`running` reconciliation; `TurnScheduler` `run_timeout` wired (`bootstrap.py:100`, `egress_proxy.py:303`); `statute_ingest.py` shim retired after tests re-point; dead `factory.py:29` import removed.
- **Dependencies:** Phase 1 (guard already relocated there; this phase moves the rest).
- **Testing:** suite stays green with import shims; shims removed when no importer remains (grep-gated). New: WAL-under-concurrency test, reconciliation test (crash → orphan closed), `run_timeout` test.
- **Acceptance:** `pip install` non-editable works and `harness serve/drive/session` run from the installed tree; TUI behaviour unchanged.
- **Rollback:** pure moves + additive store changes; git revert per commit.
- **Risks:** import cycles during the move (mitigate: move modules whole, no splitting); missed importer (grep + suite catch).
- **Complexity:** **M**.

## Phase 3 — Durable execution platform

- **Objective:** the critical gap (01 §13 row 3): runs survive restarts, park for humans, resume, and are idempotent. Implements 02 §6–§7.
- **Components (new):** `platform.db` (workflow tables only in this phase: workflows, workflow_executions, tasks, checkpoints, workflow_events + Matter row minimal read-path), `harness/workflow/` (orchestrator, lease manager, recovery, compiler). **Components (extended):** `factory.py` (`run_task` loop becomes plan-compiler + orchestrator hand-off; `_run_stage` kept as the task body), `driver.py` (kill-on-abandon seam; AgentRun transitions), `session/store.py` (AgentRun writes).
- **Dependencies:** Phase 2 (services + store hygiene).
- **Technical approach:** per 02 §7 — SQLite lease design; in-transaction event writes; startup reconciliation; completed tasks never re-executed; artifact copy becomes content-addressed (fixes the stale-copy hazard, 01 §3.1). The legal pipeline ships as the first Workflow row. Failure policy default changes to halt-and-block for legal workflows (**owner decision, 02 §16.7**). Legacy path: a flag routes dispatch through the orchestrator; one release with the flag defaulting on after a soak period.
- **Testing:** new suite — lease expiry/recovery (kill a worker mid-task), resume-from-checkpoint, idempotent re-run (same artifacts, no dupes), cancellation tree-kills (the new seam), failure-policy halt; concurrency: two dispatches, one matter, correct serialization. Full suite; one live acceptance run (opencode + providers) before flag-default-on.
- **Acceptance:** kill -9 the service mid-pipeline → restart → execution resumes at the correct task, no orphan `running` rows, board-consistent state; a 9-stage run survives a forced restart twice.
- **Rollback:** flag returns dispatch to legacy `run_task` (kept alive this entire phase); `platform.db` additive; store-root backup before upgrade.
- **Risks:** the orchestrator is the largest new component — contained by the flag and by reusing the proven `_run_stage`; lease semantics subtlety (clock: use monotonic service time + DB timestamps, never wall-clock deltas across machines — single host makes this simple).
- **Complexity:** **L** (~3–4 weeks equivalent). Highest-value phase in the plan.

## Phase 4 — Governance: approvals, matter state, audit chain

- **Objective:** human-supervised autonomy becomes a mechanism, not an aspiration (S8, brief §9). Implements 02 §4/§12 rows 7–8.
- **Components:** `platform.db` approvals + audit_events + full Matter state machine; `harness/service/approvals.py`, `audit.py`; orchestrator wait-states (`waiting_human`) consume them; matter classification moves from TUI hardcode (S6) to Matter rows; agent-memory canon content guard (S5 interim measure pending the scoping ruling).
- **Dependencies:** Phase 3 (wait-states need the orchestrator).
- **Testing:** approval parks execution → decision resumes it (both approve and reject paths); audit chain verifies (tamper an row → verification fails); state-machine transition table test (every illegal transition rejected); classification reaches dispatch from the Matter row.
- **Acceptance:** a filings-stage run parks on an approval, the operator decides in the CLI (web arrives Phase 5/6), execution resumes; audit chain intact under a deliberate tamper test.
- **Rollback:** additive tables; wait-state feature per-workflow (legal pipeline enables it; others skip); revert-safe.
- **Risks:** low — the mechanics are simple; the design choices (who may approve what) are policy data, adjustable without code.
- **Complexity:** **M**.

## Phase 5 — API service

- **Objective:** principle 9 satisfied: everything a frontend needs over HTTP (01 §9 gap closed). Implements 04 in full.
- **Components (new):** `harness/api/` (FastAPI+uvicorn — **new dependency, owner sign-off required**, 04 §2), authn (users/tokens; single operator seeded), SSE hub; service layer extended to expose the use-cases idempotently.
- **Dependencies:** Phases 3–4 (it serves their state).
- **Technical approach:** one process, second listener; OpenAPI schema generated from the pydantic contract (house style, 04 §2); `Idempotency-Key` on mutations; SSE from `workflow_events`.
- **Testing:** contract tests per endpoint (authz matrix: every endpoint × no-permission/reader/editor/admin); SSE replay test (`Last-Event-ID`); idempotency replay test; full suite untouched.
- **Acceptance:** the acceptance checklist runs a whole pipeline — create matter → dispatch → observe via SSE → approve mid-run → collect artifacts — with zero direct DB access; authz matrix passes.
- **Rollback:** API is additive; disable the listener, nothing else changes.
- **Risks:** new dependency (supply-chain precheck pattern exists — run `security/` checks on it); auth subtleties (keep to opaque tokens + deny-by-default middleware; no hand-rolled crypto).
- **Complexity:** **M–L**.

## Phase 6 — Enterprise workspace (Matter Board, Workspace, Approvals, Documents, Activity, Audit)

- **Objective:** the new primary interface (brief Stage 5), replacing the TUI for daily operation.
- **Components (new):** web client per 05 (stack per owner decision, 02 §16.3). **Components (retired at phase end):** `session/tui.py` + `scripts/tui.py`, after parity sign-off; `accept_r3`'s TUI imports rehomed to the service layer (01 §11.5).
- **Dependencies:** Phase 5 (API), and **the 05 §14 design sign-off gate** — mockups before code, per the owner's standing instruction.
- **Scope of screens (v1):** Board, Workspace tabs (Overview/Documents/Evidence/Work Plan/Agents/Decisions/Activity/Audit), Approval Center, run inspection drawer. **Not** in this phase: swarm graph, counsel chat (Phase 7) — the Work Plan tab covers their function meanwhile.
- **Testing:** component tests for state rendering (all nine matter states, ten agent states, permission matrix §12); E2E: the Phase 5 acceptance script driven through the browser; visual QA against the approved mockups.
- **Acceptance:** the operator completes a full matter lifecycle (create → ingest → dispatch → approve → collect → complete → archive) in the browser alone; TUI deleted only after the owner confirms parity on real work (**explicit owner gate, 02 §16.8**).
- **Rollback:** the web client is served read-side; the CLI remains fully functional throughout; TUI deletion is its own commit, reversible by revert (its logic already lives in services since Phase 2).
- **Risks:** scope creep on screens — mitigated by 05 §15's explicit out-of-scope list; frontend stack learning curve (owner picks per 05 §14).
- **Complexity:** **L**.

## Phase 7 — Swarm visualization & counsel chat

- **Objective:** the two signature experiences (brief Stages 6–7) on stable ground.
- **Components:** swarm graph (AgentRun tree from `parent_run_id` + `depends_on`, live via SSE); counsel chat (04 §5.8) with durable interjections (`runs/{rid}/interject` replacing in-memory `inject()`, 01 §3.1).
- **Dependencies:** Phase 6 (design system, routing, SSE client already built).
- **Testing:** graph correctness against seeded execution shapes (linear, parallel-3, deep delegation); interjection delivery semantics (queued → drained → shown durable); E2E: instruct lead counsel in chat → watch execution → approve inline.
- **Acceptance:** the brief §3.2 inspection list fully reachable from the graph; a chat instruction produces an inspectable run with evidence chips; nothing in the thread ever implies success before the backend confirms (05 §10 rule).
- **Rollback:** additive screens; Work Plan tab remains the fallback view.
- **Risks:** graph rendering complexity on large executions (mitigate: collapse-completed default, virtualize >200 nodes).
- **Complexity:** **M–L**.

## Phase 8 — Legal intelligence hardening

- **Objective:** move RAG from "measured, not production-ready" (01 §7) toward the ratified bar, eval-gated.
- **Components:** `corpus.py` (metadata/jurisdiction/doc-type columns + filters; expansion model to config; rerank fallback becomes observable event; embedding-model check at search), `ingest_generic.py` (persist licence/source_url/retrieved; version rows not replace), `vectors.py` (model check), evidence records per 03 §2.8; retrieval-gap work aimed at the measured failure classes (PRESENT_NOT_RETRIEVED 29, BELOW_POOL 9, LOST_AT_RERANK 5 of 69 needles — 01 §7).
- **Dependencies:** none technically (could run earlier in parallel by a second workstream), but deliberately sequenced after the platform phases so numbers are measured against the final shape once.
- **Technical approach:** every change lands with its bench (`bench_r1_*`) re-run and recorded under `data/eval/`; acceptance bar = the ratified retrieval bar (42/56 present needles supplied — 01 §7) and golden-case pass rate targets set by the owner before work starts.
- **Testing:** the benches are the tests; suite green; quote-verification path unchanged in semantics (deterministic).
- **Acceptance:** owner-set thresholds met or the gap quantified with a diagnosis (the honest outcome if retrieval ceilings are hit); no silent quality regression (benches are the gate).
- **Rollback:** schema additions are additive; bench records make any regression visible immediately.
- **Risks:** retrieval ceiling may be ingestion-quality-bound, not algorithm-bound (the ABSENT-13 class is a corpus supply problem — 01 §7); that becomes an operator/content action, not code.
- **Complexity:** **L** (open-ended research character).

## Phase 9 — Multi-user completion & observability polish

- **Objective:** the enterprise posture the brief names (§16): RBAC beyond the seeded roles, ethical walls in enforcement (not just data), retention policy, health surfaces.
- **Components:** role/permission matrix completion in the service layer; ethical-wall checks on matter membership; retention job for events/audit; `/healthz` enrichment; provider latency dashboards from trace.db.
- **Dependencies:** Phases 4–6.
- **Testing:** authz matrix extension; wall-enforcement tests (two matters, disjoint teams, no leak via any endpoint); retention test.
- **Acceptance:** a second user with a narrow role can do their job and nothing else; audit chain unchanged.
- **Rollback:** additive.
- **Risks:** low; policy-heavy rather than mechanism-heavy.
- **Complexity:** **M**.

## Phase 10 — Reliability & deployment validation

- **Objective:** operational readiness (brief Stage 10): installable, supervised, backed-up, recovery-drilled.
- **Components:** `packaging/` non-editable builds (Windows installer + macOS .app with pinned opencode), service supervision (Windows service/launchd), backup/restore runbook extension (`p07` pattern + `platform.db`), recovery drills.
- **Dependencies:** all prior.
- **Testing:** fresh-OS install matrices (the repo's own FRESH-OS-SETUP frictions, 01 §2 — now exercised by script); kill/restart drills at every lifecycle point (mid-stage, mid-approval, mid-ingest); upgrade drill on a copied store root.
- **Acceptance:** from bare machine to completed matter in one documented run; drills pass with zero manual repair.
- **Rollback:** installer versioning; store-root backup/restore.
- **Risks:** platform quirks (the known opencode startup-hang class stays watchdog-mitigated, 01 §13).
- **Complexity:** **M**.

---

## 1. Decisions the owner must make before/during execution

Consolidated from 02 §16 (numbering here = execution order):

1. **Now, before Phase 1:** approve this roadmap and its ordering.
2. **Phase 1:** confirm deny-by-default persona policy and guard `block` defaults for verify/filings.
3. **Phase 2–3:** confirm the legal-pipeline **halt-on-failure** policy change (02 §16.7).
4. **Phase 3:** approve SQLite-lease durable execution over an external workflow engine (02 §16.1).
5. **Phase 4:** rule on **agent-memory scoping** (02 §16.6).
6. **Phase 5:** approve the **FastAPI dependency** (04 §2) and the **frontend stack** (02 §16.3).
7. **Phase 6:** approve mockups before any screen (05 §14); confirm **TUI retirement** at parity (02 §16.8).
8. **Phase 8:** set the golden-case and retrieval acceptance thresholds.

## 2. Effort summary

| Phase | Focus | Complexity |
|---|---|---|
| 1 | Security hardening | M |
| 2 | Substrate relocation + service extraction | M |
| 3 | Durable execution platform | **L** |
| 4 | Approvals, matter state, audit | M |
| 5 | API service | M–L |
| 6 | Enterprise workspace | **L** |
| 7 | Swarm + counsel chat | M–L |
| 8 | Legal intelligence | L (open-ended) |
| 9 | Multi-user + observability | M |
| 10 | Reliability & deployment | M |

Sequence end-state: every audit finding S1–S9 closed or owned by a policy row; durable multi-day execution real; API-first surfaces; the TUI's knowledge preserved in services; RAG quality measured against explicit bars. Nothing rewritten that worked — gate, scheduler, providers, workspaces, RAG engines, and the crew all carry forward (01 §11.6).
