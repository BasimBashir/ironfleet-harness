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


class ReflectorError(RuntimeError):
    """The reflector returned neither a decline nor parseable memory JSON (spec §5)."""


REFLECT_SYSTEM = (
    "You maintain the operational memory of a legal-analysis agent. You will see the agent's "
    "persona, its current memory, and scored probe cases (prompt, output status, per-axis "
    "scores, expected citations/grounding/persona needles). Propose a REPLACEMENT for the "
    f"memory: at most {MAX_MEMORY_CHARS} characters, plain prose, no markdown headers, no "
    "HTML comments, no matter-identifying content. Reply with EXACTLY one JSON object and "
    "nothing else: {\"decline\": true} if no change would help, or "
    "{\"memory\": \"<full replacement text>\"}.")


def _extract_json(text: str) -> dict:
    """Tolerate fenced JSON (observed live on thomson1 in the spike); nothing else passes."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t.strip())


async def reflect(gate, agent: str, persona_body: str, canon: str,
                  triples: list[dict]) -> str | None:
    """The reflector's own dispatch is traced like every other (spec §3.4)."""
    user = json.dumps({"persona": persona_body, "current_memory": canon,
                       "probe_cases": triples}, ensure_ascii=False)
    resp = await gate.dispatch(LLMRequest(
        matter_ref=f"agent-memory:{agent}:reflector", task_class=REFLECTOR_TASK,
        messages=[{"role": "system", "content": REFLECT_SYSTEM},
                  {"role": "user", "content": user}],
        max_tokens=OUTPUT_CAP))
    if resp.content is None:
        raise ReflectorError("reflector content channel empty under output cap")
    try:
        doc = _extract_json(resp.content)
    except (ValueError, json.JSONDecodeError) as ex:
        raise ReflectorError(f"unparseable reflector output: {ex}") from ex
    if doc.get("decline") is True:
        return None
    if not isinstance(doc.get("memory"), str) or not doc["memory"].strip():
        raise ReflectorError("reflector output has neither decline nor a memory string")
    return doc["memory"]


def _triples(records: list[dict], cases: list[GoldenCase]) -> list[dict]:
    by_id = {c.id: c for c in cases}
    return [{"prompt": (c := by_id[r["case_id"]]).prompt, "output_status": r["status"],
             "citation_accuracy": r["citation_accuracy"],
             "grounding_score": r["grounding_score"], "checks": r["checks"],
             "expected_citations": c.expected_citations,
             "required_grounding": c.required_grounding,
             "persona_checks": c.persona_checks} for r in records]


def _decide_and_record(store, agent, pid, stage,
                       current_means, proposed_means) -> tuple[bool, dict]:
    keep, deltas = compare(current_means, proposed_means)
    store.record_leg(agent, pid, stage, "current", current_means)
    store.record_leg(agent, pid, stage, "proposed", proposed_means)
    status = "kept" if keep else "rolled_back"
    if pid is not None:
        store.decide(pid, status, f"{stage} deltas {json.dumps(deltas)}")
    return keep, deltas


async def screen(store, gate, agent: str, persona_body: str, cases: list[GoldenCase]) -> dict:
    """One propose iteration (spec §3.4): drive the current canon over the probe suite,
    reflect, validate, drive the proposal, screen. The screen verdict decides only whether
    the full confirm is worth its ~70 minutes."""
    suite_ids = store.suite(agent)
    probe = [c for c in cases if c.id in set(suite_ids)]
    if not probe:
        raise RuntimeError(f"{agent}: no probe suite — genesis (init) first")
    cur_body, cur_ver = store.get(agent)
    current = await drive_leg(gate, system_for(persona_body, cur_body, cur_ver), probe,
                              f"agent-memory:{agent}")
    raw = await reflect(gate, agent, persona_body, cur_body, _triples(current, probe))
    if raw is None:
        return {"status": "no_proposal"}
    try:
        body = validate_proposal(raw)
    except ProposalRejected as ex:
        pid = store.propose(agent, raw)          # stored as-is for the audit trail, never applied
        store.decide(pid, "rejected", str(ex))
        return {"status": "rejected", "reason": str(ex), "proposal_id": pid}
    pid = store.propose(agent, body)
    proposed = await drive_leg(gate, system_for(persona_body, body, pid), probe,
                               f"agent-memory:{agent}:p{pid}")
    try:
        keep, _ = _decide_and_record(store, agent, pid, "screen",
                                     leg_means(current, len(probe)),
                                     leg_means(proposed, len(probe)))
    except UnusableLeg as ex:
        store.decide(pid, "rejected", f"unusable screen leg: {ex}")
        return {"status": "rejected", "reason": str(ex), "proposal_id": pid}
    if not keep:
        return {"status": "rolled_back", "proposal_id": pid}
    verdict = await confirm(store, gate, agent, persona_body, cases, pid,
                            proposal_body=body, current_body=cur_body, current_version=cur_ver)
    return {"status": verdict, "proposal_id": pid, "version": store.get(agent)[1]}


async def confirm(store, gate, agent: str, persona_body: str, cases: list[GoldenCase],
                  pid: int, *, proposal_body: str, current_body: str,
                  current_version: int) -> str:
    """The full-corpus pair; ITS verdict is the decision (spec §3.4)."""
    current = await drive_leg(gate, system_for(persona_body, current_body, current_version),
                              cases, f"agent-memory:{agent}:confirm-c{pid}")
    proposed = await drive_leg(gate, system_for(persona_body, proposal_body, pid),
                               cases, f"agent-memory:{agent}:confirm-p{pid}")
    keep, _ = _decide_and_record(store, agent, pid, "confirm",
                                 leg_means(current, len(cases)),
                                 leg_means(proposed, len(cases)))
    if keep:
        store.set(agent, proposal_body, f"proposal {pid} confirmed")
        return "kept"
    return "rolled_back"


async def propose_cmd(store, gate, agent: str, persona_body: str, cases: list[GoldenCase],
                      manual_body: str | None) -> dict:
    """`propose` subcommand: the reflector path, or the manual path (--body) a human seeds
    straight into the confirm (spec §7 C2's seeded variant)."""
    if manual_body is not None:
        try:
            body = validate_proposal(manual_body)
        except ProposalRejected as ex:
            pid = store.propose(agent, manual_body)
            store.decide(pid, "rejected", str(ex))
            return {"status": "rejected", "reason": str(ex), "proposal_id": pid}
        pid = store.propose(agent, body)
        cur_body, cur_ver = store.get(agent)
        verdict = await confirm(store, gate, agent, persona_body, cases, pid,
                                proposal_body=body, current_body=cur_body,
                                current_version=cur_ver)
        return {"status": verdict, "proposal_id": pid, "version": store.get(agent)[1]}
    return await screen(store, gate, agent, persona_body, cases)
