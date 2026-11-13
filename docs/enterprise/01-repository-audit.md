# 01 — Repository Audit: harness-core

**Date:** 2026-11-04 · **Scope:** `harness-core/` (the sibling `ironfleet-legal/` plugin is out of scope) · **Mode:** read-only, per `new-plan-for-harness.md` §12/§18.

## 0. How to read this document

- Every claim cites `path:line` in the current tree. Where a docstring or comment claims something the code does not do, the claim is marked **[docstring claim]** and the contradiction is stated.
- "Tested" means a test file exists that exercises the behaviour. The full suite **was executed** during this audit: **819 passed, 0 failed** (`pytest`, project venv, ~60 s). One known noisy warning: a reader-thread `TypeError` from a lambda under `tests/test_env_scrub.py` (originates in `scripts/run_spike_opencode.py:191`); it is a warning, not a failure.
- Live acceptance (real opencode, real Ollama/cloud providers) was **not** re-run for this audit. Numbers quoted from `data/eval/**` are recorded results, not re-measurements.
- Classification vocabulary is §13's: KEEP / EXTEND / REPLACE / RETIRE / INVESTIGATE.

---

## 1. What IronFleet is today (one paragraph)

harness-core is a **single-machine, single-operator, local-first legal agent harness** written in Python 3.12. It drives the third-party **opencode** CLI as its agent runtime: each agent turn is one `opencode run` subprocess in an isolated per-agent workspace. Every model call those subprocesses make is pinned to a **loopback OpenAI-shaped egress proxy** (`127.0.0.1:7373`) that funnels into one **EgressGate** which classifies (LOCAL_ONLY / LOCAL_PREFERRED / CLOUD_PERMITTED), routes, verifies provider provenance, and traces every dispatch to SQLite. A **factory** turns a user's task into a **9-stage sequential legal pipeline** (intake → research → strategy → attack → assess → filings → advice → verify → close). A **matter-scoped hybrid RAG** (FTS5 + sqlite-vec + citation-join, RRF, local rerank) feeds agents through a gated tool, and a **guard plugin** annotates fabricated quotes and unconfirmed citations. The operator surface is a Textual TUI plus a `harness` CLI. There is **no** multi-user model, **no** client-facing API, **no** durable workflow engine, and **no** human-approval mechanism.

---

## 2. Repository structure

| Area | Contents | Role |
|---|---|---|
| `src/harness/` (~5,680 L) | gate, egress proxy, scheduler, capacity, bootstrap, policy, alias, paths, keychain, trace, corpus, vectors, ingest_generic, quote_check, agent_memory, cli | Production core |
| `src/harness/session/` | store, driver, factory, workspace, errors, tokens, view, commands, tui | Session/execution layer + TUI |
| `src/harness/module_e/` | dispatch, guard, personas, skills, tools, kernel_tools, spawn_tool, supervisor, refine, `vendored/` | Ported legal-agent crew + legal kernels |
| `src/harness/providers/` | config, http_fetch, probe, provenance, retry | Provider registry + transports |
| `src/harness/eval/` | golden_case, runner, scorers, substitute | Evaluation harness |
| `src/harness/security/` | dsh_precheck, opencode_precheck | Supply-chain prechecks |
| `src/harness/spike/` | guard_port, guard_cli, persona_port, `candidates/opencode/` (TS guard plugin) | Historical spike — **but `guard_port` is on the production path** |
| `src/harness/ops/`, `packaging/` | ironfleet_launcher, install/verify scripts, macdist | Deployment |
| `scripts/` | tui launcher, session_cli, stand_up_opencode, run_spike_opencode, ingest drivers, 9 `accept_*` drivers, `bench_r1_*`, eval/reporting | Thin drivers — **two of them (`stand_up_opencode`, `run_spike_opencode`) are imported by `src/` and are production substrate** |
| `data/` | `module-e/` (personas.yaml, tools.yaml, legal_pipeline.yaml, skills), routing*.yaml, providers.yaml, opencode-a1/ (mount template), golden_cases/ (33), eval/ (recorded results), corpus/ | Production config + data |
| `tests/` | 78 files, pytest + pytest-asyncio | Unit + stubbed acceptance |
| repo root | 7 `*.sqlite3` trace DBs (accept_r1_trace, corpus_ingest_trace 6.0 MB, dbg_trace, expand_probe_trace, failure_report_trace, probe_trace, statute_ingest_trace), `pytest-output.txt`, decision docs | One-off run artifacts + records |

**Entry points.** One console script: `harness = "harness.cli:main"` (`pyproject.toml:12`). Subcommands `serve` (egress proxy via `ops/ironfleet_launcher.py`, port 7373), `drive` (`scripts/stand_up_opencode.main`), `vectors count|list|delete`, `corpus drop`, `providers list|set-key`, `session --new|--list|--resume|--turn|--errors` (`cli.py:29-172`). The TUI is **not** a console script: `python scripts/tui.py` (`scripts/tui.py:11-13`).

**Packaging.** Editable install only — "the distribution tree IS the repo tree" (`cli.py:2-4`); packaged data is resolved relative to `cli.py` (`cli.py:17-25`), so a non-editable wheel deliberately fails. macOS `.app` manifest with pinned opencode (`packaging/macdist.py`), Windows install (`ops/install_windows.ps1`, `scripts/pack_windows.py`), Linux setup scripts only.

