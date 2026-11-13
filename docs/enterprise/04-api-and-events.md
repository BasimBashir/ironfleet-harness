# 04 — API and Event Contract (proposed)

**Date:** 2026-11-04 · **Status:** proposal — building endpoints is not authorized yet (brief §18, Phase G) · **Companion to:** [02-target-architecture.md](02-target-architecture.md) (§11), [03-data-model.md](03-data-model.md) (entities referenced below).

## 0. What the audit says we start from

- The only HTTP server today is the loopback egress proxy: stdlib `http.server.ThreadingHTTPServer` bridging threads into one asyncio loop via `run_coroutine_threadsafe` (egress_proxy.py:17, 22-52, 287). It is internal, OpenAI-shaped, and serves opencode only.
- No REST/WS/SSE surface, no auth, no serialization layer exists (01 §9).
- The stack already ships **pydantic ≥2.6** (gate request/response models) and **httpx ≥0.27** (client side). No server framework is installed.
- Principle 9 (API-first: the frontend must not depend on private in-process details) and principle 11 (no premature technology selection) govern everything below.

## 1. Protocol decision: REST + SSE; no WebSockets

**REST** for every command and read. Reasons grounded in this codebase:

- Every interaction in the brief (brief §3, §9; deliverable-4 list) is command/response or read — create matter, dispatch, approve, inspect, pause, fetch artifacts. None needs a bidirectional socket.
- The existing process model (threaded HTTP front over one asyncio loop) is proven in-repo; REST requests map onto it directly, and the orchestrator's SSE fan-out is a second consumer of the same loop.
- HTTP caching/semantics give the Matter Board polling-free reads (`ETag` on collection endpoints).

**SSE** (server-sent events) for live activity: per-matter execution channels and a board-level summary channel. Reasons: one-directional push is exactly the need; SSE is plain HTTP (works through the same server, no upgrade dance), auto-reconnects with `Last-Event-ID` replay which maps cleanly onto the append-only `workflow_events` table, and needs no client library.

