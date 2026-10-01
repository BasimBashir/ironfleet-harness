# Module E port — provenance (personas, skills, tools)

Every file in `personas/_source/` is a byte-for-byte transcription of a single
string constant from the old IronFleet tree
(`C:\Users\mianx\OneDrive\Desktop\IronFleet\legalai\agents\`). The old tree is
read-only and outside this repo; it is transcribed once by hand and never read
at test time.

Primary-selection rule: `SYSTEM_PROMPT` if the module exports one, else
`SYSTEM_PROMPT_IRON`, else the `legal_extraction_prompt` constant. Variants are
the remaining `SYSTEM_PROMPT_*` constants.

- `_source/adversary.txt` ← `agents/adversary/prompts.py:SYSTEM_PROMPT`
- `_source/ambiguity.txt` ← `agents/ambiguity/prompts.py:SYSTEM_PROMPT`
- `_source/architect.txt` ← `agents/architect/prompts.py:SYSTEM_PROMPT`
- `_source/auditor.txt` ← `agents/auditor/prompts.py:SYSTEM_PROMPT`
- `_source/citation.txt` ← `agents/citation/prompts.py:SYSTEM_PROMPT`
- `_source/citation-brain.txt` ← `agents/citation/prompts.py:SYSTEM_PROMPT_BRAIN`
- `_source/clerk.txt` ← `agents/clerk/prompts.py:SYSTEM_PROMPT_IRON` (no bare `SYSTEM_PROMPT` in this module)
- `_source/clerk-glass.txt` ← `agents/clerk/prompts.py:SYSTEM_PROMPT_GLASS`
- `_source/evaluator.txt` ← `agents/evaluator/prompts.py:SYSTEM_PROMPT`
- `_source/hunter.txt` ← `agents/hunter/prompts.py:SYSTEM_PROMPT`
- `_source/ingestor.txt` ← `agents/ingestor/legal_extraction_prompt.py:LEGAL_KNOWLEDGE_GRAPH_PROMPT` (no `SYSTEM_*` constant in `agents/ingestor/prompts.py`)
- `_source/negotiator.txt` ← `agents/negotiator/prompts.py:SYSTEM_PROMPT` (defined as `SYSTEM_PROMPT = SYSTEM_PROMPT_IRON`)
- `_source/negotiator-glass.txt` ← `agents/negotiator/prompts.py:SYSTEM_PROMPT_GLASS`
- `_source/strategist.txt` ← `agents/strategist/prompts.py:SYSTEM_PROMPT` (defined as `SYSTEM_PROMPT = SYSTEM_PROMPT_IRON`)
- `_source/strategist-glass.txt` ← `agents/strategist/prompts.py:SYSTEM_PROMPT_GLASS`
- `_source/verifier.txt` ← `agents/verifier/prompts.py:SYSTEM_PROMPT`
- `_source/wargamer.txt` ← `agents/wargamer/prompts.py:SYSTEM_PROMPT`

Index fields per persona (`description`, `task_type`, `allowed_tools`,
`denied_tools`) come from `agents/<name>/config.yaml`. Two divergences from the
common shape, carried verbatim:

- `citation/config.yaml` has no `denied_tools:` key, so the index carries
  `denied_tools: []`, and it declares its task type as `task_type:` (not
  `default_task_type:`), value `drafting`.
- `citation/config.yaml` spells its description as a folded block scalar and
  uses the top-level `agent_name:`/`description:` keys rather than the
  `agent:`-nested form used by the other personas.

`allowed_tools`/`denied_tools` are old-tree tool names (e.g. `cognee_search`,
`nzlii_search`, `nz-statutory-demand-validator`) — Task 10 reconciles them
against the new tool manifest (see the reconciliation section below).

`manager` is excluded: it is the supervisor layer, not a persona (Task 3's
routing layer).

## Skill documents (Task 8)

Each SKILL.md below is copied from the old tree
(`C:\Users\mianx\OneDrive\Desktop\IronFleet\legalai\skills\`) to
`data/module-e/skills/<name>/SKILL.md`. Only the SKILL.md documents port: the
old tree's per-skill `scripts/`, `tests/` and `docs/` subdirs and its top-level
`skill_loader.py`, `manifest.lock` and `__init__.py` do not (the scripts port
with their tools in the batch task — [BATCH.md](./BATCH.md)).

Deliberately not copied either, measured in the old tree 2026-10-01:

- the per-dir `examples/` in **6** skills (`nz-imca-2016-calculator`,
  `nz-limitation-act-checker`, `nz-penalty-clause-analyzer`,
  `nz-security-interest-checker`, `nz-solvency-assessor`,
  `nz-statutory-demand-validator`) — sample inputs, not behaviour;
- the per-dir `__init__.py` in **19** skills — package markers for the old
  tree's `skills.` package import. The copies here are read as standalone
  documents, and `sync_skills` writes one SKILL.md per directory, so a marker
  would be dead weight and an unexplained residue.

The one skill-dir top-level file that is neither a document nor a package
marker is `what_if_dashboard/what_if_dashboard.py` — a real 649-line
executable that the manifest's `scripts/`-based scan cannot see, which is why
`tools.yaml` originally classed that whole skill as prompt-only. It is a
first-class batch item, not a dropped file: see
[BATCH.md](./BATCH.md) §3 item 21.

These copies are normalised, not byte-parity artifacts: CRLF on disk in the old
tree is normalised to LF here (consistent with `.gitattributes`). Frontmatter
normalisation itself happens at sync time — `harness.module_e.skills.sync_skills`
writes the workspace copies — so a copy's frontmatter is still the old tree's.

- `data/module-e/skills/affidavit-formatter/SKILL.md` ← `skills/affidavit-formatter/SKILL.md`
- `data/module-e/skills/correspondence-tone-analyser/SKILL.md` ← `skills/correspondence-tone-analyser/SKILL.md`
- `data/module-e/skills/exhibit-numberer/SKILL.md` ← `skills/exhibit-numberer/SKILL.md`
- `data/module-e/skills/hearing-bundle-assembler/SKILL.md` ← `skills/hearing-bundle-assembler/SKILL.md`
- `data/module-e/skills/nz-context-compression/SKILL.md` ← `skills/nz-context-compression/SKILL.md`
- `data/module-e/skills/nz-contract-review-analyzer/SKILL.md` ← `skills/nz-contract-review-analyzer/SKILL.md`
- `data/module-e/skills/nz-contract-reviewer/SKILL.md` ← `skills/nz-contract-reviewer/SKILL.md`
- `data/module-e/skills/nz-court-calendar/SKILL.md` ← `skills/nz-court-calendar/SKILL.md`
- `data/module-e/skills/nz-data-structure-protocol/SKILL.md` ← `skills/nz-data-structure-protocol/SKILL.md`
- `data/module-e/skills/nz-differential-review/SKILL.md` ← `skills/nz-differential-review/SKILL.md`
- `data/module-e/skills/nz-imca-2016-calculator/SKILL.md` ← `skills/nz-imca-2016-calculator/SKILL.md`
- `data/module-e/skills/nz-kreuzberg-ingestor/SKILL.md` ← `skills/nz-kreuzberg-ingestor/SKILL.md`
- `data/module-e/skills/nz-limitation-act-checker/SKILL.md` ← `skills/nz-limitation-act-checker/SKILL.md`
- `data/module-e/skills/nz-memory-systems/SKILL.md` ← `skills/nz-memory-systems/SKILL.md`
- `data/module-e/skills/nz-nutrient-processor/SKILL.md` ← `skills/nz-nutrient-processor/SKILL.md`
- `data/module-e/skills/nz-penalty-clause-analyzer/SKILL.md` ← `skills/nz-penalty-clause-analyzer/SKILL.md`
- `data/module-e/skills/nz-property-based-testing/SKILL.md` ← `skills/nz-property-based-testing/SKILL.md`
- `data/module-e/skills/nz-recursive-decomposition/SKILL.md` ← `skills/nz-recursive-decomposition/SKILL.md`
- `data/module-e/skills/nz-security-interest-checker/SKILL.md` ← `skills/nz-security-interest-checker/SKILL.md`
- `data/module-e/skills/nz-solvency-assessor/SKILL.md` ← `skills/nz-solvency-assessor/SKILL.md`
- `data/module-e/skills/nz-statutory-demand-validator/SKILL.md` ← `skills/nz-statutory-demand-validator/SKILL.md`
- `data/module-e/skills/nz-varlock/SKILL.md` ← `skills/nz-varlock/SKILL.md`
- `data/module-e/skills/pagination-index-mapper/SKILL.md` ← `skills/pagination-index-mapper/SKILL.md`
- `data/module-e/skills/summariser/SKILL.md` ← `skills/summariser/SKILL.md`
- `data/module-e/skills/what-if-dashboard/SKILL.md` ← `skills/what_if_dashboard/SKILL.md`
  (RENAMED: the only dir in the corpus whose name violates the skill-name rule —
  lowercase alphanumeric plus hyphens. Its frontmatter already reads
  `name: what-if-dashboard`, so after the rename the directory and the
  frontmatter agree; all other 25 frontmatter names already matched their dirs.)
- `data/module-e/skills/without-prejudice-detector/SKILL.md` ← `skills/without-prejudice-detector/SKILL.md`

## Persona tool-list reconciliation (Task 10)

Task 1 transcribed `allowed_tools`/`denied_tools` verbatim from the old
`agents/<name>/config.yaml`. Those names are old-tree identifiers, and none of
them exists in this mount: the old vocabulary spans THREE surfaces, verified
2026-09-24 — the `skills/` directories (26 of them), a separate `tools/`
package (`tools/calculation/`, `tools/document_analysis/`, …), and
MCP/builtin names. Until reconciliation, `generate_all` raised `UnknownTool`
for every persona; that was the mechanism working as designed.

Both lists were rewritten in `personas.yaml` against `tools.yaml` (24 rows, 4
ported). The disposition of every name is below. The old-tree transcriptions
themselves are unchanged — the verbatim input lives in this file, and the
index carries what the mount can actually honour.

### `allowed_tools` — all 24 distinct names disposed

| old name | personas carrying it | disposition |
|---|---|---|
| `nz-statutory-demand-validator` | auditor | → `ironfleet_statutory_demand` (ported) |
| `nz-solvency-assessor` | auditor | → `ironfleet_solvency_assessor` (deferred) |
| `nz-penalty-clause-analyzer` | auditor | → `ironfleet_penalty_clause` (deferred) |
| `nz-imca-2016-calculator` | auditor | → `ironfleet_imca_2016` (deferred) |
| `nz-limitation-act-checker` | auditor | → `ironfleet_limitation_act` (deferred) |
| `nz-security-interest-checker` | auditor | → `ironfleet_security_interest` (deferred) |
| `nz_calendar` | auditor, clerk | DROP — the `nz-court-calendar` skill doc ships at `.opencode/skills/`; wiring it as a tool is the batch task |
| `skill_loader` | adversary, ambiguity, clerk, evaluator, hunter, negotiator, strategist, wargamer | DROP — SKILL.md docs are natively discoverable; batch task |
| `limitation_checker` | negotiator, strategist, wargamer | → `ironfleet_limitation_act` (deferred) — old `tools/calculation/limitation_checker.py`, the same function as the limitation skill, so the old name resolves onto that deferred row the way the six kernel names do; negotiator/strategist/wargamer carry it in their `# deferred` ledger (see note A) |
| `interest_calc` | negotiator, wargamer | DROP — old `tools/calculation/interest_calc.py`; both configs annotate it "IMCA 2016 for interest exposure", so `ironfleet_imca_2016` (deferred) covers the capability (see note A) |
| `cognee_search` | adversary, architect, citation, clerk, evaluator, hunter, negotiator, strategist, verifier, wargamer | DROP — Central Brain retrieval lands with A-4 |
| `cognee_write` | architect | DROP — same A-4 family (memory write/ingest) |
| `cognee_ingest` | ingestor | DROP — same A-4 family (memory write/ingest) |
| `nzlii_search` | hunter | DROP — external-register access, out of S7c scope |
| `ppsr_search` | hunter | DROP — external-register access, out of S7c scope |
| `companies_office` | hunter | DROP — external-register access, out of S7c scope |
| `citation_extractor` | adversary, clerk, evaluator, hunter, strategist, verifier | DROP — no S7c port; batch task |
| `pdf_extractor` | citation, ingestor | DROP — old `tools/document_analysis/` ingestion tooling, batch task |
| `pdf_snippet` | citation | DROP — old `tools/document_analysis/` ingestion tooling, batch task |
| `legal_chunker` | ingestor | DROP — ingestion tooling, batch task |
| `docx_preprocessor` | ingestor | DROP — ingestion tooling, batch task |
| `file_read` | architect | DROP from `allowed_tools` — OpenCode's `read` builtin needs no enablement row |
| `file_write` | architect | DROP from `allowed_tools` — conservative: nothing in the acceptance spine writes files, and every other persona DENIES it |
| `redis_cache` | architect | DROP — old `helpers/cache.py` infra, not a legal capability |

Note A — the two `tools/calculation/` names. `limitation_checker` MAPS: it is
the same function as the limitation skill, so it resolves to
`ironfleet_limitation_act` exactly the way the six kernel names do, and
negotiator/strategist/wargamer — the personas that allowed it in the old
configs — carry that deferred row in their `# deferred` ledger rather than an
enabled tool. `interest_calc` stays a DROP per the table: its capability is
`ironfleet_imca_2016` (deferred), which auditor, the calculation persona,
already carries, so the reference is not re-hung on negotiator/wargamer.

(Correction on file: an earlier revision of this note recorded
`limitation_checker` as a drop, reading the reconciliation's summary sentence
over the mapping table. The table governs — it is what carries the
no-silent-drop property — so the mapping is restored.)

### `denied_tools` — all 7 distinct names disposed

| old name | personas carrying it | disposition |
|---|---|---|
| `file_write` | adversary, ambiguity, auditor, clerk, evaluator, hunter, negotiator, strategist, verifier, wargamer | KEPT → `permission: {edit: deny}` (`DENY_MAP`) |
| `web_scrape` | adversary, ambiguity, architect, auditor, clerk, evaluator, hunter, ingestor, negotiator, strategist, verifier, wargamer | KEPT → `permission: {webfetch: deny}` (`DENY_MAP`) |
| `shell_exec` | same set as `web_scrape` | KEPT → `permission: {bash: deny}` (`DENY_MAP`) |
| `web_search` | auditor | KEPT → `permission: {webfetch: deny}` (`DENY_MAP`) |
| `cognee_search` | ambiguity, auditor | REMOVED from `denied_tools` — no ported equivalent, so the denial is vacuous (nothing to deny); retrieval lands with A-4 |
| `ppsr_search` | clerk, evaluator, strategist | REMOVED from `denied_tools` — no ported equivalent; external-register access is out of S7c scope |
| `companies_office` | evaluator | REMOVED from `denied_tools` — no ported equivalent; external-register access is out of S7c scope |

The `DENY_MAP` names (`file_write`, `web_scrape`, `shell_exec`, `web_search`)
stay: each names an OpenCode builtin this mount does have. The three removed
names have no equivalent at all — denying a tool that does not exist is
vacuous, and an unexplained residue in the index would read as a silent drop's
twin.

### Measured end state

`auditor` is the only persona with an ENABLED tool: `ironfleet_statutory_demand`
(ported → the generator writes `tools: {ironfleet_statutory_demand: true}` into
`auditor.md`), plus FIVE deferred rows recorded in its `# deferred` ledger
(`ironfleet_solvency_assessor`, `ironfleet_penalty_clause`,
`ironfleet_imca_2016`, `ironfleet_limitation_act`,
`ironfleet_security_interest`). `negotiator`, `strategist` and `wargamer` each
carry ONE deferred reference (`ironfleet_limitation_act`) and no enabled tool.
Every other persona ends with an empty `allowed_tools`; hunter and clerk have no
tool references at all, which is correct for the acceptance spine. Exactly one
persona gains an enabled tool — a measured fact, not a failure.