**Dependencies** (`pyproject.toml:7`): pydantic≥2.6, httpx≥0.27, keyring≥24, pyyaml≥6, pypdf≥6, markitdown≥0.1, sqlite-vec==0.1.9, textual≥3.0. Every dependency has an importer; none unused. **No web framework** (no FastAPI/Starlette/aiohttp/Flask/websockets) anywhere in `src/`.

---

## 3. Agent architecture (as built)

### 3.1 Execution lifecycle

```
user task ──► FactoryRunner.plan()             factory.py:203-213
              ├─ parse ```plan block           factory.py:59-82   (shell-drives/hybrid)
              └─ fallback_plan → legal_plan    factory.py:116-122, 99-113  (9 stages, legal_pipeline.yaml)
          ──► run_task: sequential for-loop    factory.py:243-267
              per stage:
                jobs row "running"             factory.py:245-247
                _run_stage                     factory.py:269-316
                  workspace_for(<agent>-stage-<stage>)          :283
                  write stage agent .md AFTER sync              :284-286
                  copy prior *.md as from-<agent>--<file>       :292-298
                  driver.run_turn(model=STAGE_MODEL)            :302-304
                    └─ spawn_session → `opencode run`           workspace.py:110-134
                         └─ every model call → 127.0.0.1:7373 → TurnScheduler → EgressGate
                  drain in-memory interjections                 :309-315
                jobs row "done" | "failed" (run continues)      factory.py:252-265
```

- **Plan source.** A fenced ```` ```plan ```` block of `stage|agent|instruction` lines (`factory.py:59-82`); otherwise **always** the legal pipeline (`factory.py:116-122`). `intent`/`complexity` are accepted and ignored — this implements the owner's 2026-10-21 ruling "one prompt → the full pipeline" (docstring `factory.py:117-121`).
- **Pipeline as data.** `data/module-e/legal_pipeline.yaml` — intake/ingestor, research/hunter, strategy/strategist, attack/adversary, assess/evaluator, filings/clerk, advice/clerk, verify/citation, close/auditor. Loaded fail-loud (`factory.py:85-96`).
- **Model selection.** The harness names a *task class*, not a model: `STAGE_MODEL = "gate-local/gate/drafting"` (`factory.py:46`), passed both in the stage md and as `--model` because the flag overrides frontmatter (`factory.py:42-45`). The gate's routing table chooses the provider.
- **Stage tool set.** `stage_agent_md` writes an exhaustive true/false map over `_STAGE_TOOLS` (`factory.py:38-40, 125-136`); the default enables only `read`, `write`, `ironfleet_corpus_search` (`factory.py:130-134`). **Factory stages therefore run with bash/webfetch disabled.** (Persona files outside the factory are a different story — §6.)
- **Handoff.** Previous stage summary in the prompt (`factory.py:160-174`) + file copies. Copy is guarded by `if not dest.exists()` (`factory.py:297`): **a re-run never refreshes an updated upstream artifact** — staleness hazard.
- **Failure policy.** A failed stage is recorded (`record_error` → `errors.jsonl`) and the **run continues** (`factory.py:252-261`). Downstream stages run on missing inputs.
- **Interjection.** `inject()` appends to an in-memory dict (`factory.py:199, 217-221`), drained after the stage's turn (`factory.py:309-315`). Lost on process exit.
- **Delegation.** `spawn_agent` tool (`module_e/spawn_tool.py:28-61`) runs a child turn in a sibling workspace **synchronously inside the parent's tool call**; no jobs row, no JSONL row, no scheduler handle — invisible to the session ledger.
- **Modes.** The docstring advertises three orchestration modes (`factory.py:4-9`) **[docstring claim]**; in code `mode` only toggles whether `parse_plan` is attempted (`factory.py:209-213`). There is no separate agent-os execution path.
- **Supervisor routes are dead on the run path.** `load_routes` is imported (`factory.py:29`) but never called by `fallback_plan`.

### 3.2 Turn engine

- `SessionDriver.run_turn` (`driver.py:110-174`): scrubbed env, trace-id snapshot, `asyncio.wait_for(asyncio.to_thread(spawn_session…), TURN_TIMEOUT_S=660)` (`driver.py:55, 142-144`). Any failure is recorded and an empty row lands — the shell never crashes.
- On outer timeout the spawn thread is **abandoned** (`driver.py:51`); the opencode process lives until the inner 480 s watchdog (`workspace.py:29`) tree-kills it (`taskkill /T /F`, `run_spike_opencode.py`). Cancellation never proactively kills the subprocess from the driver side.
- `spawn_session` retries **once** on exit 124 with zero events (startup-hang signature) (`workspace.py:128-132`). A hang after partial output is not retried.
- opencode session id is persisted for resume (`store.py:105`); `driver.resume` (`driver.py:176`).

### 3.3 Capability matrix vs brief §6

