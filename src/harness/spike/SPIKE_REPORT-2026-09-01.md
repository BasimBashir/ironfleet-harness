# S4 SPIKE REPORT — adopt-vs-build evidence run (P0-5) — 2026-09-01

**Session:** background autonomous run (started from NEXT_STEPS.md S4).
**Candidates run:** OpenCode 1.18.25 · OpenHands (openhands-sdk 1.44.1) ·
**dsh NOT RUN** — S1 pre-check gate not cleared (1 critical finding open pending
Jonathan's ruling, CR-2); per NEXT_STEPS S1, S4 ran OpenCode + OpenHands only.
**Protocol:** [SPIKE_PROTOCOL.md](SPIKE_PROTOCOL.md) · ledger: [SEAM_COUNT.md](SEAM_COUNT.md)

## Run conditions (identical across every parity comparison)

- Model: `qwen3.8:27b` (Q4_K_M) on local Ollama, RTX 3090 — the S2 baseline model.
- Parity set: **5 cases** — one per matter cluster, first by id (`gc-dir-001-mainzeal-hc`,
  `gc-liq-001-madsen-ries`, `gc-misc-001-burns-cir`, `gc-ppsa-001-goldcorp`,
  `gc-recv-001-viacom-scene1`). Jonathan's full 30 stay covered by the committed
  2026-09-01 bare baseline.
- Output cap 8192 on BOTH sides of every comparison (in-house reference, OpenCode,
  OpenHands). Temperature not pinned anywhere (server default in-house; candidate
  default on their side) — recorded, unresolvable without touching frozen gate code.
- Scoring: the production scorer (`score_case`), unchanged.
- Allowed-authorities for the mounted guard: per-case `expected_citations` **plus their
  bracket envelopes** — otherwise the guard annotates *inside* expected citations
  (`[2006]` in `Mason v Lewis [2006] 3 NZLR 225`), breaking the scorer's exact-substring
  needles and fabricating citation failures the unguarded in-house reference cannot
  show. Adapter untouched; list-construction only (`run_spike_opencode.allowed_for`).

## Recorded deviations (agent-recorded, this session)

1. **Parity subset (5, not 30).** Baseline pace ~4.3 tok/s (18–61 min/case; measured):
   30-case runs × 3 sides ≈ 30–90 h wall — infeasible for one session. The subset is
   deterministic (first-by-id per cluster) so all three sides saw identical prompts.
2. **max_tokens capped 8192** (baseline used the 128k gate default). Identical on both
   sides of every comparison; absolute numbers NOT comparable to the 128k baseline
   (which produced 4.7k–13.6k-token answers). One in-house case (misc-001) hit the cap.
3. **2-day-per-candidate budget mapped to agent wall-clock.** Mount + coverage + parity
   completed in-session; the human 2-day budget was for interactive work, not a
   constraint on unattended runs.
4. **Parity runs executed concurrently** against one Ollama instance (requests queue):
   halves wall-clock, inflates per-case latency numbers on both sides. Latency is
   reported, not a pass criterion; scores unaffected.
5. **Inherited baseline deviation** (user-directed 2026-08-28): in-memory admission
   override for Ollama (CR-3 unchanged, every dispatch traced `verified=0`) — applies
   to the in-house persona reference the same way it applied to the baseline.

## Reference: in-house HUNTER persona (criterion (b) comparator)

Runner: [`scripts/run_eval_persona_ollama.py`](../../scripts/run_eval_persona_ollama.py)
(persona verbatim as system message through the production gate path).
Report: [`data/eval/spike-persona-ref-ollama.md`](../../data/eval/spike-persona-ref-ollama.md)

| case | citations | grounding | checks |
|---|---|---|---|
| gc-dir-001-mainzeal-hc | 0.50 | 0.00 | 1/1 |
| gc-liq-001-madsen-ries | 0.00 | 0.00 | 0/1 |
| gc-misc-001-burns-cir | 0.00 | 0.00 | 0/1 |
| gc-ppsa-001-goldcorp | 0.00 | 1.00 | 1/1 |
| gc-recv-001-viacom-scene1 | 0.00 | 0.50 | 0/1 |
| **mean** | **0.100** | **0.300** | 0/5 passed |

Context: the persona MOUNT lowers grounding-needle scores vs the bare baseline
(30-case means: 0.017 / 0.433) — the persona's structured format paraphrases needles
(hyphenation, "balance-sheet insolvent" vs "balance sheet insolvent"). This is the
known S6 normaliser brittleness, now measured on the persona side too. Parity is
therefore judged comparatively (candidate-persona vs in-house-persona), which is what
criterion (b) specifies.

## Criterion (a) — guard coverage, no fork

### OpenCode — PASS/FAIL: _(pending injection run)_
- Mount: plugin `.opencode/plugins/ironfleet-guard.ts` calling the real guard via
  `guard_cli.py`; hooks `tool.execute.before` (block decision), `tool.execute.after`
  (tool-result annotation) — **stable** — and `experimental.text.complete`
  (model-output annotation) — **experimental hook**; fired live in `opencode run`
  (guard log shows `text.complete` checked on a smoke run).
- Injection run (`[Imaginary Act 2026, s 9]` through a real tool call + model answer):
  _(pending)_
- Core fork: none — plugins/config/agent files only.

### OpenHands — PASS/FAIL: _(pending injection run)_
- Mount: conversation callback on the event-append path driving
  `OpenHandsHandlerAdapter`; ObservationEvent (tool results) and MessageEvent
  (assistant output) checked in place; every check logged. Smoke run: both
  MessageEvents checked live; extraction working.
- Injection run (synthetic `corpus_search` tool — the Module-E-shaped retrieval tool —
  returns `[Imaginary Act 2026, s 9]`): _(pending)_
- Core fork: none — SDK composition only (register_agent, register_tool, callbacks).
  **Blocked seam:** task-delegation (`TaskToolSet`) requires `openhands-tools`, which
  does NOT install on this Windows box (Rust-building sdist in its dependency tree;
  wheels-only → ResolutionImpossible). Subagent invocation seam unmeasurable here —
  an M0 installability datum, not a guard failure.

## Criterion (b) — persona parity

| side | mean citations | mean grounding | passed |
|---|---|---|---|
| in-house HUNTER (reference) | 0.100 | 0.300 | 0/5 |
| OpenCode hunter subagent | _(pending)_ | _(pending)_ | _(pending)_ |
| OpenHands hunter agent | _(pending)_ | _(pending)_ | _(pending)_ |

Parity judgement: same scorer, same prompts, same model, same cap. Candidate parity
holds if its means track the in-house reference (they are all on the same floor);
material divergence would indicate the mount changes model behaviour (e.g. candidate
scaffolding leaking into answers).

## Criterion (c) — seam ledger

[SEAM_COUNT.md](SEAM_COUNT.md) — OpenCode 7 rows (+1 pending delegate run),
OpenHands 4 rows (1 blocked), dsh not run. Live-observed hazards recorded per row.

## Extra datum — legal-domain model (user-requested)

`thomson1:latest` (21 GB, installed in Ollama 2026-09-01) vs `qwen3.8:27b` on the
identical 5-case persona eval: _(pending run)_ — model choice is orthogonal to the
adopt-vs-build question but feeds S5/M0 context and Path A/B sizing.

## Verdict per candidate (for S5/M0)

_(pending all runs)_
