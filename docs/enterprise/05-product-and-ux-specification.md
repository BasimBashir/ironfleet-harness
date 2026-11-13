# 05 — Product & UX Specification

**Date:** 2026-11-04 · **Status:** specification — no screen may be built until the owner approves the designs (standing instruction, 2026-11-04) · **Companions:** [02-target-architecture.md](02-target-architecture.md), [04-api-and-events.md](04-api-and-events.md).

## 0. Design direction

Professional, restrained, information-dense. Reference points are practice-management and review systems (docket-style tables, file ledgers), **not** consumer chatbots: no rounded mascot panels, no gradient hero, no emoji iconography. Concretely:

- **Density first.** Lawyers live in tables and timelines. Default row height compact; tables are the primary component; charts exist only where a number alone won't do (swarm graph).
- **One accent, semantically used.** Neutral greys + one accent colour for interactive elements; state colours reserved for the nine matter states (02 §4) and ten agent states (02 §5). Status is always colour **and** word (accessibility; printing).
- **Calm motion.** Transitions ≤150 ms; streaming updates patch rows in place (SSE, 04 §5.7) rather than flashing the page.
- **Typography:** one UI sans (system stack acceptable), tabular numerals for token/time columns, monospace only for citations, ids, and log excerpts.
- **Every agent claim is labelled by what it is** — verified quote, retrieved evidence, agent interpretation, unverified assertion (brief §8's distinctions rendered visibly, e.g. evidence chips with a verification badge from `Evidence.verified`).

## 1. Global layout and navigation

```text
┌────────────────────────────────────────────────────────────────────────┐
│ IronFleet        [⌘K Matter search…………………]        status ●  user ▾     │
├──────────────┬─────────────────────────────────────────────────────────┤
│ MATTERS      │  (main content: Board / Workspace / Swarm / …)          │
│  ▸ m-1042 …  │                                                         │
│  ▸ m-1077 …  │                                                         │
│  + New       │                                                         │
│──────────────│                                                         │
│ APPROVALS  3 │                                                         │
│ DRAFTS       │                                                         │
│ ACTIVITY     │                                                         │
│──────────────│                                                         │
│ ⚙ Providers  │                                                         │
└──────────────┴─────────────────────────────────────────────────────────┘
```

- Left rail: matters list (state dot + reference + title), a global **Approvals** entry with an unread count (the "Waiting on you" surface is global, not buried per matter), drafts, firm-wide activity, settings.
- `⌘K` palette: jump to matter, artifact, agent run, or run a command (the TUI's slash-command muscle carried over: 01 §8 pure command layer).
- Top bar: search, system health dot (`/healthz`, 04 §5.9), account menu.
- Deep-linkable URLs per section (board filter, matter tab, run id) — every panel is a route.

## 2. Matter Board (primary interface)

Landing view: portfolio table, one row per matter (brief §3.1 field list), sortable, filterable by state/type/jurisdiction.

```text
MATTERS                                    [All ▾] [Type ▾] [Jurisdiction ▾]   + New matter
────────────────────────────────────────────────────────────────────────────────────────
 REF      TITLE              TYPE        STATE             AGENTS  STAGE      APPROVALS  DUE        LAST ACT
 m-1077   Acme v State —…    Litigation  ● Waiting on you  4/6     filings    1 ⚑        14 Nov     2m ago
 m-1042   PPSA priority …    Banking     ● Running         3       research   —          03 Dec     12s ago
 m-1039   Due diligence —…   Corporate   ○ Draft           —       —          —          —          1d ago
 m-0988   Employment claim…  Employment  ✓ Review required 5       advice     —          overdue ⚠  1h ago
────────────────────────────────────────────────────────────────────────────────────────
 4 matters · 2 running · 1 needs your attention
```

- **"Waiting on you" is visually loudest**: pinned state filter chip `⚑ Needs you (3)` at the top; a matter in that state sorts ahead of running ones. The count in the chip is the `GET /approvals?state=pending` number — a database fact, never inferred client-side.
- Row click → Matter Workspace. Row context: pause/cancel (with confirmations per §12), priority change, open swarm.
- Board channel SSE keeps rows live (04 §5.7 `board` channel): stage and last-activity columns tick in place.
- Empty state (no matters): one explainer line + "Create your first matter" — shown once, not decorated.

## 3. Matter Workspace

Matter header (persistent): reference, title, client, jurisdiction, confidentiality badge (drives display of anything classification-gated), state chip, lead agent, deadline countdown, actions (dispatch, pause, cancel, archive).

Tabs (brief §4 sections; each a route under `/matters/{mid}/…`):

| Tab | Contents | Primary data |
|---|---|---|
| Overview | objectives, key dates, parties summary, current executions, deliverable status | Matter, Party, WorkflowExecution |
| Documents | table: name, origin (upload/ingest/generated), type, version, licence badge, ingest status; upload + ingest actions; document viewer with per-provision anchors | MatterDocument |
| Evidence | verified/unverified filters; each item: text excerpt, locator, source doc link, verification badge, "cited in" artifact links | Evidence |
| Research | the matter's authorities: statute provisions and cases (cites tables), retrieval provenance | Evidence + corpus metadata |
| Work Plan | execution list with task trees; per task: state, agent, dependencies, failure policy | Task |
| Agents | roster on this matter + run history | Agent, AgentRun |
| Swarm | the graph (§4) | AgentRun |
| Drafts | artifacts with version chains and review state; side-by-side version diff | Artifact |
| Decisions | approvals and requests, decided and pending | Approval |
| Activity | timeline (§9) | WorkflowEvent |
| Audit | hash-chained audit events, chain-integrity indicator | AuditEvent |

The header state chip is the single source of matter state; no tab may display a conflicting status.

## 4. Swarm Graph (execution interface)

Interactive SVG/Canvas rendering of the execution's AgentRun tree (edges from `parent_run_id`, sequence from tasks' `depends_on`). Topology is **generated from state**, never hardcoded (brief §3.2).

```text
 EXECUTION exe-221 · legal_pipeline · stage 6/9                    [Pause] [Cancel]
 ─────────────────────────────────────────────────────────────────────────────
   intake/ingestor  ✓2m      research/hunter  ✓9m
                                        │
                        ┌───────────────┼────────────────┐
                 strategy/… ✓6m    attack/adversary ●4m   assess/… ○queued
                                        │
                                 filings/clerk ⏸ awaiting approval ⚑
                                        │
                                  advice/clerk ○        verify/citation ○   close/auditor ○
 ─────────────────────────────────────────────────────────────────────────────
 node = [state colour] agent/stage · duration · token count
```

- Node encodes: agent + task key, state (02 §5 colours/words), duration (live), tokens, error flag, approval flag (⚑ where an Approval parks the graph).
- Parallel branches render side-by-side as dependencies allow — the visual proof of parallelism the TUI could never show.
- Selecting a node opens the **Agent Inspection Panel** (§5) as a right drawer; the graph keeps its place.
- Live updates arrive via the matter SSE channel; nodes animate state changes only (no physics toys).
- Controls: pause/resume/cancel execution (202 → observe, 04 §5.4); zoom/fit; collapse-completed toggle for long runs.
- The intervention actions from the brief (redirect objective, supply evidence, request revision, escalate) live in the inspection drawer and on parked nodes — each is a form posting the 04 §5.4/5.5 endpoints, disabled-with-reason when the state or the viewer's permissions forbid it.

## 5. Agent Inspection Panel

Right-side drawer or full page at `/runs/{rid}`, one section per brief §3.2 requirement:

1. Identity: agent name, role, persona snapshot link (the exact persona md it ran with — 03 §2.10).
2. Objective: task instruction + parent execution link.
3. Dependencies: upstream/downstream tasks.
4. State + state history (validated transitions, 02 §5).
5. Execution timeline: events for this run (`run.started`, `tool.*`, `guard.*`, `turn.completed`…), timestamps both absolute and relative.
6. Tool usage: call, arguments summary, allow/deny result (denied tool calls are first-class rows — the S2 denial regime made visible).
7. Evidence: retrieved passages with verification badges and source links.
8. Output: final summary, artifact links, verbatim turn log link (the JSONL, kept verbatim).
9. Errors & retries: `errors.jsonl` entries + attempt count.
10. Trace summary: dispatch table (provider, model, verified, tokens in/out/thinking, latency) — the TUI's agent table (01 §8) generalized to a per-run view.
11. Actions (permission-gated): interject, cancel, approve if this run requested one.

## 6. Counsel Chat

A work channel, not a chatbot toy (brief §3.3). Layout: conversation thread left, context rail right (current execution stage, latest artifacts, open approvals).

```text
┌ Conversation: Acme v State — supervision ────────────┐ ┌ Context ─────────────┐
│ You 09:12   Compare the two versions of the SSA.     │ │ exe-221 · stage 6/9  │
│ Lead 09:14  Draft comparison prepared → artifact     │ │ filings ⏸ approval   │
│             a-88 (v2). 3 clauses diverge; clause 14  │ │ pending artifacts:   │
│             lacks a counterpart. [E3.S2] [E7.S1]     │ │  a-88 v2 · a-77 v1   │
│ You 09:15   Ask research to verify the two new       │ │ open approvals: 1 ⚑  │
│             authorities before we cite them.         │ │                      │
│ Lead 09:15   → spawned research/hunter (run r-641)   │ │                      │
└──────────────────────────────────────────────────────┘ └──────────────────────┘
│ Type an instruction…            [Send]   (enter sends, shift+enter newline)
```

- Every agent reply carries evidence chips (`[E#.S#]` → Evidence records) and artifact links; unverified assertions are visibly badged — the chat inherits the labelling discipline of §0.
- Sending an instruction creates/extends an execution (04 §5.8): the thread then shows system lines for spawns and state changes, and the same run is inspectable in the swarm.
- Approvals requested by agents surface inline (approval card in-thread, actioning writes the same `POST /approvals/{id}` as the Approval Center) — one decision surface, two views.
- Interjections to a *running* agent go through `runs/{rid}/interject` and are shown as durable "delivered at next boundary" entries — never silently dropped as today's in-memory inject() can be (01 §3.1).

## 7. Approval Center

Global list (`/approvals`) + per-matter Decisions tab. The job: nothing waits invisibly (brief §3.1 requirement).

```text
APPROVALS · 3 pending
──────────────────────────────────────────────────────────────────────────────
 ⚑ m-1077  Acme v State      FILE submission draft     requested 14m ago
   ├ a-88 "Statement of claim — draft v2"   [Open artifact]
   ├ requested by filings/clerk (run r-633)
   └ [Approve]  [Reject]  [Request changes]        (approval.decide required)
 ⚑ m-1077  Acme v State      TOOL external comms …
 ○ m-1042  PPSA …            INFO  needs the 2019 facility agreement …  [Provide]
──────────────────────────────────────────────────────────────────────────────
```

- Each card: matter, kind (filing/external comms/final opinion/client deliverable/strategy change/tool use/info request), the concrete payload (artifact preview, action summary, or the question), requesting run link, age.
- Decide actions require the `approval.decide` permission (04 §5.6); buttons render disabled-with-tooltip otherwise, never hidden (discoverability of governance).
- Decisions are irreversible-by-design → confirm dialog names the consequence; decision + note land in the audit chain.
- The info-request variant ("Waiting on you" for missing evidence/clarification) accepts a text answer or attached documents and un-parks the exact task (03 §2.17).

## 8. Document & Evidence views

- **Documents:** ledger table (§3 tab); click → viewer (PDF/text) with provision anchors for statute ingests; version chain breadcrumb (v3 ← v2 ← v1, `supersedes_doc_id`); licence and source URL shown from the persisted provenance fields (the 01 §7 gap fixed in the data model, surfaced here); ingest status live-updates during ingestion.
- **Evidence:** filter by verified; each record shows excerpt, locator (act/section or case paragraph), source document link, verification method (exact/normalised via quote_check — 01 §7), and reverse links "cited in". This view is the lawyer's answer to "can I trust this?" (brief §8) — it must never show an unverified item without its badge.

## 9. Activity Timeline & Audit

- **Activity** (per matter, and a firm-wide feed): reverse-chronological WorkflowEvents, grouped by execution; filters by type (state changes, guard annotations, errors, approvals); each entry links to its run/task/approval. Guard annotations (`[UNGROUNDED]`, `[UNQUOTED]`) appear here as well as inline — detection is visible even when the guard is set to annotate-only.
- **Audit:** append-only chain view; shows chain integrity (verified/⚠ broken) computed client-side from the hash chain (03 §2.19); admin/auditor permission. No edit affordances exist at all.

## 10. Loading, error, and empty states

| Situation | Behaviour |
|---|---|
| Route data loading | skeleton rows for tables; spinner only where no layout exists yet; ≤300 ms responses render without spinner flash |
| SSE disconnected | header status dot → amber "reconnecting"; rows keep last values with a stale marker; reconnect resumes via `Last-Event-ID` (04 §5.7) |
| Command accepted (202) | optimistic state labelled "pending…" until the confirming event arrives — the UI never shows success before the backend confirms (brief §3.2) |
| Command rejected | inline error with the stable code's message (`invalid_transition` explains the legal moves); no toast-only errors |
| Execution failed | matter state Failed + the failing task's error ledger surfaced in Work Plan and the timeline, with the recorded context (01 §5 errors.jsonl fields) |
| Empty collections | one-line explainer + the single action that fills them (no illustrations, no marketing) |
| Provider outage | dispatch returns a typed error; board shows matter Blocked with provider status from `/healthz` |

## 11. Responsive behaviour

- **Primary target: desktop ≥1280 px.** Three-column minimum for Workspace + Swarm + drawer layouts.
- **Laptop 1024–1279:** left rail collapses to icons; inspection drawer overlays instead of splitting.
- **Tablet/mobile:** read-only triage mode — Board, Approvals (decide actions stay enabled), Activity. Swarm graph degrades to a task list. Editing flows (matter metadata, workflow authoring) are desktop-only and hidden, not broken.
- Print stylesheet for artifacts and evidence bundles (couriers still want paper).

## 12. Permission-dependent interactions

Enforcement is server-side (04 §3); the UI's obligation is honest affordance:

| No permission | Render as |
|---|---|
| `approval.decide` | Approve/Reject disabled with tooltip "requires approval.decide" |
| `matter.dispatch` | Dispatch/pause/cancel hidden; board rows remain readable |
| `matter.cross_read` | No cross-matter affordance exists at all |
| `audit.read` | Audit tab shows a lock row, not the data |
| read-only role | All mutation controls hidden; document download per matter policy |

Never show an enabled control that will fail, and never hide the *reason* a lawyer can't act — governance must be discoverable (brief §9 posture).

## 13. Interaction details worth keeping from the TUI

The terminal shell got some things right (01 §8); the web client should keep the muscle memory:

- Keyboard-first: `⌘K` palette, `Enter` sends in chat, `Esc` closes drawer, `j/k` table navigation.
- Copy-anywhere: the TUI's ctrl+o clipboard dump becomes per-block copy buttons + selection-native copy.
- The **agent table's information model** — agent, stage, provider, model, verified flag, tokens in/out/thinking, guard annotation count — is preserved verbatim as the run inspection's trace summary (§5.10); it was the TUI's best screen and no abstraction should blur it.
- The token meter: per-matter token budget read from trace joins, shown in the workspace header (same computation as `tokens.py`, now via the API).

## 14. Design sign-off gate

Per the owner's standing instruction (2026-11-04): **before any screen is implemented**, the owner reviews and picks the concrete visual design (this document's ASCII specs are layout contracts, not the final visual design). The implementation phase opens with 2–3 high-fidelity mockups of the Matter Board and Swarm (the two defining screens) presented for selection, and each subsequent screen follows the chosen system. No screen is built ahead of that pick.

## 15. Out of scope for v1

Named so they aren't accidentally built: client-facing portals, mobile-native apps, collaborative multi-cursor editing, notification email/SMTP integration, theming beyond light/dark, i18n beyond en-NZ conventions (dates `14 Nov 2026`), custom dashboards/widgets.