| Capability | Status | Evidence |
|---|---|---|
| Concurrent matters | **Yes, at model-call layer** | per-matter lock + global semaphore, `scheduler.py:73-75, 90` |
| Multiple agents within a matter | Sequential only | `factory.py:243` for-loop |
| Parallel execution within a matter | **No** — and the per-matter lock would serialize model calls even if stages ran in parallel | `scheduler.py:73-75` |
| Per-matter isolation | Partial (see §6) | |
| Task-level scheduling | No — scheduler admits *model calls*, not tasks | `egress_proxy.py:303` |
| Cancellation | Partial — scheduler handles yes (`scheduler.py:204-224`); driver abandons, does not kill | `driver.py:51` |
| Checkpointing | No stage checkpoint; only conversation `/compact` rows | `tokens.py` compact |
| Recovery after restart | **No** for runs | no reconciliation code |
| Retry/timeout | Turn: 480 s + 660 s + one retry; queue: 600 s; **running model call: unbounded** | `bootstrap.py:100`, `egress_proxy.py:303` build without `run_timeout` |
| Durable event history | Partial — trace rows + TurnRows + jobs rows; raw event stream not kept | |
| Idempotent execution | **No** | jobs append, TurnRows append, stale copies |
| Worker supervision | Watchdog per subprocess only | `workspace.py:29` |

---

## 4. Scheduler architecture

- **Location and process.** `TurnScheduler` lives **inside the egress proxy process** (`egress_proxy.py:303`; also `bootstrap.py:100`). The factory/TUI/CLI never touch it; they reach it only because every opencode model call is an HTTP request to the proxy. **It schedules model calls, not stages, tasks or workflows.**
- **Mechanism.** Per-matter `_MatterQueue` = `asyncio.Lock` + `deque` of waiting handles (`scheduler.py:73-75`); global `asyncio.Semaphore(max_concurrent)` (`scheduler.py:90`). Acquire order matter-lock → semaphore, both under `asyncio.timeout(queue_timeout)` (`scheduler.py:142`); semaphore released before the matter lock so one matter cannot monopolise the cap (`scheduler.py:~195-201`).
- **Cap.** `Capacity.max_concurrent = min(perf_cores//2, avail_mb//20480)`, floor 1 (`capacity.py:45-59`), override by arg or `HARNESS_MAX_CONCURRENT`.
- **Timeouts.** `queue_timeout=600.0` default (`scheduler.py:80`); `run_timeout` exists and is honoured if set (`scheduler.py:81, 174-175`) but **both construction sites omit it** (`bootstrap.py:100`, `egress_proxy.py:303`) → a running model call is unbounded at the scheduler.
- **State.** `_handles`/`_tasks` are in-memory dicts; `handle.status` is a free string with no transition validation. Everything is lost on exit.
- **FIFO claim.** Module docstring says same-matter turns serialize FIFO **[docstring claim]**. `asyncio.Lock` does not guarantee FIFO wake-up; the deque is bookkeeping for `cancel()` (`scheduler.py:71`), not an ordering mechanism. Overstated.
- **Cross-process.** No file locks anywhere; nothing stops two TUI/CLI processes driving the same session. The per-matter lock serializes model calls inside one proxy only.

**Verdict for §7's critical question:** the scheduler is **in-process and non-durable**. It is a sound *admission controller for model calls* and should be kept in that role; it is not, and should not be stretched into, the durable workflow scheduler.

---

## 5. Persistence

| Store | Location | Schema (verified) | Durable? |
|---|---|---|---|
| Session index | `<store>/sessions/index.sqlite3` | `sessions(session_id PK, matter_ref, display, turns, started, updated, opencode_session)`; `jobs(id, session_id, stage, agent, status, detail, ts)` (`store.py:62-76`) | Yes; no WAL / busy_timeout |
| Turn log | `<store>/sessions/<sid>.jsonl` | TurnRow `{ts, session_id, matter_ref, display, agent, tools_used[], output_summary, docs_touched[], trace_refs[], thinking}` | Yes, append |
| Errors | `errors.jsonl` | `{ts, where, exception, message, cause, line, context}` | Yes, append |
| Dispatch trace | `trace.db` | `dispatches(id, ts, matter_ref, task_class, classification, provider, model, weights_revision, engine, verified, tokens_in/out/cache, latency_ms, status, error)` + ALTER-added backend/agent/session_id/tokens_reasoning; WAL | Yes; **mutable** (`trace.py:123-136` UPDATEs rows) |
| Corpus | `<store>/corpus.sqlite3` | per-matter `docs_<m>(doc_id, source_name, sha256, words, chunk_count, ts)`, `fts_<m>`, `cites_<m>` | Yes |
| Vectors | `<store>/vectors.sqlite3` | `embeddings(…, matter_ref, seq, text, model, provider)` + `vec0(float[1024], matter_ref PARTITION KEY)` | Yes |
| Agent memory | `agent_memory.db` | `agent_memory(agent PK, body…)`, `memory_versions`, `agent_edit_proposals`, `benchmark_runs`, `agent_probe_suites` (`agent_memory.py:29-43`) | Yes; keyed by **agent, not matter** |
| Workspaces | `<store>/workspaces/<sid>/<agent>[-stage-<s>]/` | git-snapshotted files, `matter.json`, `allowed.json`, `guard-log.jsonl`, per-agent opencode data root | Yes |

