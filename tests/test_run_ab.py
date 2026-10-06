# tests/test_run_ab.py — resumable sidecars, empty-content detection, one stubbed leg end to end.
# No network: run_leg accepts a pre-built registry + in-memory keys, so the probe is never called.
import json
import pytest
from pathlib import Path

from harness.eval.substitute import ModelUnderTest
from harness.gate import EgressGate, LLMRequest
from harness.policy import RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore

import scripts.run_ab as run_ab

LEG = ModelUnderTest(label="stub", role="candidate", provider="stub", model="stub-model",
                     engine="cloud", output_cap=128, rate_key="x")


def _cases(tmp_path, n=3):
    d = tmp_path / "cases"
    d.mkdir(exist_ok=True)
    for i in range(n):
        (d / f"c{i}.yaml").write_text(
            f"id: c{i}\nmatter_type: m\ntask_class: analysis\nprompt: q{i}\n"
            f"expected_citations: ['[Act, s 1]']\nrequired_grounding: []\npersona_checks: {{}}\n",
            encoding="utf-8")
    return d


def _registry(admitted="full"):
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="stub", base_url="http://s/v1", model="stub-model",
                              engine="cloud", tier="cloud", admitted=admitted))
    return reg


def _routing():
    return RoutingTable(rules=[], defaults={"local_only": ["stub"], "local_preferred": ["stub"],
                                            "cloud_permitted": ["stub"]})


def _content_transport(text="answer citing [Act, s 1]"):
    async def _call(provider, payload):
        return {"choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}}
    return _call


@pytest.mark.asyncio
async def test_run_leg_writes_one_record_per_case_and_scores(tmp_path):
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=_registry(), routing=_routing(), trace=trace,
                      transport=_content_transport())
    n = await run_ab.run_leg(LEG, run_ab.load_cases(_cases(tmp_path)), tmp_path, trace,
                             registry=_registry(), keys={"stub": "k"}, atria_key="", ollama_url="",
                             gate=gate)
    assert n == 3
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    assert [r["id"] for r in recs] == ["c0", "c1", "c2"]
    assert all(r["status"] == "ok" for r in recs)
    assert recs[0]["citation_accuracy"] == pytest.approx(1.0)   # the needle is present
    assert recs[0]["tokens_in"] == 12 and recs[0]["tokens_out"] == 8


@pytest.mark.asyncio
async def test_empty_content_channel_is_recorded_not_scored_as_zero(tmp_path):
    # a reasoning model can spend the whole budget on reasoning_content and return content: null.
    # That is a CAP failure, not a quality failure — the record keeps its tokens_out so the runner
    # can tell the difference, and it is recall-eligible at a larger cap.
    async def _call(provider, payload):
        return {"choices": [{"index": 0, "finish_reason": "length",
                             "message": {"role": "assistant", "content": None,
                                         "reasoning_content": "thinking..."}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 128, "total_tokens": 138}}
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=_registry(), routing=_routing(), trace=trace, transport=_call)
    await run_ab.run_leg(LEG, run_ab.load_cases(_cases(tmp_path, 1)), tmp_path, trace,
                         registry=_registry(), keys={"stub": "k"}, atria_key="", ollama_url="",
                         gate=gate)
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    assert recs[0]["status"] == "empty_content"
    assert recs[0]["tokens_out"] == 128 and recs[0]["content"] is None


@pytest.mark.asyncio
async def test_a_failed_case_is_recorded_and_the_leg_continues(tmp_path):
    async def _call(provider, payload):
        raise RuntimeError("upstream failure")
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=_registry(), routing=_routing(), trace=trace, transport=_call)
    n = await run_ab.run_leg(LEG, run_ab.load_cases(_cases(tmp_path, 2)), tmp_path, trace,
                             registry=_registry(), keys={"stub": "k"}, atria_key="", ollama_url="",
                             gate=gate)
    assert n == 0                       # nothing scored
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    assert all(r["status"] == "failed" for r in recs)
    assert "upstream failure" in recs[0]["error"]


def test_pending_skips_cases_already_scored():
    records = [{"id": "c0", "status": "ok"}, {"id": "c1", "status": "failed"},
               {"id": "c2", "status": "empty_content"}]
    assert run_ab.pending(records, ["c0", "c1", "c2", "c3"], recall=()) == ["c1", "c2", "c3"]


@pytest.mark.asyncio
async def test_latency_ms_in_the_record_matches_the_traced_dispatch(tmp_path):
    # the gate measures latency into the trace; the sidecar must carry it because
    # substitute.amortized_rate_entry prices a local leg from the sidecar's latency_ms alone.
    async def _call(provider, payload):
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "ans"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=_registry(), routing=_routing(), trace=trace, transport=_call)
    await run_ab.run_leg(LEG, run_ab.load_cases(_cases(tmp_path, 1)), tmp_path, trace,
                         registry=_registry(), keys={"stub": "k"}, atria_key="", ollama_url="",
                         gate=gate)
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    tr = trace.by_matter("eval-a7:stub:c0")[-1]
    assert recs[0]["latency_ms"] == tr.latency_ms


@pytest.mark.asyncio
async def test_a_failed_dispatch_still_records_its_latency(tmp_path):
    async def _call(provider, payload):
        raise RuntimeError("upstream failure")
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=_registry(), routing=_routing(), trace=trace, transport=_call)
    await run_ab.run_leg(LEG, run_ab.load_cases(_cases(tmp_path, 1)), tmp_path, trace,
                         registry=_registry(), keys={"stub": "k"}, atria_key="", ollama_url="",
                         gate=gate)
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    tr = trace.by_matter("eval-a7:stub:c0")[-1]
    assert recs[0]["status"] == "failed"
    assert recs[0]["latency_ms"] == tr.latency_ms


def test_recall_reruns_the_named_cases_even_if_scored():
    records = [{"id": "c0", "status": "ok"}, {"id": "c1", "status": "ok"}]
    assert run_ab.pending(records, ["c0", "c1"], recall=("c0",)) == ["c0"]


def test_pending_takes_the_last_record_per_case():
    # append-only sidecar: a superseded record stays in the file; the LAST one per id is effective
    records = [{"id": "c0", "status": "failed"}, {"id": "c0", "status": "ok"}]
    assert run_ab.pending(records, ["c0"], recall=()) == []


@pytest.mark.asyncio
async def test_resume_skips_completed_cases_and_appends_the_rest(tmp_path):
    sidecar = tmp_path / "A7-stub.jsonl"
    sidecar.write_text(json.dumps({"id": "c0", "status": "ok", "citation_accuracy": 1.0,
                                   "grounding_score": 1.0, "persona_rate": 1.0, "checks": {},
                                   "tokens_in": 1, "tokens_out": 1, "latency_ms": 1, "error": ""}) + "\n",
                       encoding="utf-8")
    trace = TraceStore(tmp_path / "t.db")
    gate = EgressGate(registry=_registry(), routing=_routing(), trace=trace,
                      transport=_content_transport())
    await run_ab.run_leg(LEG, run_ab.load_cases(_cases(tmp_path, 3)), tmp_path, trace,
                         registry=_registry(), keys={"stub": "k"}, atria_key="", ollama_url="",
                         gate=gate)
    recs = run_ab.load_sidecar(sidecar)
    ids = [r["id"] for r in recs]
    assert ids == ["c0", "c1", "c2"]        # c0 untouched (not re-dispatched), c1/c2 appended
    assert trace.summary()["dispatches"] == 2
