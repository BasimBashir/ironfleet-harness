# data/module-e/BATCH.md — the named S7c batch ticket

The follow-on task *inside* S7c: port what this cycle deferred. `tools.yaml` is the machine
source of truth — every row below is a `status: deferred` row there with its own `reason` field;
this file is the human-readable plan those reasons point at. Nothing here blocks the S7c
acceptance spine (the mount stands with 4 ported tools and 26 natively-discovered SKILL.md
documents), and nothing here is allowed to go silently missing: every persona reference to a
deferred name is already recorded in that persona's generated `# deferred` ledger
([PROVENANCE.md](./PROVENANCE.md), "Measured end state").

Scope: **20 deferred executable skills + 4 prompt-only skills** (one of which is not actually
prompt-only — see §3). Sources are measured from the old tree
`C:\Users\mianx\OneDrive\Desktop\IronFleet\legalai\skills\`, read 2026-10-01 for this ticket.

**House rule for every item:** vendored under `src/harness/module_e/vendored/`, diffed
LF-stripped against the old-tree original, and limited to the three-edits rule (import path,
module docstring, and nothing else without a recorded reason). Characterization tests pin the
observed contract BEFORE the wrapper is written — Task 7's findings are the template (the
detector's status vocabulary is `ERROR`/`FLAGGED`/`SUCCESS`, never `"OK"`; a missing required
arg raises `KeyError`, not `TypeError`). No `sys.path` edits, no cross-tree reach, no network
import outside the gate's loopback proxy — the check-4 static sweep of `accept_s7c.py` stays
the gate on that.

## 1. Kernel-backed five — dependency ALREADY vendored, port is mechanical

`tools.yaml` gives each of these an `aliases:` field (the kernel name is an alias on the skill
row, never a row of its own). All five are single-file, stdlib-plus-`Decimal`, and their one
non-stdlib import is `helpers.jurisdiction_loader` — which is **already vendored**
(`vendored/jurisdiction_loader.py`, stdlib-only, provenance-diffed at Task 7). No new
dependency work; expect the same three-edits shape as `companies_act.py`.

| # | manifest row | source script (old tree) | kernel alias |
|---|---|---|---|
| 1 | `ironfleet_solvency_assessor` | `nz-solvency-assessor/scripts/cccfa_2003.py` (224 L) | `cccfa_2003` |
| 2 | `ironfleet_penalty_clause` | `nz-penalty-clause-analyzer/scripts/ccla_2017.py` (157 L) | `ccla_2017` |
| 3 | `ironfleet_imca_2016` | `nz-imca-2016-calculator/scripts/imca_2016.py` (142 L) | `imca_2016` |
| 4 | `ironfleet_limitation_act` | `nz-limitation-act-checker/scripts/limitation_act.py` (123 L) | `limitation_act` |
| 5 | `ironfleet_security_interest` | `nz-security-interest-checker/scripts/pla_2007.py` (153 L) | `pla_2007` |

Each takes an optional `JurisdictionLoader` at call time (lazy import inside the function),
so the wrapper needs no jurisdiction argument of its own. Do these first: they are the rows
`auditor`'s `# deferred` ledger already names, and they close the only persona with enabled-tool
expectations.

## 2. Plain executable twelve — stdlib-only, port is a copy + wrapper

No non-stdlib import in any of them (measured). The work is characterization tests + the
`kernel_tools.py`-style wrapper + flipping the row to `status: ported` with a real `entry:`.