Gaps: the `jobs` table is **written, never read back** to drive execution; a crash leaves the last job `running` forever (no reconciliation); `store.py:8` claims "a lost index is rebuilt from the files" **[docstring claim]** — no rebuild code exists. Interjections, scheduler queue and "which stage is next" are not persisted.

---

## 6. Security

### 6.1 Egress

Path: opencode → `gate-local` provider pinned to `http://127.0.0.1:7373/v1/m/<matter>` at sync (`stand_up_opencode.py:229-232`) → proxy (unknown alias → 400, unregistered matter → 500, `egress_proxy.py:186-211`) → `EgressGate.dispatch` (`gate.py:158-225`), fail-closed routing for unlisted task classes, refusals traced. Confinement layers are config + env, not kernel-enforced: `disabled_providers: ["opencode"]` in the mount template, bearer-env scrub (`stand_up_opencode.py:88-155`), per-agent data roots, exclusive port bind (`egress_proxy.py:287-293`). **Model-API traffic has no bypass found.**

### 6.2 MCP

**No MCP server or client is configured anywhere in harness-core.** The opencode binary supports `opencode mcp`; an agent with `bash` could invoke it. MCP is therefore not a configured surface but **is a latent one wherever bash is enabled**. Any future MCP integration must be routed through the gate or treated as a blocker (brief §10).

### 6.3 Findings, severity-ranked

| # | Sev | Finding | Evidence |
|---|---|---|---|
| S1 | **HIGH** | `ironfleet_corpus_search` accepts `matter` as a **model-supplied tool argument** that overrides the workspace binding → cross-matter corpus read chosen by the model | `corpus.py:552` (`matter = args.get("matter", matter) or matter`), env fallback only at `:553` |
| S2 | **HIGH** | Builtin `bash`/`webfetch` not universally denied. Denial is per-persona and only when `denied_tools` is non-empty (`module_e/personas.py:7-8, 59-63`); the `citation` persona has `denied_tools: []` (`data/module-e/personas.yaml:61-62`). Persona files drive the CLI `--turn` path and `spawn_agent` children (`spawn_tool.py:52-58`). Direct network egress outside the gate, and `edit`/`write` can rewrite the guard's `allowed.json`. (Factory stage files are **not** affected — `factory.py:130-135`.) | |
| S3 | MED | Loopback proxy is unauthenticated; `X-IronFleet-Matter` header takes precedence over the path (`egress_proxy.py:201`) — any local process can dispatch as any registered matter | `egress_proxy.py:169-215` |
| S4 | MED | Guard is annotate-only in production: mounts ship `{"block": false}` (`stand_up_opencode.py:279`); `guard-log.jsonl` truncated every sync (`:282`); both files live in the agent-writable workspace | |
| S5 | MED | `agent_memory.db` keyed by agent and injected into every mount — a cross-matter channel via canon (2,000-char cap, delimiter-validated, not matter-scoped) | `agent_memory.py:29-31` |
| S6 | MED | Matter classification set by the UI, not by matter policy: the TUI dispatches every task with `classification="CLOUD_PERMITTED"`, `complexity="HIGH"` hardcoded | `session/tui.py:695-699` |
| S7 | LOW | Audit not tamper-evident: `trace.db` rows UPDATEd by `attr()` (`trace.py:123-136`); no hash chain; guard log wiped per sync | |
| S8 | LOW | No human-approval mechanism for consequential actions (closest: `agent_edit_proposals` propose/decide for memory edits) | not found |
| S9 | LOW | `IRONFLEET_<NAME>_URL` env overrides re-point providers unvalidated (operator-level) | `bootstrap.py:129-134` |
| S10 | INFO | Guard legacy bypass: a payload with no `allowed_passages` key skips the quote check and approves | `spike/guard_port.py:37-45`; documented as intended in `tests/test_quote_check.py:94-98` |

No authn/authz of any kind exists (no users, roles, login, API auth). Secrets are in the OS keychain (`keychain.py`, service `ironfleet-harness`); no keys in YAML; traces store token counts only.

---

## 7. Legal RAG

| Stage | Implementation | Evidence | Tested |
|---|---|---|---|
| Ingest | Manifest-driven `ingest_any`; parser chain markitdown → pypdf → raw in a killable subprocess, 180 s watchdog | `ingest_generic.py:107-157` | test_corpus_ingest, test_statute_ingest |
| Statute split | One record per provision; statute-vs-prose detection | `ingest_generic.py:35-78` | yes |
| Chunking | Structure-aware, 210-word target, hard split at 2×, heading as provenance | `corpus.py:29-83` | test_corpus |
| Embedding | `bge-m3:567m` via the gate, task class LOCAL_ONLY → never leaves the box | `ingest_generic.py:158`, `gate.py:53` | indirect |
| Vector store | sqlite-vec, 1024-dim, partitioned by matter, idempotent per (matter,text) | `vectors.py:60-117` | test_vectors (13, incl. isolation) |
| Lexical | Per-matter FTS5, BM25 | `corpus.py:243-244, 281-284` | yes |
| Citation join | Canonical act/year/section and case keys in `cites_<m>` | `corpus.py:125-201` | yes |
| Fusion | RRF k=60 with per-hit supply diagnostic | `corpus.py:458-465` | yes |
| Expansion | Multi-query, schema-validated, fail-open; model `qwen3.8:27b` **hardcoded**; default off | `corpus.py:484-504, 579` | yes |
| Rerank | Local llama-server `/rerank`, LOCAL_ONLY; **silent fail-open** on any exception | `gate.py:319-344`, `corpus.py:595-603` | test_gate_rerank |
| Quote verification | Deterministic normalised containment; select-compose `[E#.S#]` splicing | `quote_check.py`, `corpus.py:620-668` | test_quote_check (10) |

