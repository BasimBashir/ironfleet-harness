"""S7i: the self-improvement loop — per-agent memory, benchmarked keep-if-better (spec 12).

SRS §3.9 interfaces, as CLI subcommands:
  agent.memory.get      -> get <agent>
  agent.memory.propose  -> propose <agent> [--body "<manual proposal>"]
  agent.benchmark       -> benchmark <agent> --proposal <id>
  agent.history         -> history <agent> | revert <agent> <version>

Every LLM call dispatches through the egress gate (matter_ref "agent-memory:<agent>"), is
traced, and runs on the local provider only. Ollama's honest admission is mechanical-only
(CR-3); this eval-loop driver applies the recorded in-memory-only admission override
(2026-08-28 precedent — CR-3 and src/ untouched, verified=0 throughout).

Cost model (spec §3.3, stated plainly): memory improves at BENCHMARK cadence. A screen
iteration ≈ 2 × 5 cases (~12 min on thomson1) + one reflector call; a confirmed keep adds a
full-confirm pair ≈ 2 × 30 cases (~70 min). Nothing runs per-turn or per-session.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from harness.agent_memory import (AXES, MAX_MEMORY_CHARS, PROBE_SIZE, MemoryStore,
                                  ProposalRejected, UnusableLeg, apply_to_agent_md,
                                  compare, leg_means, select_probe, validate_proposal)
from harness.eval.golden_case import GoldenCase, load_cases
from harness.eval.scorers import score_case
from harness.gate import EgressGate, LLMRequest

CASES_DIR = ROOT / "data" / "golden_cases"
ROUTING = ROOT / "data" / "routing-a1.yaml"
MODULE_E = ROOT / "data" / "module-e"
OLLAMA_URL = "http://127.0.0.1:11434/v1"
LOCAL_MODEL = "thomson1-chat:latest"
PROVIDER = "ollama-local"
OUTPUT_CAP = 16384                     # thomson1 needs ≥16k: reasoning tokens precede content
REFLECTOR_TASK = "complex_reasoning"   # routed to the local provider by data/routing-a1.yaml


async def build_gate(trace_path: Path, *, registry=None) -> EgressGate:
    """The run_ab pattern, local-only: probe honestly, print the honest verdict, apply the one
    recorded in-memory override, route everything to the one provider."""
    from harness.policy import RoutingTable
    from harness.providers.config import ProviderRegistry
    from harness.providers.probe import register_provider
    from harness.trace import TraceStore
    if registry is None:
        registry = ProviderRegistry()
        res = await register_provider(PROVIDER, OLLAMA_URL, "ollama-nokey-needed",
                                      model=LOCAL_MODEL, engine="ollama", declared={},
                                      registry=registry, keychain_set={})
        print(f"[probe] {PROVIDER}: reachable={res.reachable} auth_ok={res.auth_ok} "
              f"verified={int(res.provenance.verified)} -> honest admission={res.admission}")
        if res.admission == "refused":
            raise RuntimeError(f"probe refused {PROVIDER} — the loop cannot run")
        registry.get(PROVIDER).admitted = "full"
        print("[deviation] in-memory admission override for this eval loop "
              "(user-directed 2026-08-28 precedent; CR-3 and src/ untouched; traced verified=0)")
    rules = []   # single provider for every class — the leg's own table (run_ab._routing_for)
    defaults = {"local_only": [PROVIDER], "local_preferred": [PROVIDER],
                "cloud_permitted": [PROVIDER]}
    return EgressGate(registry=registry, routing=RoutingTable(rules=rules, defaults=defaults),
                      trace=TraceStore(trace_path))


def system_for(persona_body: str, memory_body: str, version: int) -> str:
    """The drive-time system prompt: exactly what the mount renders (spec §3.3)."""
    if not memory_body:
        return persona_body
    return persona_body + "\n\n" + apply_to_agent_md("", memory_body, version)


async def drive_leg(gate, system: str, cases: list[GoldenCase],
                    matter_prefix: str) -> list[dict]:
    """One leg over the given cases (spec §3.4). Per-case failure never aborts the leg —
    the S6-3/run_ab precedent: a refusal is an outcome, not a crash."""
    records: list[dict] = []
    for case in cases:
        matter = f"{matter_prefix}:{case.id}"
        try:
            resp = await gate.dispatch(LLMRequest(
                matter_ref=matter, task_class=case.task_class,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": case.prompt}],
                max_tokens=OUTPUT_CAP))
        except Exception as ex:                              # noqa: BLE001 — record, keep going
            records.append({"case_id": case.id, "status": "failed",
                            "citation_accuracy": 0.0, "grounding_score": 0.0,
                            "checks": {}, "passed": False,
                            "error": f"{type(ex).__name__}: {ex}"})
            continue
        if resp.content is None:                             # cap failure (S7h finding-1 shape)
            records.append({"case_id": case.id, "status": "empty_content",
                            "citation_accuracy": 0.0, "grounding_score": 0.0,
                            "checks": {}, "passed": False,
                            "error": "content channel empty under output cap"})
            continue
        s = score_case(resp.content, case)
        records.append({"case_id": case.id, "status": "scored",
                        "citation_accuracy": s.citation_accuracy,
                        "grounding_score": s.grounding_score,
                        "checks": s.checks, "passed": s.passed, "error": ""})
    return records
