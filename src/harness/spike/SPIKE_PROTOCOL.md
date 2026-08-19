# SPIKE PROTOCOL — Adopt-vs-Build Evidence Run (P0-5)

**Candidates:** OpenCode · OpenHands · dsh (DeepSeek Harness)
**Budget:** exactly **2 days per candidate** (6 days total). Hard stop — day 3 on a
candidate means the candidate failed, not that the budget moves.
**Ports under test:** exactly **two** per candidate. No third port, however tempting:
1. **Guard as hook** — the portable grounding guard (`guard_port.py`) mounted so it
   fires on every tool-execution path AND every model-output path.
2. **Persona as subagent** — the HUNTER legal-research persona (`persona_port.py`)
   mounted as a subagent, driven by the LEGAL golden prompts.
**Material:** non-privileged only. Synthetic seeds and abridged persona text. No real
matter data touches any candidate — the P0-6/A-8 supply-chain reviews precede that.

## Procedure (per candidate)

1. Mount the guard via the candidate's adapter (`OpenCodeHookAdapter`,
   `OpenHandsHandlerAdapter`, or `dsh_plugin_skeleton()`). **No core fork** — if the
   only way to make the guard fire is editing the harness's own source, that is a FAIL
   condition, not a workaround.
2. Mount the persona as a subagent using the fragment in `PERSONA_PORT["configs"]`.
3. Run the LEGAL golden prompts — the seed set from `data/golden_cases/`
   (`seed-imca-001`, `seed-limitation-001`, `seed-without-prejudice-001`) until
   Jonathan's authored cases land, then his set replaces the seeds.
4. Fill the candidate's table in `SEAM_COUNT.md` as you go, not at the end.

## Pass criteria (all three, per candidate)

- **(a) Guard coverage, no fork.** The guard fires on every tool-execution and
  model-output path. Verified by a run where an ungrounded citation
  (`[Imaginary Act 2026, s 9]`) is injected and MUST be annotated
  `[UNGROUNDED — not confirmed]` on every path that can emit text. Zero commits to the
  candidate's own repo (plugins/hooks/config only).
- **(b) Persona parity.** The subagent's outputs on the LEGAL golden prompts meet the
  seed cases' `expected_citations` and `persona_checks` — same citation accuracy and
  grounding behaviour the in-house HUNTER shows, judged by the eval harness's scorers.
- **(c) Seam count recorded.** `SEAM_COUNT.md` carries one complete table per candidate.

## Ordering & gate

- **dsh runs LAST and ONLY after its P0-6 dependency-provenance pre-check clears.**
  If the pre-check fails, dsh is recorded "not run — pre-check failed" and the spike
  concludes with the other two.

## M0 tie-break (CR-2a)

An **OpenCode or OpenHands pass beats a dsh pass** unless dsh wins **decisively** on
seam count **AND** clears the stability bar: a pinned commit (no floating dev preview)
**AND** a costed willingness to maintain the fork/seams. Absent both, the CR-2a default
holds. `SEAM_COUNT.md` is the input that reprices Module E (A-2/B-5, 48h) — see its
header for how the count converts to hours.
