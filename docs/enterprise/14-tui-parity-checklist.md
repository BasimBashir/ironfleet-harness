# 14 — TUI parity checklist (06 Phase 6 · owner gate 02 §16.8)

**Date:** 2026-11-09 · **For:** the owner's decision to retire `src/harness/session/tui.py` +
`scripts/tui.py` (06 Phase 6: "TUI deleted only after the owner confirms parity on real work").
**Method:** every capability of the TUI (its bindings, slash commands, panes and entry flags,
read from the code) mapped to the M8 web client (`web/`, served by `create_app`) — **carried**,
**partial**, or **not carried, why**. Each "carried" row was exercised in the browser by
`tests/test_web_e2e.py`, `tests/test_web_a11y.py` or the smokes named in the M8 plan.

**Bottom line:** the web client carries the matter, document, approval, run-inspection and
lifecycle surfaces the TUI never had, but it **cannot yet run a live crew** — the served worker
runs the named harbour-freight demo body; the production body (opencode behind the gate) is the
optional live leg (M8 plan §3). Until that leg exists, the TUI is still the only way to run real
agent work, so **retiring it now would remove the ability to do real work.**

## Entry and session

| TUI capability | Web | Status |
|---|---|---|
| `scripts/tui.py --new --matter <ref>` — start a session on a matter | New matter (`#/new`, firm) / Start a case (self-rep) | carried |
| `--session <id\|last>` — resume | Board, rail "Recent matters", ⌘K search → workspace or case home | carried |
| `open_gate()` for the app's lifetime (live turns reach providers) | none — the API runs no gate; the demo worker needs none | **not carried** — belongs with the live leg |
| provider fixed to `nvidia-nim` in the entry script | none | **not carried** — provider choice is routing config; no UI in M8 |

## Prompt line and slash commands

| TUI capability | Web | Status |
|---|---|---|
| type a goal → the legal pipeline runs (10 stages, moot gate, filing approval) | Workspace → Overview → "Dispatch work" (`POST /matters/{mid}/executions`) | **partial** — the same plan compiles and the M6 filing guard is enforced, but stages run the **demo body**, not agents |
| follow-up continues from the last checkpoint (session digest seeded) | dispatch again | **partial** — a new execution starts; the API does not seed the previous runs' digest (`executions.create` has no digest input) |
| `/plan <file>` — kickoff from a file with a ```` ```plan ```` block | none (the API accepts `plan_block`, the form sends only `task_text`) | **not carried** — add a "scripted plan" field to Dispatch when the live leg lands |
| `/ingest <path>` — ingest law sources into the matter corpus + report lines | Workspace → Documents → "Ingest operator-supplied law sources" | carried — the report (ingested / skipped / already in corpus / chunks) is shown since this pass; it was discarded before |
| `/mode`, `/mode <name>`, **shift+TAB** — runner mode (agent-os / shell-drives / hybrid) | none | **not carried** — mode selects the live runner; the served worker has one body. Decide with the live leg whether mode survives |
| `/doctor` — one-screen health report | header "● Live" (SSE health) only; API has `/healthz`, no doctor route | **not carried** — needs a `GET /system/doctor` route (API change) |
| `/provider` — the provider registry | none (no providers route) | **not carried** — Settings → Providers is in mockup B's rail; not M8 scope |
| `/persona new name\|description\|tools\|prompt` | none (API has `POST /agents`, no screen) | **not carried** — agent/persona management screen not in M8 scope |
| `/compact` + auto-compact past the meter's safe fill | none | **not carried** — compaction is the live runner's concern; returns with the live leg |

## Panes

| TUI pane | Web | Status |
|---|---|---|
| Chat (the record of what was asked + answers, follows the tail) | Activity tab (timeline, newest first) + Work plan run drawer | **partial** — conversational chat with lead counsel is M10 (`/conversations` API exists, screen M10) |
| Jobs (the session's jobs table, live spinner) | Workspace → Work plan (executions table) + run drawer / run page (stages, states, summaries) | carried — and adds pause / resume / cancel / redirect / interject, which the TUI never had |
| Agents (per-agent status from the trace, guard-log count) | Workspace → Agents (tokens by agent: in / out / thinking / calls) | **partial** — no guard-log (guard annotation) count per agent |
| Docs (active stage workspace: changed files as links + git diff) | Workspace → Drafts (artifacts, view/download, "Mark reviewed") | **partial** — artifacts are carried; the live git diff of a stage workspace is not |
| deliverable announcements (clickable, opens in the OS) | Drafts tab + document viewer with download | carried |
| Corpus (ingested docs with words and chunks) | Documents tab (uploads + ingest status) + Evidence tab | **partial** — per-document word/chunk counts of the law corpus are not shown |
| Thinking (each turn's reasoning text) | thinking **token counts** in the run drawer and Agents tab | **not carried** — the reasoning text needs a run-events route; M10 inspection drawer |
| status bar: mode · session · tokens used / window (%) | header token meter (matter total) | **partial** — no context-window / budget denominator (no budget field in the API) |

## Keys and safety behaviour

| TUI capability | Web | Status |
|---|---|---|
| ctrl+o — copy the chat to the clipboard | text is selectable/copyable natively | carried (platform) |
| ctrl+q is the only quit; ctrl+c trapped so a mis-key can't kill a stage | runs live in the server's worker: closing the tab stops nothing | carried, stronger |
| errors recorded to `errors.jsonl`, echoed in the chat | inline error lines with retry; API error envelope with `trace_id` | carried |

## What the web adds that the TUI never had

Matter board with state, stage, approvals, due date, lawyer-now and tokens · approval centre
(approve / reject / answer requests, confirmation of the consequence) · document upload and viewer
· evidence browser · audit chain · case lifecycle (stage moves, deadlines, strategy versions and
diffs, predictions, debrief, hearing pack) · the whole guided self-represented journey (N1–N10)
with the lawyer-now block · light/dark and plain/legal reading level · keyboard palette (⌘K).

## Found while writing this

- The ingest service returned an empty report (nothing ingested, nothing skipped) for a directory
  holding one short `.txt` file, although `.txt` is a supported type — a silent drop in the
  ingester (`harness.ingest_generic`), outside M8. The web now says "nothing in that source was a
  file this ingester reads" instead of showing an empty list.

## Before the TUI can go

1. The live leg: the served worker runs the production body (opencode behind the gate), with the
   gate opened by the API process — this closes the five "not carried — live leg" rows.
2. Decide per row above: carry (`/plan` field, doctor route, providers screen, persona screen,
   thinking text, guard counts, digest seeding) or drop with a reason.
3. The owner runs real work through the web for a period and signs below.

**Owner sign-off — parity confirmed on real work, TUI may be deleted (its own commit):**

Name: ______________________  Date: ____________  Matters used: ______________________