**Recorded quality (not production-ready):**
- Golden RAG (`data/eval/R1-GOLDEN-RAG-2026-10-15/SUMMARY.md`): no-corpus baseline ca 0.117 / gs 0.367 → product arm **ca 0.278 / gs 0.650**, quote verification 269/379, **0/30 cases passed**. Compose arm ca 0.233 (below product on citations).
- Retrieval failure analysis (`data/eval/R1-ACCEPT/RETRIEVAL-FAILURE-REPORT.md`, 7,229 docs / 19,763 chunks): of 69 needles — ABSENT 13, PRESENT_NOT_RETRIEVED 29, BELOW_POOL 9, LOST_AT_RERANK 5, **SUPPLIED 13**; ratified bar 42/56 of present needles **not met**.

**Gaps vs brief §8:** no metadata/jurisdiction/doc-type columns or filters (`corpus.py:240-242`); no document versioning — `INSERT OR REPLACE` on `doc_id` (`corpus.py:247`); licence/source_url/retrieved are **required at ingest but not persisted** (`ingest_generic.py:81-89`) so provenance does not reach retrieval output; no separate store for a matter's own documents vs shared law (law is ingested per matter); rerank failures unobservable; embedding model not checked at search time (two 1024-dim models would mix silently). Cross-matter isolation is enforced by construction **except** S1.

Scripts named in the brief that **do not exist** in this repo: `extract_quotes`, `sentenceize`, `anchor_regex`, `classify`, `seed_legacy_db`, `select_parity_subset` (and `ingest_statutes` — the real file is `scripts/statute_ingest.py`).

---

## 8. Existing TUI

`src/harness/session/tui.py` (719 L), Textual app `IronFleetApp`. Layout: chat scroll left; tabs Jobs/Docs/Corpus/Thinking right; status bar with token meter; prompt input (`compose`, `tui.py:248-269`). Bindings shift+tab mode cycle, ctrl+q, ctrl+o copy via `clip.exe` (`:202-217, 519-533`). Slash commands `/mode /doctor /ingest /plan /persona new /provider` (`:485-517`). One 2 s poll timer refreshes every pane (`:477`). Reads `session.db`, `trace.db`, workspace git status, `corpus.sqlite3`, guard logs in-process.

**~300 lines of backend logic are trapped in the app class** and unreachable without Textual: `/ingest` wiring (`:593-617`), `/doctor` assembly (`:548-577`), `/persona new` writing `personas.yaml` directly (`:619-638`), `/provider` (`:640-649`), session digest (`:651-672`), auto-compact-then-dispatch with hardcoded classification (`:674-708`), deliverable scanning (`:295-303`). Pure, tested, reusable: `cycle_mode`, `render_status`, `render_jobs`, `render_agents`, `split_plan` (`:53-171`) and the whole of `view.py`, `commands.py`, `tokens.py`.

**Owner direction (2026-11-04):** the owner has rejected this TUI and asked for its removal. It is **not removed** by this audit (§18). Its disposition is RETIRE, gated on extracting the trapped logic first (§11).

---

## 9. APIs

The **only** HTTP surface is the egress proxy: stdlib `http.server.ThreadingHTTPServer` (`egress_proxy.py:17`), `_ExclusiveBindServer` (`:287`), OpenAI chat-completions shape, loopback, consumed by opencode only. It bridges HTTP threads to one background asyncio loop via `run_coroutine_threadsafe` behind a module lock (`egress_proxy.py:22-52`) — a proven in-repo pattern for a threaded HTTP front over async internals.

There is **no** REST, WebSocket, SSE or IPC surface for execution status, agent inspection, control, artifacts or approvals; no serialization layer for those objects; no auth. Everything a frontend needs exists only as **substrate** (the SQLite files, JSONL, workspace trees) that the TUI reads in-process. Brief principle 9 ("API-first; the frontend must not depend on private in-process implementation details") is unmet.

---

## 10. Tests

78 files; pytest + pytest-asyncio (auto). Unit tests use injected fake transports — "No network, ever" (`tests/test_agent_loop.py:3`). Coverage is broad: store/driver/factory/workspace/errors/tokens/view/commands/tui; gate/policy/alias/capacity/scheduler/trace; egress proxy fail-closed paths; corpus/vectors/ingest/quote_check; providers; module_e characterization/kernels/spawn schema/tools/skills/supervisor; persona generator; env scrub; guard envelope/port; packaging (Windows/macOS/macdist/launcher). `test_accept_*` drive acceptance logic with stubs and import `scripts/accept_r3.py`, `accept_s7c.py` etc.

