# SEAM COUNT — spike integration-point ledger

> **"Seam"** = one integration point where IronFleet behaviour attaches to the adopted
> harness WITHOUT touching its core: a hook registration, plugin entry, config file, or
> subagent manifest. Each row is a thing Module E (A-2/B-5) must build and maintain.
>
> **How the count reprices Module E:** Module E is priced at 48h assuming a fixed number
> of attachment points. Actual seam count × observed effort-per-seam from the spike
> replaces that estimate: `Module E (repriced) = seams × median-hours-per-seam observed
> in the 2-day run`, with each `core-fork? = yes` row additionally pricing the ongoing
> fork-maintenance burden (tracked in the M0 tie-break, CR-2a). Record rows during the
> run, not after.
>
> **Run context (2026-09-01, background S4 session):** parity material = the 5-case
> parity subset (one per matter cluster, first by id: dir-001, liq-001, misc-001,
> ppsa-001, recv-001), model `qwen3.8:27b` on local Ollama, output cap 8192 on BOTH
> sides of every comparison; in-house comparator = `scripts/run_eval_persona_ollama.py`
> (persona system message through the production gate path). Deviations recorded in the
> S4 spike report.

## OpenCode (1.18.25, pinned via npm `opencode-ai`)

| seam | file/hook touched | core-fork? |
|---|---|---|
| guard hook — tool path (result annotation) | `.opencode/plugins/ironfleet-guard.ts` → `tool.execute.after` (stable hook) → `guard_cli.py` → `OpenCodeHookAdapter` | no |
| guard hook — tool path (block decision) | same plugin → `tool.execute.before` (stable; throw = block) | no |
| guard hook — model-output path | same plugin → `experimental.text.complete` (**experimental** hook in 1.18.25 — fires live in `opencode run`; stability risk priced at M0) | no |
| persona subagent | `.opencode/agent/hunter.md` (mode: subagent; body = PERSONA_PORT verbatim, driver-generated) + `--agent hunter` direct drive | no |
| provider wiring | `opencode.json` custom provider `ollama-local` (npm `@ai-sdk/openai-compatible`, auto-installed into `~/.config/opencode`); provider id must NOT collide with builtin `ollama` (cloud) | no |
| workspace isolation | workspace must be its own git repo, else opencode adopts a sibling repo's instance; driver must scrub inherited `PWD` env (steers instance resolution) — both observed live | no |
| subagent invocation via task delegation | primary agent → task(hunter) | no (pending delegate run) |

## OpenHands (openhands-sdk 1.44.1, pinned; **openhands-tools NOT installable on this Windows box** — Rust-building sdist in dep tree, wheels-only ResolutionImpossible)

| seam | file/hook touched | core-fork? |
|---|---|---|
| guard — conversation callback on event-append path (ObservationEvent = tool results, MessageEvent = assistant output) | `scripts/run_spike_openhands.py` callbacks → `OpenHandsHandlerAdapter` (annotate-in-place; event immutability is the open empirical question — smoke) | no (pending smoke) |
| persona subagent | `Agent(system_prompt=PERSONA_PORT verbatim)` + `register_agent("hunter", …)` registry mount | no |
| task delegation (subagent invocation) | `TaskToolSet` lives in `openhands-tools` → **blocked: package unresolvable on Windows** (installability datum for M0) | n/a — blocked |
| LLM wiring | litellm model `openai/qwen3.8:27b` + base_url → Ollama /v1; SDK-only install path exists (no Docker needed for tools=[] agents) | no |

## dsh
_(runs only after the P0-6 pre-check clears — **gate NOT cleared as-measured 2026-08-26;
single critical finding open pending Jonathan's ruling (CR-2). Not run in this session;
S4 proceeded with OpenCode + OpenHands only, per NEXT_STEPS S1.)_

| seam | file/hook touched | core-fork? |
|---|---|---|
| _(guard plugin: …)_ | `plugins/ironfleet-…/guard.ts` on tools/post-execute | |
| _(persona subagent: …)_ | `plugins/…/manifest.json` | |
