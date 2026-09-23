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
