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

## OpenCode (1.18.25, pinned via npm `opencode-ai`) — verdict: (a) PASS w/ 1 costed hazard, (b) PASS, no fork

| seam | file/hook touched | core-fork? |
|---|---|---|
| guard hook — tool path (result annotation) | `.opencode/plugins/ironfleet-guard.ts` → `tool.execute.after` (stable hook) → `guard_cli.py` → `OpenCodeHookAdapter` | no |
| guard hook — tool path (block decision) | same plugin → `tool.execute.before` (stable; throw = block) | no |
| guard hook — model-output path | same plugin → `experimental.text.complete` (**experimental** hook in 1.18.25 — fires live in `opencode run`; stability risk priced at M0) | no |
| persona subagent | `.opencode/agent/hunter.md` (mode: subagent; body = PERSONA_PORT verbatim, driver-generated) + `--agent hunter` direct drive | no |
| provider wiring | `opencode.json` custom provider `ollama-local` (npm `@ai-sdk/openai-compatible`, auto-installed into `~/.config/opencode`); provider id must NOT collide with builtin `ollama` (cloud) | no |
| workspace isolation | workspace must be its own git repo, else opencode adopts a sibling repo's instance; driver must scrub inherited `PWD` env (steers instance resolution) — both observed live | no |
| CLI prompt transport | `opencode run` via cmd.exe TRUNCATES the message at the first newline — multi-line prompts must be flattened (observed live: hunter answered "your message looks cut off") | no |
| run supervision (Windows) | killing the direct child (cmd.exe) orphans opencode.exe holding the stdout pipe — driver hangs despite subprocess timeouts; needs tree-kill (`taskkill /T /F`) supervision — observed live | no |
| subagent invocation via task delegation | primary agent → task(hunter) | no (pending delegate run) |

## OpenHands (openhands-sdk 1.44.1, pinned; **openhands-tools NOT installable on this Windows box** — Rust-building sdist in dep tree, wheels-only ResolutionImpossible) — verdict: (a) PARTIAL FAIL (detection everywhere; annotation blocked on immutable finish-observation/tool carriers), (b) PASS, no fork

| seam | file/hook touched | core-fork? |
|---|---|---|
| guard — conversation callback on event-append path (ObservationEvent = tool results, MessageEvent = assistant output, ActionEvent = model-authored tool arguments — the agent loop routes its CONCLUSION through the finish tool, so the finish ObservationEvent IS the final-answer carrier, observed live) | `scripts/run_spike_openhands.py` callbacks → `OpenHandsHandlerAdapter` (annotate-in-place) | no (write-back verdict pending chain) |
| persona subagent | `Agent(system_prompt=PERSONA_PORT verbatim)` + `register_agent("hunter", …)` registry mount | no |
| task delegation (subagent invocation) | `TaskToolSet` lives in `openhands-tools` → **blocked: package unresolvable on Windows** (installability datum for M0) | n/a — blocked |
| LLM wiring | litellm model `openai/qwen3.8:27b` + base_url → Ollama /v1; SDK-only install path exists (no Docker needed for tools=[] agents) | no |

## dsh
_(runs only after the P0-6 pre-check clears — **gate NOT cleared as-measured 2026-08-26;
single critical finding open pending Jonathan's ruling (CR-2). Not run in this session;
S4 proceeded with OpenCode + OpenHands only, per NEXT_STEPS S1. 2026-09-03: ruling closed MOOT
by the M0 decision — dsh exits the programme unless deliberately reopened.)_

| seam | file/hook touched | core-fork? |
|---|---|---|
| _(guard plugin: …)_ | `plugins/ironfleet-…/guard.ts` on tools/post-execute | |
| _(persona subagent: …)_ | `plugins/…/manifest.json` | |

## OpenCode S7c — Module E ported onto the A-1 mount (2026-09-24..10-01, commits `053baec..b9590b9`) — verdict: (a) CONDITIONAL, (b) PASS, no fork

