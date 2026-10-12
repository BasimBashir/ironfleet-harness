# CUTOVER RULING — old IronFleet → the gated harness (CR-6)

> **Status: DRAFT for Jonathan's ruling** (S7j-W step 3). One page; each open question is
> boxed and answerable in one line. Written 2026-10-12.
> Evidence base: `..\IronFleet\legalai` surveyed 2026-10-12 (sizes + store inventory below);
> ship state per NEXT_STEPS.md (S7j-W step 2's distribution, acceptance ladder R1–R6).

## The scope question (decides the size of this step)

**Q1. Does any real user depend on the old tree today?**
Next Steps already records the rule: if not, this shrinks from a 14h parallel-run step to a
**recorded decision + a migration script**. The survey supports the small shape:

- `case_vault/`: one matter-shaped directory (`d4169ad6aa323208`) + `_bench` — reads as
  bench/synthetic, not an active matter store. **Q1a: is `d4169ad6aa323208` real matter
  data that must migrate, or bench?**
- `data/hermes/` (41 MB): old-stack runtime data. **Q1b: migrate or drop?**
- `databases/`: init scripts for **neo4j / postgres / redis under Docker**. The programme
  rule forbids container lifecycle ops on the old tree, so any state living in those
  containers is out of reach until the user chooses to export it. **Q1c: is anything live
  in those containers?** (If yes: the export is a one-off user-run `docker` command, listed
  in the migration script's header, not automated.)

**Recommendation: take the small shape** — a recorded decision + a migration script that
copies `case_vault/d4169ad6aa323208` (if Q1a = real) into the new store's
`matters/<ref>/` registry form, with the hermes/container answers above deciding the rest.

## Switch-off criteria (what "cut over" means)

The old tree is switched off when ALL of these hold:

1. The new stack passes its acceptance ladder through R1 (citation-RAG product layer) —
   the MVP alone is not the old tree's replacement for real work; R1 is.
2. One real matter has run END-TO-END on the new stack: ingest → gated dispatch → guarded
   draft → memory-improved persona (the drive smoke proves the plumbing; this proves the work).
3. Whatever Q1a/Q1b/Q1c surface as real has been migrated and verified in the new store
   (`matters/<ref>/matter.json` + trace rows carrying its ref).
4. Jonathan records the switch-off date here. Until then the old tree stays read-only by
   convention — no new matters into the old stack.

## Parked decisions riding this ruling

| Item | The ask | Recommendation |
|---|---|---|
| **CR-7 BitLocker** (2026-08-26 deviation) | Ratify the operator's `-AcceptUnencryptedStore` on this dev PC, or require an encrypted store before any real matter | Ratify for dev; REQUIRE encryption before real matter data (the store setup script already fail-louds by default) |
| **CR-3 amendment** (Ollama evidence) | Accept server-reported digest + residency as backend evidence (parity with llama.cpp declared sha256), upgrading Ollama legs `mechanical-only` → still not `verified` without an engine report — or leave frozen | Leave FROZEN for the MVP ship: `verified=0` is honest and the gate's tier logic already does the right thing; revisit only if a cloud-tier refusal ever blocks real work |
| **BATCH.md drops** (S7c) | Note `what_if_dashboard` (649-line tool + 4,556 guarded lines, unreferenced) and `nutrient_processor` (cloud egress) as ruled-out of the MVP | Record as out-of-scope for MVP; revisit on user demand |

## What this ruling does NOT decide

- R4 (MCP policy) — separate ruling, costed before exposure.
- The R1 RAG research gate — already directed (survey before code).