**WebSockets — rejected.** No specified interaction requires server-initiated *requests* to the client. Adding WS means a second delivery path, its own reconnect/auth semantics, and proxy friction, for zero specified capability. Revisit only if a future feature needs true duplex (e.g. streaming token-by-token chat echo, which is not requested — counsel chat is turn-based, matching today's driver model).

## 2. Server framework: one new dependency, flagged for approval

| Option | Assessment |
|---|---|
| **FastAPI + uvicorn (recommended)** | New dependency (brief §18 requires owner sign-off). Rationale: pydantic models are already the house style (gate.py:7), so endpoint schemas reuse them directly; typed contracts are a stated NFR (brief §16); async-native fits the single asyncio loop; built on Starlette's mature SSE/StreamingResponse primitives. Cost: two packages (fastapi, uvicorn), locked and prechecked like every dep (security/ pattern exists: dsh_precheck/opencode_precheck). |
| Extend stdlib `http.server` | Zero new deps, matches the proxy's pattern. Cost: hand-rolled routing, auth middleware, SSE framing, OpenAPI/schema generation, and validation — a few hundred lines of framework reimplementation that FastAPI gives tested. |
| aiohttp/Flask/Litestar | No advantage over FastAPI here; Flask is sync-first (wrong loop model); aiohttp would duplicate the pydantic contract work. |

Recommendation: **FastAPI + uvicorn**, mounted in the same service process as the proxy (02 §1). If the owner prefers zero new dependencies, the stdlib path is viable but slower to build and to keep typed; the API *shapes* below are framework-neutral either way.

## 3. Authentication and session model

- **Transport:** loopback or LAN TLS-terminated by the OS/front proxy; the API itself issues **opaque bearer tokens** on login (`POST /api/v1/auth/login` with local credentials → token + refresh). Single-tenant deployment; the `tenant_id` is resolved from the user (03 §2.1).
- **Authorization:** the API layer authenticates and attaches the principal; **all permission checks live in the service layer** (02 §2) using `Permission`/`Role`/`matter_members` (03 §2.3-2.5). The API never makes an authorization decision itself.
- **Agents are not API callers.** opencode subprocesses keep their existing path (loopback proxy with per-run matter token, 02 §12). The API serves humans and the CLI.
- **Idempotency:** mutating POSTs accept `Idempotency-Key`; the service stores the key → response for safe retries (mirrors the durability posture: an operator retrying after a crash must not double-dispatch a pipeline).

## 4. Conventions

- Base path `/api/v1`. JSON bodies; ISO-8601 timestamps; text ids (`m-…`, `wf-…`, `exe-…`, `run-…`).
- Errors: `{ "error": { "code", "message", "details", "trace_id" } }`; codes are stable strings (`matter_not_found`, `permission_denied`, `invalid_transition`, `lease_conflict`).
- Collections: cursor pagination (`?limit=&cursor=`, response `{"items": […], "next_cursor": …}`).
- Long-running commands return **202 + a resource**, never block: dispatching a task returns the `WorkflowExecution` created; clients follow it via status endpoints or SSE.
- All reads are matter-scoped after authz; there is no cross-matter endpoint except the explicit, permission-gated `matter.cross_read` capability (03 §2.4).

## 5. Endpoint catalog

Schemas shown are representative request/response shapes (entity fields per 03).

### 5.1 Auth

```
POST /api/v1/auth/login            {username, password} → {token, expires_at}
POST /api/v1/auth/refresh          → {token}
GET  /api/v1/auth/me               → {user, roles, permissions[]}
```

### 5.2 Matter management

```
GET    /api/v1/matters?state=&q=&cursor=     → {items: [MatterSummary], next_cursor}
POST   /api/v1/matters                        {title, client_ref, matter_type, jurisdiction, confidentiality, objectives, deadlines} → Matter
GET    /api/v1/matters/{mid}                  → Matter (full metadata, sections per brief §4)
PATCH  /api/v1/matters/{mid}                  {priority?, objectives?, deadlines?…} → Matter
POST   /api/v1/matters/{mid}/state            {to: "queued"|"archived"|…, note} → Matter      # only legal transitions (02 §4)
GET    /api/v1/matters/{mid}/members          → [{user, role}]
PUT    /api/v1/matters/{mid}/members/{uid}    {role_id} → member
DELETE /api/v1/matters/{mid}/members/{uid}    → 204
```

`MatterSummary` = board row: id, reference, title, client, type, jurisdiction, state, priority, lead agent, active agent count, current stage, last_activity, **outstanding approvals count**, next deadline, deliverable status, risk flags — everything the Matter Board renders (brief §3.1) in one read.

### 5.3 Documents, evidence, artifacts

```
POST   /api/v1/matters/{mid}/documents        multipart upload {doc_type?, jurisdiction?} → MatterDocument (ingest_status=pending)
POST   /api/v1/matters/{mid}/documents/ingest {source_spec} → 202 {ingest_run}                   # the extracted /ingest use-case (01 §8)
GET    /api/v1/matters/{mid}/documents        → paged MatterDocument[]
GET    /api/v1/documents/{doc_id}             → bytes (stream; authz via parent matter)
GET    /api/v1/matters/{mid}/evidence?q=&verified= → paged Evidence[] (02 §2.8 shape)
GET    /api/v1/matters/{mid}/artifacts?review_state= → paged Artifact[]
GET    /api/v1/artifacts/{aid}                → Artifact + content ref
POST   /api/v1/artifacts/{aid}/review         {decision: approve|reject|request_changes, note} → Artifact
```

Search over the matter's corpus stays an **agent-tool**, not an API: retrieval quality is governed by the RAG path (fusion/rerank/quote-verify, 01 §7). The API exposes evidence *records*, not raw vector search, until the eval-gated bar is met (06 Phase 8).

### 5.4 Workflows and execution

```
GET    /api/v1/workflows                       → [Workflow]                    # definitions incl. default legal pipeline
POST   /api/v1/workflows                       {name, definition|yaml} → Workflow
POST   /api/v1/matters/{mid}/executions        {workflow_id?, task_text, plan_block?} → 202 WorkflowExecution
       # workflow_id omitted ⇒ default pipeline; plan_block accepted in the existing ```plan grammar (factory.py:59-82)
GET    /api/v1/executions/{eid}                → WorkflowExecution + tasks[]
GET    /api/v1/executions/{eid}/tasks          → Task[] (states, leases, dependencies)
POST   /api/v1/executions/{eid}/pause          → 202   # graceful: finishes in-flight turn, parks
POST   /api/v1/executions/{eid}/resume         → 202
POST   /api/v1/executions/{eid}/cancel         {reason} → 202                    # tree-kills running turns (driver kill seam, 02 §5)
POST   /api/v1/executions/{eid}/redirect       {task_id, instruction} → 202      # re-scope a pending/paused task
```

Pause/resume/cancel are **202-then-observe** on purpose: the UI must not show success before the backend confirms the state change (brief §3.2 requirement) — the SSE event `execution.state_changed` is the confirmation.

### 5.5 Agent management and inspection

```
GET    /api/v1/agents                          → Agent roster (03 §2.9)
POST   /api/v1/agents                          {name, role, tool_policy, default_task_class} → Agent
PATCH  /api/v1/agents/{aid}                    → Agent
GET    /api/v1/matters/{mid}/runs?state=       → AgentRun[]                     # swarm-graph edges from parent_run_id
GET    /api/v1/runs/{rid}                      → inspection payload (brief §3.2 list):
       { persona_snapshot, objective, parent, dependencies, state, timeline: WorkflowEvent[],
         tool_calls[], evidence_refs[], artifacts[], errors[], trace_summary {tokens, providers, verified}, duration }
POST   /api/v1/runs/{rid}/interject            {text} → 202                     # durable replacement for in-memory inject() (01 §3.1)
POST   /api/v1/runs/{rid}/cancel               → 202
```

### 5.6 Approvals (the "Waiting on you" machine)

```
GET    /api/v1/approvals?state=pending        → paged Approval[]               # board-level "needs attention"
GET    /api/v1/matters/{mid}/approvals        → Approval[]
POST   /api/v1/approvals/{apid}/approve       {note?} → Approval               # permission: approval.decide
POST   /api/v1/approvals/{apid}/reject        {note}  → Approval
POST   /api/v1/matters/{mid}/requests         {kind: info|evidence, question, task_id?} → Request-row  # human→agent info waits (03 §2.17 kind info_request)
POST   /api/v1/requests/{qid}/answer          {text|doc_ids} → 202            # un-parks the waiting task
```

Approve/reject un-parks the execution (02 §6) and writes the AuditEvent chain (03 §2.19).

### 5.7 Live activity (SSE)

```
GET /api/v1/events?channels=matter:{mid}      → text/event-stream
GET /api/v1/events?channels=board             → text/event-stream
```

Envelope (one per event, matching `WorkflowEvent`):

```
id: <seq>
event: task.state_changed
data: {"execution_id":"exe-…","task_id":"t-…","from":"leased","to":"running",
       "actor":{"run":"run-…"},"ts":"2026-11-04T09:31:02Z","matter_id":"m-…"}
```

- Channels authorize like any read (matter membership); a board channel carries only summaries the subscriber may see.
- Replay: `Last-Event-ID: <seq>` resumes from the append-only table — a reconnecting browser misses nothing (brief §16 "efficient event delivery").
- Heartbeat comment every 15 s for proxy keepalive.

### 5.8 Counsel chat (agent communication)

```
GET    /api/v1/matters/{mid}/conversations            → Conversation[]
POST   /api/v1/matters/{mid}/conversations            {title?} → Conversation
GET    /api/v1/conversations/{cid}/messages?cursor=   → Message[]
POST   /api/v1/conversations/{cid}/messages           {text, refs?} → 202 {message, execution?}
       # instructing lead counsel creates/extends a WorkflowExecution — the same dispatch use-case as 5.4, so
       # chat and the Matter Board are views of the same state (brief §3: "different views of the same state")
```

Turn-based by design (no streaming tokens): the reply arrives as agent runs + events on the matter's SSE channel; the conversation endpoint returns the final assistant Message when the run completes. `refs` may cite evidence/artifact/task ids, satisfying the evidence/artifact reference requirement (brief §3.3).

### 5.9 System

```
GET /healthz      → {stores: ok, proxy_bound: true, providers: probe summary, version}   # no auth; loopback only
GET /api/v1/audit?matter_id=&cursor=  → paged AuditEvent[]                               # permission: audit.read
```

## 6. What this API deliberately omits

- **No raw SQL/SQLite access, no generic query endpoint** — principle 9's whole point.
- **No direct corpus/vector search endpoint** (see 5.3 rationale).
- **No model-provider management API** in v1: `providers.yaml` + keychain stay operator-level (`harness providers` CLI). Exposing key material CRUD over HTTP is a security surface not yet required.
- **No WebSocket anything** (§1).
- **No multi-tenant admin API** beyond user/role CRUD — deployment is single-tenant (02 §1).

## 7. Client impact

The CLI migrates onto these services (not necessarily onto HTTP — it may call the service layer in-process; both surfaces stay in lockstep because they share use-cases, 02 §2). The web workspace consumes only this API + SSE. The TUI, in its remaining life, keeps reading its existing stores until retired (06 Phase 6 gate).
