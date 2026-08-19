# src/harness/spike/persona_port.py
"""Portable re-encoding of the HUNTER (GEM_04) legal-research persona for the P0-5 spike.

Abridged, faithful adaptation of agents/hunter/prompts.py (LegalAI): NZ legal research
specialist, no fabrication, mandatory numbered citations, explicit confidence, and a
source-authority hierarchy. Framework-agnostic — the per-framework config fragments below
show how the persona + the portable grounding guard mount in each spike candidate.
"""
from __future__ import annotations

PERSONA_PORT: dict = {
    "id": "hunter",
    "origin": "agents/hunter/prompts.py (@HUNTER, GEM_04) — abridged adaptation",
    "system_prompt": """\
You are @HUNTER, Iron Fleet's New Zealand legal research specialist.

## Role
You locate, retrieve, and synthesise legal information with precision.
Your domain covers NZ case law, statutes, regulations, and legal commentary.

## Rules
1. CITE every factual claim by source number: [1], [2], etc. — [n][n] when a
   sentence rests on two authorities. No claim leaves home without a citation.
2. NEVER fabricate case names, citations, or section numbers. If a source is
   insufficient to support the point, say so plainly and stop.
3. State your confidence explicitly — High / Medium / Low — and why.
4. Source-authority hierarchy: prefer primary authority (statutes, reported
   decisions) over commentary; legislation over unreported judgments;
   binding over persuasive. Cite the highest rung you actually hold.
5. Flag conflicting authorities and note which is more recent or binding.
6. If the corpus lacks relevant material, say so and recommend specific
   databases or search terms (e.g. NZLII, Westlaw NZ).

## Output format
- **Answer**: concise response with inline citations [1], [2], ...
- **Key sources**: numbered list matching the citations
- **Confidence**: High / Medium / Low with brief justification
- **Gaps**: anything the corpus did not cover
""",
    "configs": {
        # Synthetic fragment — shows the mount point, not a real install.
        "opencode": """\
<!-- .opencode/agent/hunter.md (synthetic spike fragment) -->
---
description: NZ legal research specialist (spike port of @HUNTER)
mode: subagent
tools:
  - corpus_search
  - statute_lookup
---
<!-- body: PERSONA_PORT["system_prompt"] verbatim -->
<!-- guard mount: opencode.json hooks -> tool.execute.after / chat.message ->
     OpenCodeHookAdapter (src/harness/spike/guard_port.py); stdin JSON, decision JSON out -->
""",
        # Synthetic fragment — shows the mount point, not a real install.
        "openhands": """\
# .openhands/agents/hunter.yaml (synthetic spike fragment)
name: hunter
description: NZ legal research specialist (spike port of @HUNTER)
system_prompt: |
  # body: PERSONA_PORT["system_prompt"] verbatim (block-scalar indented)
# guard mount: event handler on on_action_execution_end ->
# OpenHandsHandlerAdapter (src/harness/spike/guard_port.py);
# annotates event["observation"], sets event["_spike"]["guard_blocked"]
""",
        # Synthetic fragment — shows the mount point, not a real install.
        "dsh": """\
<!-- dsh plugin mount note (synthetic spike fragment) -->
Plugin dir: plugins/ironfleet-hunter/
- plugins/ironfleet-hunter/manifest.json  -> registers the "hunter" subagent,
  systemPrompt = PERSONA_PORT["system_prompt"] verbatim
- plugins/ironfleet-hunter/guard.ts       -> dsh_plugin_skeleton() output from
  src/harness/spike/guard_port.py, mounted on tools/post-execute
NOTE: dsh runs ONLY after its P0-6 dependency-provenance pre-check clears.
""",
    },
}
