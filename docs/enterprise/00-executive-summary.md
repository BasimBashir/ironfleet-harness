# 00 — Final Audit Report (Executive Summary)

**Date:** 2026-11-04 · **Deliverable set:** this summary + [01-repository-audit](01-repository-audit.md) · [02-target-architecture](02-target-architecture.md) · [03-data-model](03-data-model.md) · [04-api-and-events](04-api-and-events.md) · [05-product-and-ux-specification](05-product-and-ux-specification.md) · [06-migration-roadmap](06-migration-roadmap.md). Evidence: `path:line` citations live in 01; this page draws conclusions only.

## A. Current state

IronFleet today is a **single-operator, local-first legal agent harness**, not yet an operating system. It drives pinned opencode subprocesses through a loopback egress proxy into one governed dispatch point (EgressGate), runs a 9-stage legal pipeline sequentially, and serves one operator through a Textual TUI. Suite: **819 passed, 0 failed** (executed 2026-11-04). (01 §1–§2)

## B. Existing strengths (preserve)

EgressGate + routing policy (refusal-traced, fail-closed), TurnScheduler as a model-call admission controller, per-agent workspaces with env scrubbing, the hybrid legal RAG engines (FTS5 + sqlite-vec + citation join + rerank + deterministic quote verification), personas/skills/kernels as data, the eval harness and recorded benches, and a genuinely green 819-test suite. (01 §11.6 KEEP list)

## C. Critical gaps

1. **No durable execution** — in-process scheduler, no resume/recovery, orphan state on crash, workflows cannot wait for humans. 2. **No API** — surfaces are in-process SQLite reads; principle 9 unmet. 3. **No human approval mechanism.** 4. **Two model-reachable confidentiality holes** (corpus matter-arg override; builtin bash/webfetch not universally denied). 5. **RAG below the ratified bar** — 0/30 golden cases pass; 42/56 present needles unsupplied. 6. Production logic in `scripts/`/`spike/` and ~300 lines of backend trapped in the TUI.

## D. Architectural risks

Ranked: cross-matter read via tool arg (S1); unguarded tool egress (S2); non-durable execution; failure-continue pipelines drafting on missing research; no authn/authz; RAG quality; no approval gate; no API; opencode binary dependency (known hang class, watchdog-mitigated). (01 §13)

## E. Target architecture

One host, one Python service: API (REST + SSE) → application services → new SQLite-lease durable orchestrator → the preserved IronFleet core (gate/scheduler/providers/crew/RAG). `platform.db` carries the matter/workflow/approval/audit entities; existing stores keep their roles. Full shape: 02; entities: 03; contracts: 04; screens: 05.

## F. Component disposition

**No REPLACE.** KEEP: 20 components (gate, policy, capacity, providers, keychain, workspace, session read models, crew/tooling, vectors, quote_check, eval, CLI, ops, prechecks…). EXTEND: 12 (proxy, scheduler, bootstrap, trace, driver, factory, store, spawn_tool, personas, guard, corpus, ingest). RETIRE: TUI + launcher (gated on extraction + owner parity sign-off), statute_ingest shim, acceptance drivers (deferred), root trace DBs. INVESTIGATE: supervisor routes, agent-memory scoping, spike/persona_port. (01 §11.6)

## G. Migration strategy

Ten phases, security first, durable execution before any frontend, eval-gated RAG last-but-one; full detail with per-phase rollback in 06. Headline sequencing change vs the brief's sketch: Stage 9 (security) executes first because two of its findings are exploitable by the agents themselves today.

## H. Decisions required (owner)

1. Approve roadmap + ordering (06 §1.1). 2. Deny-by-default personas + guard block defaults (Phase 1). 3. Legal-pipeline halt-on-failure policy (02 §16.7). 4. SQLite-lease orchestrator over an external engine (02 §16.1). 5. Agent-memory scoping ruling (02 §16.6). 6. FastAPI dependency + frontend stack choice (04 §2, 02 §16.3). 7. UI mockup sign-off before any screen; TUI retirement at parity (05 §14). 8. Golden-case/retrieval acceptance thresholds before Phase 8.

## I. Implementation readiness

| Subsystem | Readiness |
|---|---|
| Gate / policy / providers / capacity | **Ready to extend** (Phase 1 touches config seams only) |
| Session driver / workspace / store | **Ready to extend** |
| Factory → orchestrator | **Requires architectural change** (Phase 3, flag-gated) |
| Corpus / ingest / vectors | **Ready to extend** (Phase 1 + Phase 8) |
| Guard | **Requires relocation + policy work** (Phase 1) |
| API / web workspace | **Blocked by missing infrastructure** (Phases 3–5 precede) |
| Agent memory | **Requires owner decision** |
| Supervisor routes | **Requires additional research** (retire-or-repurpose) |
| TUI | **Not suitable for further investment**; retire per 06 Phase 6 gate |