> **S7c seams = 5 new + 6 reused = 11 attachment points** (the spike's 9 above are unchanged;
> the three guard-hook rows and the persona-subagent row are REUSED, not re-counted as new).
> The spike's other 5 rows (provider wiring, workspace isolation, newline flatten, tree-kill,
> >64 KB file transport) are also reused unchanged in kind and are re-listed only to say where
> S7c touched them.
>
> **Why (a) is CONDITIONAL, not PASS.** Acceptance ran 2026-10-01
> (`scripts/accept_s7c.py`, artifacts `data/eval/S7C-PARITY-2026-10-01/`). Checks 1
> (persona parity, 30/30 case-pairs on `thomson1-chat`: mount citation_accuracy 0.156 vs house
> 0.228, grounding 0.383 vs 0.350, 20/30 exact ties), 2 (guard coverage 33/33) and 4 (no bypass,
> 9 models, `gate-local` only) PASS. **Check 3 (fail-closed) FAILS** — proven NOT the guard:
> opencode 1.18.33 loses the model's tool call before `tool.execute.before` is ever reachable
> (the driver captured opencode's own 14-tool request and replayed it straight to Ollama;
> `finish_reason: tool_calls`, calling `ironfleet_without_prejudice`). The spike proved the
> block live on 1.18.25 on 2026-09-01. `EXPECTED_VERSION` still reads 1.18.25; the rig
> (`scripts/verify_opencode_mount.py`) reports the drift and exits 1 — the harness refusing to
> lie. On 1.18.33 the ported tools and BOTH tool hooks are effectively dead.
>
> Rubric exact-passes were 0/30 on BOTH sides — thomson1 rarely emits the exact citation
> needles, so the 20/30 exact ties are the agreement signal. Structural bar met; a low absolute
> number is a model property, not a port failure.

| seam | file/hook touched | core-fork? |
|---|---|---|
| custom-tools plugin (4-placeholder shim + Python dispatcher) | `data/opencode-a1/opencode.json` mounts `.opencode/plugins/ironfleet-tools.ts` ← `render_tools_plugin(TOOLS_TEMPLATE, ws, python, manifest, ported_rows)` (4 placeholders `__SPIKE_WS__/__PYTHON__/__MANIFEST__/__TOOLS__`; renderer substitutes exactly these four) → one `tool()` per `ported` manifest row (`args: {}` — 1.18.25's `tool()` takes a ZodRawShape, so an empty shape is the per-tool passthrough) → `spawnSync` venv python `-m harness.module_e.dispatch <manifest> <tool> <in> <out>`. The manifest (`data/module-e/tools.yaml`) is the single source of truth for persona enablement, the guard's annotation whitelist AND the tool list — three projections of one load, so they cannot drift | no |
| skills native discovery | `.opencode/skills/<name>/SKILL.md` — 26 docs copied from the old tree by `harness.module_e.skills.sync_skills`; frontmatter normalised (missing `name:` inserted, CRLF→LF, `description: >` block scalars validated via `yaml.safe_load` because a line-split would measure the literal `>`); `what_if_dashboard` dir renamed `what-if-dashboard`, the one corpus name violating the skill-name rule (its frontmatter already read the hyphenated form) | no |
| seam tools `route` + `refine_output` | two manifest `ported` rows whose `entry:` is `harness.module_e.supervisor:route_tool` / `harness.module_e.refine:refine_tool` — the SAME dispatch path as the skill tools, no special case. Measured LLM contract: refine's wire model is the BARE alias `gate/<task_class>` (`egress_proxy.py:108 resolve_alias`), matter identity rides the workspace's `matter.json`, `POST {base}/chat/completions stream:false` — and the proxy IS the gate's egress point, the same path opencode itself uses | no |
| mount model-alias growth | `data/routing-a1.yaml`: 4 new `gate/*` aliases (`drafting`, `classification`, `complex_reasoning`, `summarization`) so the personas' task types route (S7b's table had 5; a drafting rule pointed at unregistered `mini1-mlx` would have refused citation+clerk at acceptance) + `limit.output: 16384` on every model in `data/opencode-a1/opencode.json` (thomson1 needs ≥16k: ~3k+ reasoning tokens precede content) → 9 aliases, the catalog opencode resolves | no |
| per-decision guard log | same guard plugin → one JSONL line per hook call (`tag`, `decision`, `reason`, `chars`, `sha256_16`, `sha256_out`, `annotated`, `authorities`) → `<ws>/guard-log.jsonl`, sliced per run into `guard-slices/<run>.jsonl`. **SUPERSEDES Task 5's "byte-identical to the spike" pin**: the spike's log had only retry + event-summary lines, so acceptance check 2 had nothing to read. Guard is 158 lines against the spec's ~100 aspiration; the proven sections (serialized chain, retry, file transport, defensive checks, whitelist, block-throws) are untouched and `logDecision` returns its argument unchanged | no |
| **REUSED** guard hook — tool path (result annotation) | `tool.execute.after` — proven section unchanged from `ironfleet-guard.ts` | no |
| **REUSED** guard hook — tool path (block decision) | `tool.execute.before` (throw = block) — proven section unchanged; **unreachable on 1.18.33, see the CONDITIONAL note** | no |
| **REUSED** guard hook — model-output path | `experimental.text.complete` — still the priced M0 hazard 1; fired 33/33 in acceptance | no |
| **REUSED** persona subagents | 13 primaries + 4 variants + 17 drive twins generated from `personas.yaml`/`_source/` (byte-exact transcription); `hunter` replaces the spike's hand-written twin | no |
| **REUSED** >64 KB file transport | guard + tools shim both ride temp files (Bun `spawnSync` stdin deadlock, observed live 2026-09-01); tools shim adds the same serialized `Promise` chain the guard uses (concurrent Python spawns observed failing) | no |
| **REUSED** workspace isolation + tree-kill + newline flatten | `sync_mount` still `git init`s the workspace (no commits — the matter never enters history); supervision and prompt flattening unchanged from the spike driver, reused via `run_opencode`/`flatten_prompt` | no |