Not covered by the suite: live opencode/provider runs (scripts only); RAG quality benches (`scripts/bench_r1_*`, off-suite); **crash/restart recovery** (no such capability to test); cross-process concurrency on one session; builtin-tool-denial coverage across all personas; the S1 tool-arg override (isolation tests bind the matter by parameter, not by adversarial tool arg). Platform skips: `test_pack_macos.py:29,36`, `test_accept_s7g.py:102,148`, `test_session_tui.py:12` (`importorskip("textual")`).

---

## 11. Component disposition (§13)

Each entry: **Location · Current implementation / functionality · Dependents · Evidence · Tests · Limitations → Classification · Reasoning · Migration implications · Risk.**

### 11.1 Model egress and governance core

**EgressGate** — `src/harness/gate.py` (412 L) · single dispatch point: classification, routing, provenance check, rerank, embeddings, trace on every outcome · dependents: egress_proxy, corpus tool, eval runner, bootstrap, driver (via trace) · `gate.py:81, 98-130, 158-225, 319-344` · test_gate, test_gate_rerank · no per-tenant policy → **KEEP**. Proven, refusal-traced, the security spine. Migration: becomes the "Model Gateway" service unchanged; tenant/matter policy arrives as data on the request. Risk: Low.

**Routing policy** — `policy.py`, `alias.py`, `data/routing*.yaml` · task-class → provider tiers; structural rule embeddings/rerank never route to cloud (`policy.py:16, 53-54`); fail-closed defaults · test_policy, test_routing_a1, test_alias → **KEEP**. Risk: Low.

**Egress proxy** — `egress_proxy.py` (323 L) · loopback OpenAI-shaped front for opencode, per-matter `matter.json`, scheduler submit · dependents: launcher, stand_up_opencode, bootstrap · `:169-215, 287-303` · test_egress_proxy · unauthenticated, header-trusted matter (S3) → **EXTEND**: bind each workspace to a per-run token that resolves to exactly one matter; ignore client-supplied matter when a token is present. Migration: opencode mount gets the token in its provider config at sync. Risk: Medium (touches every turn).

**TurnScheduler** — `scheduler.py` (230 L) · model-call admission: per-matter lock, global semaphore, queue timeout, cancel · dependents: egress_proxy, bootstrap · `:73-90, 142, 174-175, 204-224` · test_scheduler · in-memory, unbounded running call, FIFO overstated, per-matter concurrency fixed at 1 → **EXTEND** (not replace): wire `run_timeout`; make per-matter concurrency a budget (default 1) so in-matter parallel branches are possible; true FIFO via the deque if ordering is promised. It stays the admission controller; durable scheduling is a **new** layer above it. Risk: Medium.

**Capacity** — `capacity.py` · machine-probed cap · test_capacity → **KEEP**. Risk: Low.

**Bootstrap** — `bootstrap.py` · builds gate + scheduler, provider specs, env URL overrides · `:93-100, 129-134` → **EXTEND**: pass `run_timeout`; validate `IRONFLEET_*_URL` (scheme/host allow-list). Risk: Low.

**Providers** — `providers/` · registry, transports, probe, provenance, retry · test_providers_* → **KEEP**. Risk: Low.

**Keychain** — `keychain.py` · OS keychain secrets · no dedicated test → **KEEP** (add a test when touched). Risk: Low.

**Trace store** — `trace.py` · dispatch ledger, WAL, attribution by UPDATE (`:123-136`) · test_trace, test_trace_identity · mutable, no hash chain → **EXTEND**: keep as the operational dispatch ledger; write attribution as an append-only event instead of UPDATE, or mirror dispatches into the new hash-chained audit log. Risk: Low.

### 11.2 Execution and orchestration

**SessionDriver** — `session/driver.py` · one opencode turn, recorded failure, resume handle · dependents: factory, tui, session_cli · `:55, 110-176` · test_session_driver · abandons rather than kills on timeout → **EXTEND**: kill-on-abandon seam (return the Popen handle / pid to the caller). Becomes the body of the agent-execution worker. Risk: Low.

**FactoryRunner** — `session/factory.py` (316 L) · plan parse, legal pipeline fallback, sequential stages, handoff, failure-continue, in-memory interjection · dependents: tui, accept_r3 · `:116-122, 243-316` · test_session_factory · sequential only, no checkpoint/resume, stale copies, continues on failure, in-memory interjections, dead supervisor import → **EXTEND**. Its `_run_stage` is the proven unit of work; `run_task`'s loop is what moves into the durable orchestrator. Preserved: plan grammar, pipeline-as-data, stage-file-after-sync rule (F5/P7), STAGE_MODEL flag rule, one-prompt→pipeline ruling. Risk: Medium.

**SessionStore** — `session/store.py` · sessions/jobs index + JSONL · dependents: driver, factory, tui, session_cli, tokens · `:62-76, 151-164` · test_session_store · no WAL, jobs write-only, false rebuild claim → **EXTEND**: WAL + busy_timeout; reconcile orphan `running`; correct or implement the rebuild claim. Remains the conversation/turn log; workflow state goes to new tables. Risk: Low.

