# 09 — Moot Gate Design (M6)

**Date:** 2026-11-05 · **Status:** implemented as the 0.5.0 plugin prototype
(`ironfleet-legal/`); this document records the design, the measured detection table,
and the boundaries. **Companions:** [08-guided-journey-ux.md](08-guided-journey-ux.md)
(§N5 renders the flaw ledger defined here) · NEXT_STEPS §8 (M6 row) ·
`specs/12` (the keep-if-better bar, S7i). Framing rule as everywhere in enterprise:
maximum defensibility, never "courts will accept this output".

## 0. What this document is

The moot gate is the mechanism that separates "a draft exists" from "a draft may be
marked final". It has four parts: a **deterministic pre-pass** (kernels + corpus,
never a model), a **flaw ledger** (dossier register #9), **adversarial rounds**
(five new agents), and a **platform hook** that makes the final marker unforgeable
by the drafting model. Everything is offline-measurable; the prototype ships with a
seeded-flaw eval set that holds the bar in CI.

## 1. The principle

Nothing is marked final without a passed gate, and a CAPPED draft is NEVER final —
it goes to approval with its flaws listed. Two consecutive clean rounds →
`moot-gate: PASSED <run_id>`; open critical/material flaws after 4 rounds →
`CAPPED` (flaws listed, never hidden). The gate measures the mechanical floor plus
judgement rounds; it makes no promise about what a court accepts.

## 2. Architecture (one pass, one register, rounds, one hook)

- **`ironfleet_moot_check` (deterministic floor).** One call wraps three surfaces:
  (a) the objection pass — every quote and `[E*.S*]` ref verdicted against the
  corpus, every stated date/period checked against the run's logged kernel
  computations (a deadline-speaking draft must state the kernel's computation), any
  statutory demand demanded to have a logged kernel run; (b) the citator —
  later-citing judgments surfaced as **minor** rows, never blocking (the good-law
  reading call is human); (c) `moot_checks` — every exhibit ref traced to the
  evidence register (fail-closed), every statutory-demand line re-validated by the
  vendored kernel. Never raises; unreadable drafts come back as an error envelope,
  not a conviction.
- **The flaw ledger (register #9).** Append-only JSONL, last-status-wins per
  `flaw_id`; projection at read: open rows, open counts by severity
  (critical/material/minor), `gate_blocked` = any open critical **or** material.
  Rows are appended by the `/moot` orchestrator with `detector` naming which
  surface found them; a fixed row is a NEW append (`status: fixed`), never an
  edit. Minor rows never block.
- **Adversarial rounds (max 4).** opposing-counsel attacks the draft + flaw rows;
  procedural-examiner and evidence-examiner cover their lanes; the drafter fixes
  or answers each CRITICAL/MAJOR attack and re-runs the pre-pass. A round is clean
  when the mechanical pass is clean AND no agent holds a CRITICAL/MAJOR attack.
- **The hook.** A PreToolUse (Write|Edit) hook denies any write whose resulting
  text matches `^status:\s*final\s*$` (line-anchored, so quoted court text like
  "final order" never trips) without a `moot-gate: PASSED <run_id>` line — exit 2,
  reason on stderr. A crashed or unreadable hook ALWAYS allows: a checker that
  cannot read cannot convict. CAPPED documents carry `moot-gate: CAPPED <run_id>`
  and stay non-final.

## 3. Keep-if-better (the specs/12 S7i bar)

Baseline vs candidate flaw counts on three axes (critical, material, minor):
keep iff ≤ on all and < on ≥ 1; all-tie → ROLLBACK; a regression on any axis →
ROLLBACK (naming the axis); counts that are not three integers → REFUSED (unusable
leg). Exposed via `ironfleet_flaw_ledger op=compare` and graded in the dummy-case
grader.

## 4. Measured detection (Track B5 seeded-flaw eval, this build)

`tests/moot-eval/`: 30 flawed docs (6 per class × 5 classes, one critical flaw per
doc, corpus-anchored so only the seeded flaw trips) + 4 clean controls.
`tests/test_moot_eval.py` runs the gate over all 34 offline (fake embeddings, the
harbour-freight dummy corpus) and asserts the bar:

| class             | detected | note |
|-------------------|----------|------|
| wrong_deadline    | 6/6      | vs logged `ironfleet_filing_deadline` comp |
| misquote          | 6/6      | paraphrase/number-swap of real corpus sentences |
| fabricated_case   | 6/6      | invented authority + ref token |
| missing_exhibit   | 6/6      | refs absent from the evidence register |
| wrong_form        | 6/6      | SD below $1,000 or 10–14 working days, kernel INVALID |
| **overall**       | **30/30 (1.00)** | bar ≥ 0.90 |
| clean controls    | 0/4 false positives | blocking rows on controls |

Deterministic floor only. The AGENT-layer detection rate is a different number and
is NOT claimed from this prototype (§5).

Fixture findings worth keeping: the corpus ingest gate skips docs under 200 words
(eval corpus docs must clear it — a silently empty corpus convicts clean drafts);
evidence-register labels MUST be seeded for docs that legitimately cite exhibits,
or clean controls count as false positives; ref verdicts borrow from the nearest
preceding quote span, so a fabricated-case doc must not carry a preceding verbatim
quote (it would mask the fake ref).

## 5. Boundaries — what M6 does not do

- **Forms → M9.** The procedural-examiner covers procedural gaps by judgement;
  court-form generation and filing validation stay M9. Any point beyond judgement
  is flagged for the operator, never guessed.
- **Live agent-rate protocol.** The 1.00 above is the deterministic floor. The
  agent-layer rate (attacks the rounds actually catch on live drafts) needs a
  protocol: fixed drafts, fixed rounds, model-pinned runs — it is NOT asserted
  here and MUST NOT be quoted as 1.00.
- **Platform port.** The Claude Code plugin (agents/commands/hooks/MCP) is the
  prototype surface; the harness-core app consumes the SAME MCP tools and ledger
  — N5 renders the register defined in §2, the approval flow consumes CAPPED
  reports, nothing is reimplemented per platform.
- **No court-acceptance promise**, ever (framing rule).

## 6. Verification surface

Plugin pytest 115 passed (nine-register set, compare truth table, pure checks,
integrated moot_check, hook subprocess tests, tool-surface validation) · seeded
eval asserted green in `tests/test_moot_eval.py` ·
`python tests/grade_dummy_case.py` (BY FILE PATH) exit 0 with the M6 section
(seeded flaws caught, keep-if-better, ledger blocks-then-unblocks) ·
harness-core suite 833 passed, untouched.