### PRICED SEAM (evidence attached): the guard annotates INSIDE structured JSON tool results

`tool.execute.after` writes its annotation into the tool result string, and a custom tool's
result is JSON. Observed live (Task 10, 2026-09-24): `ironfleet_statutory_demand` returned
`"issues": [] [UNGROUNDED — not confirmed]`, because `guard_port._citations` treats `[]` as a
citation envelope and the shipped `allowed.json` authorities are empty. The same result yields
decision `block` — inert while `block: false`, fail-closed the moment a driver flips it.
The spec's envelope rule names custom tools as annotation-eligible, so the whitelist stands and
this is priced rather than patched; the wrinkle is that the annotation is now indistinguishable
from model-authored JSON to a naive consumer. Acceptance unaffected: parity drives zero-tool
twins, and blocking never mutates. Task 13's obligation falls out of it — a driver that forgets
to write authorities annotates-and-blocks every bracket in the response.

### OPERATIONAL HAZARDS at close-out

1. **OPEN — the opencode version drift is now load-bearing.** The global binary auto-updated
   1.18.25 → 1.18.33 mid-programme (Task 12, ~2026-10-01 00:43): the user's global
   `~/.config/opencode/opencode.jsonc` carries no `autoupdate: false` — the mount's own setting
   only protects mount workspaces. Behavioural evidence was re-measured on BOTH versions
   (mount checks identical); what differs is that 1.18.33 drops model tool calls. **User
   decisions pending, neither actioned:** (a) `npm i -g opencode-ai@1.18.25`, or a deliberate
   bump to 1.18.33 after seam re-verification; (b) `autoupdate: false` in the global
   `opencode.jsonc` — the actual cause. Re-verification path once either lands:
   `accept_s7c.py --skip-parity` re-proves checks 2–4 (a DEBUG mode — exits 2 and writes no
   acceptance verdict); the module is acceptance-complete only on a full four-check run
   exiting 0.
2. **NEW — child-env credential scrub** (Task 12). The spike scrubbed nothing: opencode
   activates providers from inherited bearer keys, its own auth store, and the keyless builtin
   catalog. `child_env(ws)` now copies-on-write and scrubs prefix families including `AWS_`
   (`AWS_REGION` alone activates 178 bedrock models; the real activators are
   `AWS_ACCESS_KEY_ID`/`_SECRET`), plus `disabled_providers: ["opencode"]` in the mount config
   to shut the keyless catalog. Verified by `scripts/verify_opencode_mount.py --live` against
   the binary (`opencode models` = the union of every activation path).
3. **Carried** — M0 hazard 1 (`experimental.text.complete` is experimental; pin + re-verify on
   every upgrade), the SSE adapter stays unit-tested only (S7b CARRIED ruling — the pinned
   client does not stream).

## OpenCode S7f — scheduler caps + same-case queue (2026-10-02, commits `57cd050..` HEAD) — verdict: (a) PASS, (b) PASS, no fork

> **S7f seams = 1 new + 1 reused.** The seam count rises by **exactly one** — the per-matter
> identity attachment described below. Every other S7f surface is in-process harness code.
>
> **Why (a) is PASS.** Acceptance ran 2026-10-02 (`scripts/accept_s7f.py`, exit 0 on all seven
> checks). C7 — the one check a binary seam can fail — ran two real mounts against the installed
> opencode 1.18.33 binary and resolved matter identity through the mount's baseURL path form
> (`/v1/m/<ref>/`); turns landed under both `m-s7f-a` and `m-s7f-b`. The pin decision remains
> S7c's pending user decision, so the binary version is printed, never asserted.

| seam | file/hook touched | core-fork? |
|---|---|---|
| per-matter identity via baseURL path | `stand_up_opencode.py` (`sync_mount`) now writes one `matters/<ref>/matter.json` record per mount and points the mount's provider `baseURL` at `http://<host>:<port>/v1/m/<matter_ref>`, so opencode's own provider wiring carries matter identity to the gate on every dispatch — no header, no plugin, no prompt surgery. The proxy's `/v1/m/<ref>/chat/completions` path form is the matching reader. **New is only the path segment**: the provider/baseURL wiring itself is a REUSED seam from S7b/S7c. No guard hook and no plugin were touched for this module. | no |
| **REUSED** provider wiring | `opencode.json` custom provider `ollama-local` — unchanged in kind from the spike and S7c; S7f only varies the `baseURL` path segment per matter | no |

