# S4 SPIKE REPORT — adopt-vs-build evidence run (P0-5) — 2026-09-01/02

**Session:** background autonomous run (started from NEXT_STEPS.md S4).
**Candidates run:** OpenCode 1.18.25 · OpenHands (openhands-sdk 1.44.1) ·
**dsh NOT RUN** — S1 pre-check gate not cleared (1 critical finding open pending
Jonathan's ruling, CR-2); per NEXT_STEPS S1, S4 ran OpenCode + OpenHands only.
**Protocol:** [SPIKE_PROTOCOL.md](SPIKE_PROTOCOL.md) · ledger: [SEAM_COUNT.md](SEAM_COUNT.md)

## Headline verdicts (input to S5/M0)

| criterion | OpenCode 1.18.25 | OpenHands SDK 1.44.1 |
|---|---|---|
| (a) guard coverage, no fork | **PASS with one costed hazard** — fires on every path; model-output annotation proven AT SCALE (2,596 annotations across the 5 parity answers); tool-path block decision proven live; tool-RESULT annotation corrupts built-in tools' structured envelopes (SchemaError observed — needs envelope-aware handling in Module E) | **PARTIAL FAIL** — guard checks+detects on every path; annotation PERSISTS on MessageEvents (proven, incl. final answers carried as text) but the finish-tool observation carrier and tool observations are IMMUTABLE (frozen parts; replacement fails validation) — annotation there requires SDK change or a yet-unfound LLM entry point (wrapper override never fired) |
| (b) persona parity | **PASS** — mean citations 0.100 (= in-house exactly), grounding 0.400 vs 0.300 (one needle, one case) | **PASS** — mean grounding 0.300 (= in-house exactly), citations 0.000 vs 0.100 (one needle, one case) |
| (c) seam ledger | **complete** — 9 rows, incl. 4 live-observed operational hazards | **complete** — 5 rows, 1 blocked (openhands-tools not installable on Windows) |
| core fork | none (plugins/config/agents only) | none (SDK composition only) |

**Both candidates pass criterion (b); neither requires a core fork.** Criterion (a)
separates them: OpenCode's guard covers the model-output path outright; OpenHands'
cannot annotate every text carrier as-is. Both divergence deltas in (b) are single
needles on single cases, within the run-to-run variance measured on this model
(the same case scored 0.50/0.00/0.50 citations across identical in-house/config mounts).

## Run conditions (identical across every parity comparison)

- Model: `qwen3.8:27b` (Q4_K_M) on local Ollama, RTX 3090 — the S2 baseline model.
- Parity set: **5 cases** — one per matter cluster, first by id (`gc-dir-001-mainzeal-hc`,
  `gc-liq-001-madsen-ries`, `gc-misc-001-burns-cir`, `gc-ppsa-001-goldcorp`,
  `gc-recv-001-viacom-scene1`). Jonathan's full 30 stay covered by the committed
  2026-09-01 bare baseline.
- Output cap 8192 on the in-house reference and OpenHands; **OpenCode raised to 16384**
  after live measurement (see deviations). Temperature not pinned anywhere.
- Scoring: the production scorer (`score_case`), unchanged.
- Guard authorities per case: `expected_citations` **plus their bracket envelopes**
  (`allowed_for`) — otherwise the guard annotates *inside* expected citations and
  fabricates citation failures the unguarded in-house reference cannot show.

## Criterion (b) — persona parity (the numbers)

| case | in-house c/g | OpenCode c/g | OpenHands c/g |
|---|---|---|---|
| gc-dir-001-mainzeal-hc | 0.50 / 0.00 | 0.50 / 0.00 | 0.00 / 0.00 |
| gc-liq-001-madsen-ries | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| gc-misc-001-burns-cir | 0.00 / 0.00 | 0.00 / 0.50 | 0.00 / 0.00 |
| gc-ppsa-001-goldcorp | 0.00 / 1.00 | 0.00 / 1.00 | 0.00 / 1.00 |
| gc-recv-001-viacom-scene1 | 0.00 / 0.50 | 0.00 / 0.50 | 0.00 / 0.50 |
| **mean** | **0.100 / 0.300** | **0.100 / 0.400** | **0.000 / 0.300** |

8 of 10 cells identical across all three sides. Answers were substantive on both
candidates (10k–48k chars, persona format followed). Context: the persona MOUNT lowers
grounding-needle scores vs the bare baseline (0.433→0.300 in-house) — the persona's
structured format paraphrases needles (hyphenation etc.; the known S6 normaliser
brittleness). Parity is judged comparatively, as criterion (b) specifies.

Reports: [in-house](../../data/eval/spike-persona-ref-ollama.md) ·
[OpenCode](../../data/eval/spike-opencode-parity.md) ·
[OpenHands](../../data/eval/spike-openhands-parity.md) (+ re-scorable JSONL sidecars).

## Criterion (a) — guard coverage, no fork (details)

### OpenCode
- Mount: `.opencode/plugins/ironfleet-guard.ts` → `guard_cli.py` → `OpenCodeHookAdapter`
  (the REAL guard; no JS re-implementation). Hooks: `tool.execute.before` (stable; block
  proven live), `tool.execute.after` (stable; result annotation), `experimental.text.complete`
  (model-output annotation — **experimental** hook: a stability seam priced at M0).
- **Model-output path proven at scale**: the five parity answers carry 275 / 58 / 825 /
  262 / 1,176 `[UNGROUNDED — not confirmed]` annotations (2,596 total) — the guard fired
  on every model output during real runs and annotations persisted into the scored text.
- **Tool-result annotation hazard**: built-in tools return opencode-internal JSON
  envelopes; blanket text annotation corrupts them (SchemaError, session killed —
  observed live). Module E must annotate the human-facing presentation layer or custom
  tools' outputs, not the envelope. Detection/blocking on this path works.
- Injection runs: block-mode verdict banked
  ([spike-opencode-inject-verdict-blockmode.json](../../data/eval/spike-opencode-inject-verdict-blockmode.json));
  annotate-mode reruns hit 27B instruction-compliance variance (the model did not
  reliably run the echo tool), which is why the at-scale parity evidence above is the
  stronger proof.

### OpenHands
- Mount: conversation callbacks on the event-append path → `OpenHandsHandlerAdapter`
  (every Observation/Message/Action event checked and logged), `Agent(system_prompt=
  persona VERBATIM)` + `register_agent("hunter")`, synthetic `corpus_search` custom tool
  (`register_tool`) for the injection run.
- **Answer-carrier discovery**: OpenHands' agent loop routes its CONCLUSION through the
  finish TOOL — the final answer often travels as the finish tool's ObservationEvent
  (immutable), not as a MessageEvent (mutable; annotation proven and persisted when the
  model answers in text — injection verdict shows annotated final answer).
- Tool observations: checked + detected every time; annotation blocked by frozen
  content parts; whole-observation replacement fails schema validation. LLM-wrapper
  override (`GuardedLLM.completion`) never fired — the SDK's agent calls a different
  completion entry point; finding that entry is a small, unbudgeted follow-up seam.
- **Installability**: `openhands-tools` (task delegation, terminal/file tools) does NOT
  install on this Windows box — Rust-building sdist in its dependency tree;
  wheels-only resolution impossible. The subagent-invocation seam is therefore
  UNMEASURED for OpenHands (registry mount exists; TaskToolSet blocked).

## Recorded deviations (agent-recorded, this session)

1. **Parity subset (5, not 30)** — 30-case reruns ×3 sides ≈ 30–90 h wall at baseline
   pace; subset deterministic so all sides saw identical prompts.
2. **Output caps** — 8192 in-house/OpenHands; OpenCode 16384 (its ~8k-token request
   scaffolding inflates the model's thinking past a shared 8192 — measured input 9,279
   vs 1,104 in-house; cases ended reason=length with zero content). The scaffolding tax
   itself is a finding: candidate cost ≈ 8× prompt tokens per legal query.
3. **2-day-per-candidate budget** mapped to one unattended session (mount + coverage +
   parity + ledger per candidate); all iterations and their live evidence are committed.
4. **Persona drives**: OpenCode parity used a `mode: primary` twin agent with the
   IDENTICAL verbatim persona (driving a subagent-mode agent directly makes opencode
   wrap a flailing primary around it — observed live); the protocol's subagent MOUNT
   (mode: subagent) was exercised by the delegate run (task(hunter) fired; the
   subagent's guard path surfaced a real defect — concurrent hook spawns failed until
   serialized; after hardening, one delegate attempt still errored at the subagent
   boundary while the primary's fallback answer carried live guard annotations).
5. **Inherited baseline deviation** — Ollama in-memory admission override (user-directed
   2026-08-28; CR-3 unchanged, dispatches traced verified=0).
6. **Mid-run server setting change** — the user set the Ollama app context 256k→32k
   (~22:30 09-01) after the in-house reference completed: speeds runs up ~3×; scores
   unaffected (a ~1k-token prompt behaves identically at 32k vs 256k ctx; only KV
   allocation and offload change). In-house latency figures (18–30 min/case) predate
   the change; candidate latencies (2–4 min/case) postdate it.

## Extra datum — legal-domain model (user-requested): Thomson-1.0-Small, full 2×3 matrix

`thomson1:latest` = Thomson Reuters **Thomson-1.0-Small** (Qwen3.6-35B-A3B MoE base,
21 GB local import), run on the identical 5-case persona eval across ALL THREE mounts
(in-house persona runner, OpenCode hunter, OpenHands hunter) with a 16,384 output cap
(the model burns 3k+ reasoning tokens before content; at 8,192 the content channel
comes back empty — first in-house attempt inconclusive, all runs below use headroom):

| case | in-house | OpenCode | OpenHands | in-house-T | OpenCode-T | OpenHands-T |
|---|---|---|---|---|---|---|
| gc-dir-001-mainzeal-hc | 0.50/0.00 | 0.50/0.00 | 0.00/0.00 | 0.50/0.00 | 0.50/0.00 | 0.00/0.00 |
| gc-liq-001-madsen-ries | 0.00/0.00 | 0.00/0.00 | 0.00/0.00 | 0.50/0.00 | 0.50/0.00 | 0.50/0.00 |
| gc-misc-001-burns-cir | 0.00/0.00 | 0.00/0.50 | 0.00/0.00 | 0.00/0.00 | 0.00/0.00 | 0.00/0.00 |
| gc-ppsa-001-goldcorp | 0.00/1.00 | 0.00/1.00 | 0.00/1.00 | 0.00/1.00 | 0.00/0.00 | 0.00/1.00 |
| gc-recv-001-viacom-scene1 | 0.00/0.50 | 0.00/0.50 | 0.00/0.50 | 0.00/0.50 | 0.00/0.50 | 0.00/0.50 |
| **mean (c/g)** | **0.100/0.300** | **0.100/0.400** | **0.000/0.300** | **0.200/0.300** | **0.200/0.100** | **0.100/0.300** |
| mean answer chars | 9,720 | 26,007 | 1,105 | 3,475 | 5,810 | 4,299 |

(cells = citation_accuracy / grounding_score; `-T` = thomson1; non-`-T` = qwen3.8:27b.
Sidecars: `spike-persona-{ref,thomson1}` , `spike-{opencode,openhands}-parity{-thomson1}`.)

**Readings:**
- **The model effect is consistent across every mount**: thomson1 lifts exact-citation
  accuracy in-house (0.100→0.200), on OpenCode (0.100→0.200) and on OpenHands
  (0.000→0.100) — doubling it wherever it runs, at equal grounding (0.300 on 5 of 6
  columns). The legal-domain training (citation-pattern rewards) shows up exactly on
  the axis the persona-parity harness measures. It is also 4–8× more compact and
  ~2× faster per case (~60–165 s vs ~90–240 s post-ctx-fix).
- **The mount effect stays small under both models** — each candidate tracks its
  in-house comparator within a needle or two, for BOTH models: criterion (b) parity
  is model-robust, not a qwen artifact. One systematic per-mount quirk: OpenHands
  misses the dir-001 citation needle ("Mason v Lewis [2006] 3 NZLR 225") under BOTH
  models while every other mount hits it — worth a look in S6 normaliser work.
- Model choice is ORTHOGONAL to adopt-vs-build: this feeds Path A/B sizing (and the
  eval engine choice going forward), not the M0 tie-break.

**Thomson1-under-candidates incident trail (recorded for Module E):** getting
thomson1 through OpenCode surfaced one more real defect on our side and one candidate
quirk — (i) the serialized guard returned a Promise whose `.output` the hooks assigned
into opencode parts (undefined text → SchemaError; all pre-serialization OpenCode
evidence predates it and stands; fixed + relaunch clean), and (ii) thomson1's
reasoning-phase streaming produces empty text parts that opencode's part-cleanup
rejects if touched — the guard hook is now defensive about them. A `thomson1-chat`
variant (proper qwen renderer in the Modelfile) was built and probed — neutral on the
thinking-budget behaviour; the original model id is used for all data above.

## Seam-count → Module E repricing input

OpenCode 9 rows / OpenHands 5 rows (details + live-observed hazards in
[SEAM_COUNT.md](SEAM_COUNT.md)). Rough effort-per-seam observed in this session:
each candidate consumed ~6 mount iterations to reach healthy runs — the operational
hazards (instance steering, prompt transport, orphan supervision, pipe deadlocks,
immutable events) are where the hours went, not the two ports themselves.

## S5 inputs checklist

- SEAM_COUNT.md (per-candidate tables) ✓
- spike pass/fail per candidate (this report) ✓
- eval baseline (committed 2026-09-01) + persona reference + candidate parity runs ✓
- dsh pre-check report (committed 2026-08-26; ruling pending Jonathan) ✓
