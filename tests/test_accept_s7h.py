# tests/test_accept_s7h.py — the driver's pure checks against fixtures (spec §11). C6 is live and
# is exercised only by the driver itself, not here.
import json
import pytest
from pathlib import Path

import scripts.accept_s7h as acc
import scripts.run_ab as run_ab


def _ok(cid, leg="thomson1-chat"):
    return {"id": cid, "leg": leg, "status": "ok", "citation_accuracy": 0.5,
            "grounding_score": 0.5, "persona_rate": 1.0, "tokens_in": 100, "tokens_out": 50,
            "latency_ms": 1000, "checks": {}, "error": ""}


def test_c1_passes_when_every_case_is_accounted_for(tmp_path):
    ids = [f"gc-{i:03d}" for i in range(30)]
    sidecars = {l.label: [_ok(i, l.label) for i in ids] for l in run_ab.LEGS}
    assert acc.check_c1(sidecars, ids) == []


def test_c1_fails_on_a_missing_case(tmp_path):
    ids = [f"gc-{i:03d}" for i in range(30)]
    sidecars = {l.label: [_ok(i, l.label) for i in ids] for l in run_ab.LEGS}
    sidecars["thomson1-chat"].pop()                      # one case unaccounted for
    problems = acc.check_c1(sidecars, ids)
    assert len(problems) == 1 and "gc-029" in problems[0]


def test_c1_counts_failed_cases_as_accounted_for(tmp_path):
    # a failed case is still an outcome the run recorded — C1 asks for completeness, not success
    ids = ["c0", "c1"]
    sidecars = {l.label: [_ok("c0", l.label), {**_ok("c1", l.label), "status": "failed"}]
                for l in run_ab.LEGS}
    assert acc.check_c1(sidecars, ids) == []


def test_c2_recomputes_cost_independently_and_matches(tmp_path):
    # an INDEPENDENT arithmetic path (no cost_of) — a wiring bug in the shared code must not pass
    sidecars = {"Atria-Dawn-Preview": [
        {"id": "c0", "leg": "Atria-Dawn-Preview", "status": "ok", "tokens_in": 3000,
         "tokens_out": 2000, "latency_ms": 500}]}
    claims = {"Atria-Dawn-Preview": (3000 * 1.40 + 2000 * 4.40) / 1_000_000}   # $/case, same rate
    assert acc.check_c2(sidecars, claims, in_per_m=1.40, out_per_m=4.40) == []


def test_c2_fails_when_a_claimed_cost_does_not_recompute(tmp_path):
    sidecars = {"Atria-Dawn-Preview": [
        {"id": "c0", "leg": "Atria-Dawn-Preview", "status": "ok", "tokens_in": 3000,
         "tokens_out": 2000, "latency_ms": 500}]}
    claims = {"Atria-Dawn-Preview": 99.0}                 # cannot come from these tokens
    assert acc.check_c2(sidecars, claims, in_per_m=1.40, out_per_m=4.40)


def test_c2_skips_a_blended_local_leg(tmp_path):
    # Ruling 2026-10-06: a local leg is priced by its DERIVED blended rate, not the cloud split
    # rates, so C2 must SKIP it rather than fail a claim those rates were never used for. Local
    # legs are covered structurally by C3, which recomputes them end-to-end through the real
    # leg_summaries.
    sidecars = {"thomson1-chat": [
        {"id": "c0", "leg": "thomson1-chat", "status": "ok", "tokens_in": 3000,
         "tokens_out": 2000, "latency_ms": 500}]}
    claims = {"thomson1-chat": 99.0}            # deliberately wrong — and deliberately irrelevant
    assert acc.check_c2(sidecars, claims, in_per_m=1.40, out_per_m=4.40) == []


def test_c3_recomputes_the_bar_and_recommendation(tmp_path):
    # incumbent 0.5/0.5/1.0 on one case; one candidate matches, one regresses
    inc = {"thomson1-chat": [_ok("c0")]}
    good = {"Atria-Dawn-Preview": [{**_ok("c0"), "leg": "Atria-Dawn-Preview",
                                    "citation_accuracy": 0.9}]}
    bad = {"qwen3.8:27b": [{**_ok("c0"), "leg": "qwen3.8:27b", "citation_accuracy": 0.1}]}
    sidecars = {**inc, **good, **bad}
    problems = acc.check_c3(sidecars, expected_recommendation="Atria-Dawn-Preview")
    assert problems == []


def test_c3_fails_when_the_recommendation_does_not_follow_the_numbers(tmp_path):
    sidecars = {"thomson1-chat": [_ok("c0")],
                "Atria-Dawn-Preview": [{**_ok("c0"), "leg": "Atria-Dawn-Preview",
                                        "citation_accuracy": 0.1}]}
    assert acc.check_c3(sidecars, expected_recommendation="Atria-Dawn-Preview")


def test_c5_resume_and_recall_semantics():
    records = [{"id": "c0", "status": "ok"}, {"id": "c1", "status": "failed"}]
    # plain resume redoes only what is not complete
    assert run_ab.pending(records, ["c0", "c1", "c2"], recall=()) == ["c1", "c2"]
    # recall redoes a named case even though it completed
    assert run_ab.pending(records, ["c0", "c1"], recall=("c0",)) == ["c0", "c1"]
    # a superseded record keeps its old row in the file; the LAST per id wins
    assert run_ab.pending([{"id": "c0", "status": "failed"}, {"id": "c0", "status": "ok"}],
                          ["c0"], recall=()) == []


@pytest.mark.asyncio
async def test_c4_retry_recovers_and_exhausts(tmp_path):
    # offline, deterministic: the wrapper redoes transient failures and stops at its ceiling
    assert await acc.check_c4() == []


def test_c7_empty_content_is_a_cap_failure_not_a_quality_failure(tmp_path):
    import asyncio
    from harness.gate import EgressGate
    from harness.policy import RoutingTable
    from harness.providers.config import ProviderConfig, ProviderRegistry
    from harness.trace import TraceStore

    async def _reasoning_only(provider, payload):
        return {"choices": [{"index": 0, "finish_reason": "length",
                             "message": {"role": "assistant", "content": None,
                                         "reasoning_content": "..."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 128, "total_tokens": 138}}

    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="stub", base_url="http://s/v1", model="m", engine="cloud",
                              tier="cloud", admitted="full"))
    # One trace store for the gate AND the leg: run_leg reads the row the gate wrote, so the two
    # must share it or the leg sees no dispatch and records a spurious failure.
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=reg,
                      routing=RoutingTable(rules=[], defaults={"local_only": ["stub"],
                                                               "local_preferred": ["stub"],
                                                               "cloud_permitted": ["stub"]}),
                      trace=trace, transport=_reasoning_only)
    leg = run_ab.ModelUnderTest(label="stub", provider="stub", model="m", engine="cloud",
                                output_cap=128, rate_key="x")

    async def _go():
        return await run_ab.run_leg(leg, acc._tiny_cases(tmp_path), tmp_path, trace,
                                    registry=reg, keys={}, atria_key="", ollama_url="", gate=gate)

    scored = asyncio.run(_go())
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    assert scored == 0
    assert recs[0]["status"] == "empty_content"
    assert recs[0]["tokens_out"] == 128            # the cap failure kept its token accounting
