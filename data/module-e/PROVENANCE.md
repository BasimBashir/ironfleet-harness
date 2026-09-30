# Module E persona corpus — provenance

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
`nzlii_search`, `nz-statutory-demand-validator`) — Task 9 reconciles them
against the new tool manifest.

`manager` is excluded: it is the supervisor layer, not a persona (Task 3's
routing layer).

## Skill documents (Task 8)

Each SKILL.md below is copied from the old tree
(`C:\Users\mianx\OneDrive\Desktop\IronFleet\legalai\skills\`) to
`data/module-e/skills/<name>/SKILL.md`. Only the SKILL.md documents port: the
old tree's per-skill `scripts/`, `tests/` and `docs/` subdirs and its top-level
`skill_loader.py`, `manifest.lock` and `__init__.py` do not (the scripts port
with their tools in the batch task).

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