### In-process by construction: the scheduler attaches to nothing

`harness.scheduler.TurnScheduler` is in-process harness code with **no opencode attachment
point** — exactly like S7e's embedding path. It sits below the gate's egress proxy
(`egress_proxy.py` submits every dispatch as a turn) and above nothing external; opencode
never sees it. The same is true of `harness.capacity.machine_capacity()`. So the seam count
does not rise for the scheduler, the capacity probes, the FIFO locks, or the 503/Retry-After
queue-timeout path — none of them cross the harness boundary.

## S7g (A-6 macOS packaging) — 2026-10-05

**No change.** As predicted in spec §8: the packaging surface attaches to macOS
install/launch machinery, not to opencode. The mount scaffolding (`baseURL` path form,
`matter.json`) is REUSED from S7b/S7f; the opencode pin and `autoupdate: false` are
install-time config with no hook or plugin; the launcher wraps the egress proxy, which
is in-process harness code with no opencode attachment point — the same shape as S7e's
embedding path and S7f's scheduler. Confirmed by accept_s7g.py's static layer (exit 2:
five static checks PASS on Windows, live layer due-for-Mac, no verdict written); the live
confirmation belongs to S7g-M on a Mac.

## S7h (A-7 model substitution) — 2026-10-09

**No change — zero, as predicted in spec §9.** The A/B runner (`scripts/run_ab.py`),
the dashboard (`scripts/build_dashboard.py`) and the acceptance driver
(`scripts/accept_s7h.py`) are in-process harness code driving the egress gate
directly — the same shape as S7e's embedding path, S7f's scheduler and S7g's
packaging layer. Verified by grep over the A-7 surface: the only occurrences of
"opencode" in the A-7 scripts are *comparison notes* (the ~8x prompt-scaffolding
tax and the "no opencode" corpus line in the dashboard), never an attachment
point — no hook, no plugin, no mount, no provider wiring touched. The golden
corpus dispatches through `EgressGate` to Ollama and the cloud endpoint exactly
as S2's baseline runner did; opencode never sees a token.

No new seam surfaced from the live run either. The two live findings (the
reasoning model's buffered-vs-streamed hang, and carrying the probe's `verified`
verdict forward) are both inside the gate and the provider layer, which are
already-counted in-process surfaces.

## S7i (A-9 self-improving agents) — 2026-10-12

**No new seams — 0 new + 2 reused, as predicted in spec §8.** The memory appendix rides the
existing S7c persona-subagent seam (new CONTENT in an existing generated file — the S7f
"only the path segment" standard); the C5 live check reuses the CLI prompt transport. The
loop, reflector and store are in-process harness code with no opencode attachment point —
the S7e/S7f/S7h shape. `resolve_store_root()` gained its first core runtime consumer
(paths.py's deferred-wiring note gets its first tick).

**Byte-lock supersession recorded (spec §8, §2.4 precedent):** `scripts/stand_up_opencode.py`
was amended (`sync_mount` grew the memory-projection step) under S7i's own acceptance.
`personas.py`, `gate.py`, `policy.py`, `trace.py`, `providers/` untouched.

**Acceptance CONDITIONAL (exit 1), the S7c pattern — C1-C4+C6 PASS, C5 split:**
- **The loop is live-proven end to end**: real reflector screen (its first live proposal was
  a 2,243-char near-verbatim echo of the persona's own system prompt — the oversize guard
  rejected it exactly as designed, recorded as proposal 1); seeded canary confirm ran its 60
  real dispatches and the comparator honestly **rolled it back** (tie → rollback, the SRS's
  "kept only if improved"); revert restored exact bytes as a new version; all 66
  agent-memory dispatches traced `ollama-local`, zero `verified=1` (CR-3 honest).
- **C5's mount projection PASSES** (canary in the synced subagent file, asserted every run
  against a scratch fresh store); **the live session-read leg is BLOCKED BY BINARY — a NEW
  drift finding:** opencode 1.18.33 falls back to the DEFAULT agent when `--agent` names a
  subagent (stderr: "Falling back to default agent"), and @-mention delegation rides the
  dead tool path (S7c check 3). Proven not-the-mount: the drive under the loop's recorded
  override reached the gate (traced) and the default agent answered "I am opencode…".
  1.18.25 drove subagents directly (spike-proven) — the full C5 proof lands with the pin
  decision, alongside S7c's check 3.

**Deferred, named (spec §9):** agent-initiated memory tools (parked on S7c's pin decision);
live-session transcript harvesting; cross-agent memory sharing; embedding recall over memory.