**Workspace** — `session/workspace.py` · per-agent dirs, isolated opencode data root, env, supervised spawn with retry · test_session_workspace, test_env_scrub → **KEEP**. Risk: Low.

**spawn_agent tool** — `module_e/spawn_tool.py` · synchronous child turn in sibling workspace · `:28-61` · test_spawn_tool_schema · invisible to ledger/scheduler, drives persona files (S2) → **EXTEND**: record child as an AgentRun with parent link; route through the orchestrator so delegation is visible, cancellable and permission-scoped. Risk: Medium.

**Supervisor routes** — `module_e/supervisor.py`, `data/module-e/supervisor.yaml` · intent → persona lists; reachable only via the `route` tool · imported unused at `factory.py:29` · test_supervisor → **INVESTIGATE**: the one-prompt ruling made the fallback path the pipeline; decide whether routes become workflow-definition selection (per matter type) or retire. Risk: Low.

**Errors / tokens / view / commands** — `session/errors.py`, `tokens.py`, `view.py`, `commands.py` · error ledger, trace-join token meter + compaction, pure read models, pure command assembly · tests exist for each → **KEEP**. These become the read side of the application service. Risk: Low.

### 11.3 Crew, tools, guard

**Personas generator** — `module_e/personas.py`, `data/module-e/personas.yaml` · renders persona md with tools map + `permission: deny` · `:7-8, 40-63`; `personas.yaml:61-62` · test_persona_generator · builtin denial is opt-in (S2) → **EXTEND**: invert to deny-by-default for `bash`, `webfetch`, `websearch`, `edit` outside an explicit allow-list per persona. Risk: Medium (persona behaviour changes; re-run golden cases).

**Guard** — `module_e/guard.py` (renderer, 25 L), `spike/guard_port.py`, `spike/guard_cli.py`, `spike/candidates/opencode/ironfleet-guard-s7c.ts` · tool.execute.before scan; annotate `[UNGROUNDED]`/`[UNQUOTED]` · `stand_up_opencode.py:279-282`; `guard_port.py:23-45` · test_guard_envelope, test_guard_port, test_quote_check · annotate-only default, agent-writable authority file, log wipe, legacy bypass, production logic in `spike/` → **EXTEND**: move guard logic out of `spike/`; authorities and log outside the agent workspace (harness-owned path, read-only to the agent); block configurable per matter policy with block as default for verify/filings stages; append the log, never truncate. Risk: Medium.

**Tool dispatch / manifest / kernels / skills / refine / vendored** — `module_e/dispatch.py`, `tools.py`, `kernel_tools.py`, `skills.py`, `refine.py`, `vendored/` · manifest-driven tool subprocess; NZ statutory-demand, court calendar, without-prejudice kernels · tests exist → **KEEP**. Risk: Low.

**Agent memory** — `agent_memory.py` · per-agent canon, versions, edit proposals · `:29-43` · test_agent_memory · not matter-scoped (S5) → **INVESTIGATE**: owner decision whether canon is intentionally cross-matter (agent "skill learning") or must be matter-partitioned; either way add a content check that refuses matter identifiers in canon. Risk: Medium.

**Mount substrate** — `scripts/stand_up_opencode.py` (363 L: `sync_mount`, `child_env`, `generate_all` call, memory injection) and `scripts/run_spike_opencode.py` (`run_opencode`, tree-kill, event parse) · **imported by `src/`** (`workspace.py`, `spawn_tool.py:45, 59`) · test_stand_up_opencode, test_run_spike_opencode → **KEEP** behaviour, **relocate** into `src/harness/` (production code living in `scripts/` and named "spike" blocks non-editable packaging). Risk: Low (move + re-export).

**Spike persona port** — `spike/persona_port.py` · historical port superseded by `module_e/personas.py` · importers not verified in this audit → **INVESTIGATE** (grep importers; RETIRE if none). Risk: Low.

### 11.4 RAG and evaluation

**CorpusStore + corpus tool** — `corpus.py` (668 L) · split, FTS5, citation join, RRF, expansion, rerank, select-compose · test_corpus (25) · S1, no metadata filters, no versioning, hardcoded expansion model, silent rerank fallback → **EXTEND**. Risk: **High for S1** (security), Medium otherwise.

**VectorStore** — `vectors.py` · test_vectors → **KEEP** (add model check at search). Risk: Low.

**Ingest** — `ingest_generic.py`, `scripts/corpus_ingest.py` · test_corpus_ingest, test_statute_ingest → **EXTEND**: persist licence/source_url/retrieved/jurisdiction/doc-type into `docs_<m>`; version rows instead of replace. Risk: Low.

**Quote check** — `quote_check.py` → **KEEP**. Risk: Low.

**Eval harness** — `eval/`, `scripts/bench_r1_*`, `check_golden.py`, `rescore_sidecars.py`, `report_r1_retrieval_failures.py`, `data/golden_cases/` → **KEEP**; becomes the RAG acceptance gate (§06). Note `eval/runner.py` does no retrieval — RAG evals live in the bench scripts. Risk: Low.