| # | manifest row | source script (old tree) | triage note |
|---|---|---|---|
| 6 | `ironfleet_exhibit_numberer` | `exhibit-numberer/scripts/exhibit_numberer.py` (217 L) | pure text; no deps |
| 7 | `ironfleet_context_compression` | `nz-context-compression/scripts/nz_context_compression.py` (324 L) | pure text; no deps |
| 8 | `ironfleet_contract_review_analyzer` | `nz-contract-review-analyzer/scripts/contract_review.py` (311 L) | pure text; no deps |
| 9 | `ironfleet_contract_reviewer` | `nz-contract-reviewer/scripts/nz_contract_reviewer.py` (345 L) | pure text; no deps |
| 10 | `ironfleet_data_structure_protocol` | `nz-data-structure-protocol/scripts/nz_data_structure_protocol.py` (315 L) | pure text; no deps |
| 11 | `ironfleet_memory_systems` | `nz-memory-systems/scripts/nz_memory_systems.py` (308 L) | pure text; no deps. Name notwithstanding: no cognee/redis in the script — the A-4 memory tier is a separate module, not this |
| 12 | `ironfleet_property_based_testing` | `nz-property-based-testing/scripts/nz_property_based_testing.py` (315 L) | pure text; generates test scaffolds, does not import `hypothesis` |
| 13 | `ironfleet_recursive_decomposition` | `nz-recursive-decomposition/scripts/nz_recursive_decomposition.py` (355 L) | pure text; no deps |
| 14 | `ironfleet_differential_review` | `nz-differential-review/scripts/nz_differential_review.py` (332 L) | **see §5** — the ONE LLM-bearing item |
| 15 | `ironfleet_varlock` | `nz-varlock/scripts/nz_varlock.py` (300 L) | `subprocess` + `shutil.which("varlock")`: shells out to an EXTERNAL `varlock` CLI, absent from this machine. Port the wrapper + the not-installed degradation path; the CLI itself is an environment dependency to declare, not to vendor |
| 16 | `ironfleet_court_calendar` | `nz-court-calendar/scripts/nz_court_calendar.py` (315 L) | **already vendored at Task 7** (`vendored/court_calendar.py` + `vendored/nz_calendar.py` + the 6 jurisdiction JSONs; the `sys.path.insert` back to the old project root is gone — verified no `sys.path` in `vendored/`). Only the tool row + `entry:` remain. Cheapest item on the ticket |
| 17 | `ironfleet_pagination_index` | `pagination-index-mapper/scripts/pagination_index_mapper.py` (392 L) | `pdfplumber` (guarded import). TWO scripts in the dir — `check_bounding_boxes.py` (68 L, also `pdfplumber`) rides the batch as a second row or is explicitly dropped with a recorded reason; the manifest's `reason` field already names it |

## 3. The four "prompt-only" skills — three are docs, one is a hidden executable

`tools.yaml`'s prompt-only comment names four skills with no `scripts/` dir and therefore no
tool row. Three of them really are prompt-only — `SKILL.md` + `__init__.py` and nothing else,
measured in the old tree:

| # | skill doc (already ported) | old-tree contents |
|---|---|---|
| 18 | `affidavit-formatter` | `SKILL.md` + `__init__.py` |
| 19 | `correspondence-tone-analyser` | `SKILL.md` + `__init__.py` |
| 20 | `summariser` | `SKILL.md` + `__init__.py` |

These need no batch work beyond a decision: they are already natively discoverable at
`.opencode/skills/`, so the only question is whether any of them should ever become a tool row.
Default answer: no — a prompt-only skill is a prompt the model reads, not a function it calls.

**21. `what_if_dashboard` is NOT prompt-only.** Task 8's review found the real thing:
`skills/what_if_dashboard/what_if_dashboard.py` — **649 lines, 25,752 bytes, sitting at the
SKILL-DIR TOP LEVEL**, not under `scripts/`. The manifest's executable-skill scan walks
`<skill>/scripts/*.py`, so this file was invisible to it and `tools.yaml` classed the whole
skill as prompt-only on the strength of a missing directory.

Triage note (first-class batch item, not a footnote):

- **Surface:** top-level module, no `scripts/` dir, `__init__.py` is a 45-byte stub. Port it as
  `vendored/what_if_dashboard.py` (do not invent a `scripts/` layout the old tree does not
  have) — preserving the old shape keeps the provenance diff clean and the three-edits rule
  checkable. Its own integration comment shows the intended call is
  `from skills.what_if_dashboard.what_if_dashboard import run_what_if`, an absolute
  package-rooted import, so the import-path edit is the same three-edits shape as §1.
- **It is not a leaf — the 649 lines sit on ~5,000 lines of old-tree dependency.** Three
  guarded imports, each with a documented degradation flag (measured 2026-10-01):
  `simulations.batna_analyzer` → `_BATNA_AVAILABLE`; `simulations` (8 functions:
  monte carlo, nash, decision tree, sensitivity, pivot pricing, markov, belief update, causal)
  → `_SIM_AVAILABLE`; `tracing.context` → `_TRACING_AVAILABLE` with a graceful no-op fallback.
  `simulations/` is **14 files / 4,556 lines**; `tracing/context.py` is 411 lines. The batch
  decision is therefore not "copy one file" but **which tier to vendor**: module-only (all
  three flags false, degraded but importable — cheap, and it still type-checks and returns its
  status vocabulary), or module + `simulations/` (a real port, 4.5k lines to provenance-diff),
  or defer with a recorded reason. `tracing/` should NOT port — the A-1 mount already has a
  trace store, and a second tracer behind the gate is exactly the kind of duplication the
  module boundary exists to prevent.
- **No kernel alias** on any row: `tools.yaml` has no `what_if_dashboard` alias, so nothing in
  the alias map changes.