**statute_ingest shim** — `scripts/statute_ingest.py` · self-described compat wrapper over `ingest_any` (`:1-8`) · dependents: `tests/test_statute_ingest.py`, any operator habit → **RETIRE** after the test is pointed at `corpus_ingest`/`ingest_any`. Preserved: the provision-level statute path, which lives in `ingest_generic.py` already. Risk: Low.

### 11.5 Surfaces, packaging, artefacts

**Textual TUI** — `src/harness/session/tui.py` (719 L) + launcher `scripts/tui.py` (52 L) · operator shell · dependents: `scripts/accept_r3.py:128,366`, `scripts/tui.py:50`, `tests/test_session_tui.py` · owner rejected 2026-11-04 → **RETIRE**. Functionality to preserve **before** removal: the ~300 L of command/dispatch logic (§8) moved into an application-service module callable by CLI and API; the pure renderers' information model (jobs ledger, agent table with provider/model/verified/tokens/guard count, deliverable list, thinking pane) carried into the new workspace spec (§05). Removal is not authorized now. Risk: Medium (accept_r3 + tests must be rehomed).

**CLI** — `cli.py`, `scripts/session_cli.py` → **KEEP**; CLI subcommands later call the same application service as the API. Risk: Low.

**Launcher / ops / packaging** — `ops/`, `packaging/macdist.py`, `scripts/pack_windows.py` → **KEEP**; **EXTEND** packaging to non-editable once mount substrate moves into `src/`. Risk: Low.

**Security prechecks** — `security/` → **KEEP**. Risk: Low.

**Acceptance drivers** — `scripts/accept_r1*.py, accept_r2.py, accept_r3.py, accept_s7b…s7i.py` · milestone sign-off drivers · dependents: `tests/test_accept_*` import several (`accept_r3`, `accept_s7c`, …) → **RETIRE (deferred)**. Preserved: the regression assertions the `test_accept_*` files make; move the imported helpers into test fixtures first. Risk: Low.

**Root trace DBs and `pytest-output.txt`** — repo root · one-off outputs of acceptance/probe runs · no importer verified by this audit → **RETIRE** after a grep confirms no reference and the owner confirms no evidentiary value (some back recorded acceptance claims). Risk: Low.

**Decision records** — `CUTOVER-RULING-2026-10-12.md`, `M0_DECISION-2026-09-03.md`, precheck reports → **KEEP** (history; move under `docs/decisions/` later). Risk: None.

### 11.6 Summary matrix

| Classification | Components |
|---|---|
| KEEP | gate, routing policy, capacity, providers, keychain, workspace, errors, tokens, view, commands, dispatch/tools/kernels/skills/refine/vendored, vectors, quote_check, eval harness, CLI, ops/packaging, security prechecks, mount substrate (relocate), decision records |
| EXTEND | egress_proxy, scheduler, bootstrap, trace, driver, factory, store, spawn_tool, personas, guard, corpus, ingest |
| REPLACE | **none** — no component is unsuitable for the target; gaps are additive |
| RETIRE | TUI + launcher (gated on extraction), statute_ingest shim, acceptance drivers (deferred), root artefact DBs |
| INVESTIGATE | supervisor routes, agent_memory scoping, spike/persona_port |

---

## 12. Technical debt

1. Production code in `scripts/` and `spike/` (`stand_up_opencode`, `run_spike_opencode`, `guard_port`) imported by `src/` — blocks non-editable packaging and misleads readers.
2. Business logic in the UI class (`tui.py`, ~300 L).
3. Three files named "tui" with unrelated purposes (`session/tui.py`, `scripts/tui.py`, `scripts/probe_r3_tui.py`).
4. Docstrings overstating behaviour: scheduler FIFO, store rebuild, factory modes.
5. Dead import (`factory.py:29`) and dead route path.
6. Hardcoded model ids in retrieval (`corpus.py:579`, `ingest_generic.py:158`) outside the routing table.
7. Status values are free strings everywhere (jobs, scheduler handles); no state machine.
8. Append-only intent implemented with UPDATE (`trace.py:123-136`) and truncation (`stand_up_opencode.py:282`).
9. One shared `corpus.sqlite3`/`vectors.sqlite3` per store root; isolation is logical (per-matter tables / partitions), not physical.

## 13. Risks (ranked)

| Risk | Why it matters | Mitigation phase (§06) |
|---|---|---|
| Cross-matter read via tool arg (S1) | Confidentiality breach decided by a model | Phase 1 |
| Unguarded network egress via builtin tools (S2) | Privileged text can leave the box outside the gate; MCP latent here | Phase 1 |
| Non-durable execution | A crash mid-pipeline loses position; orphan state; no resume; no multi-day work | Phase 3 |
| Failure-continue pipeline | Later stages draft advice on missing research without flagging | Phase 3 |
| No authn/authz | Any multi-user deployment is unsafe | Phase 2/6 |
| RAG quality below ratified bar | 0/30 golden cases pass; legal outputs not trustworthy unsupervised | Phase 7 (eval-gated) |
| No approval gate | Filings/advice produced with no human checkpoint | Phase 4 |
| No API | No frontend possible without coupling to SQLite internals | Phase 5 |
| opencode dependency | Pinned third-party binary is the agent runtime (startup-hang class already mitigated by watchdog + retry) | ongoing |