- **No persona references it — verified, and it matters.** Zero hits for `what_if_dashboard` /
  `what-if-dashboard` across `agents/` (both the `config.yaml` tool lists and the transcribed
  `prompts.py` constants), so the reconciliation's "no silent drop" property does not bind —
  which is exactly why it fell through. The module's own docstring claims it is
  "Called by @NEGOTIATOR / @WARGAMER via @PLANNER"; no agent config or prompt in the old tree
  substantiates that, so treat it as aspirational. A batch scoped from the manifest alone would
  have missed this file permanently; that is why it is item 21 and not a comment.
- Name it `ironfleet_what_if_dashboard`, add it to `tools.yaml` as `status: deferred` with
  `reason:` pointing here. `tools.yaml`'s prompt-only comment now points at this file; when the
  port lands, the comment drops it and the row appears.

## 4. External-dependency items — decide before porting, not during

| # | manifest row | dependency | the decision |
|---|---|---|---|
| 22 | `ironfleet_hearing_bundle` | `pypdfium2` (render) + `fpdf` (write), both guarded imports | PDF in AND out. Both are real wheels on Windows, but they are the only new install surface on the ticket outside §5. Decide: `.venv` install + record in the install discipline, or defer the write path and return text-only |
| 23 | `ironfleet_kreuzberg_ingestor` | `kreuzberg` (guarded import, `extract_file` + `ExtractionConfig`) | Heavy deps behind it. This is ingestion tooling, and A-4 owns the ingestion tier — consider folding it into A-4 rather than porting it standalone |
| 24 | `ironfleet_nutrient_processor` | `requests` → **`POST https://api.nutrient.io/build`**, gated on `NUTRIENT_DWS_API_KEY` | **A cloud egress event, not a dependency question.** Sending privileged matter text to a SaaS extraction API is exactly what the egress gate exists to classify (S7e's rule). It cannot port as a plain tool row: either it becomes a gate-classified provider, or it is dropped with Jonathan's sign-off. The check-4 static sweep would flag the `requests` import the moment it landed |

## 5. The LLM-bearing item

**`ironfleet_differential_review`** — the manifest's `reason` says "the ONE LLM-bearing script —
must dispatch through the gate". Read precisely: the script itself makes **no network call**
(measured — its imports are `hashlib`/`json`/`re`/`decimal`/`typing`, and its regexes are a
DENYLIST of LLM-shaped module names: `model_router`, `anthropic`, `openai`, `requests`, …). It
is a static diff-risk analyser. The LLM involvement is the SKILL.md's review *workflow*, which
expects a model to act on the diff it grades.

Consequence for the batch: port the analyser as an ordinary tool row (it is stdlib-only, so it
belongs in §2's mechanical group), and wire the workflow step it grades so that any LLM call it
triggers rides `refine_output`'s path — the bare-alias gate proxy, matter identity from the
workspace's `matter.json`. Do not give this skill its own HTTP client; that is the one thing
that would break check 4.

## 6. Also batch-shaped, but not manifest rows

These are persona `allowed_tools` DROPs whose disposition in
[PROVENANCE.md](./PROVENANCE.md) says "batch task". They have no `tools.yaml` row, so a
manifest-scoped batch would silently skip them — the same failure mode as §3's item 21. Name
them here so the decision is explicit: port, or record as out of S7c scope.

| old-tree name | personas carrying it | where it lives | note |
|---|---|---|---|
| `citation_extractor` | adversary, clerk, evaluator, hunter, strategist, verifier | not located in `skills/` — needs a source hunt before it can be triaged at all | the only item here with no measured source path |
| `pdf_extractor` | citation, ingestor | `tools/document_analysis/` | old-tree package, not a skill |
| `pdf_snippet` | citation | `tools/document_analysis/` | same package |
| `legal_chunker` | ingestor | `tools/` | ingestion tooling — A-4 candidate, like §4's kreuzberg |
| `docx_preprocessor` | ingestor | `tools/` | ingestion tooling — A-4 candidate |

Two further DROPs also read "batch task" in PROVENANCE and are already covered above:
`nz_calendar` → `ironfleet_court_calendar` (§2 item 16), and `skill_loader` → superseded by
native skill discovery (no batch work; the DROP is final).

## 7. Non-goals

- **No persona re-reconciliation.** `personas.yaml`'s `allowed_tools`/`denied_tools` were
  reconciled once, measured, and reviewed; porting a deferred row does not retro-edit a
  persona's ledger — the generator re-reads the manifest on the next `sync_mount`, and a
  persona that carried the name in its `# deferred` ledger gains the enabled tool on that
  refresh. That is the mechanism working, not a change to make by hand.
- **No EXPECTED_VERSION or global-install change.** The opencode pin decision is the user's and
  is recorded as pending in [SEAM_COUNT.md](../../src/harness/spike/SEAM_COUNT.md).
- **No acceptance re-run.** The batch is not on the acceptance spine; `accept_s7c.py` is not
  re-run for a batch item, only for a guard or mount change.
