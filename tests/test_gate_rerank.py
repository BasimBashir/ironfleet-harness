# tests/test_gate_rerank.py — R1 plan Task 5, spec 14 D3: rerank as a structurally
# LOCAL_ONLY gate dispatch class, sibling of embed(). Fixtures mirror test_gate.py's
# embed fixtures (the S7e patterns: adversarial cloud refusal, refuse-never-truncate,
# index-alignment errors traced).
import pytest

from harness.gate import EgressGate
from harness.policy import LOCAL_ONLY_TASKS, MECHANICAL_TASKS, RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore

RR_ROUTING = """
aliases:
  gate/rerank: {task_class: rerank}
rules:
  - task_class: rerank
    local_only: [rr]
    local_preferred: [rr]
    cloud_permitted: [rr, rr-cloud]
defaults:
  local_only: []
  local_preferred: []
  cloud_permitted: []
"""


def _rr_gate(tmp_path, rerank_transport, routing=RR_ROUTING):
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="rr", base_url="http://m/v1", engine="llama.cpp",
                              tier="local", model="qwen3-reranker-0.6b",
                              admitted="mechanical-only"))
    reg.upsert(ProviderConfig(name="rr-cloud", base_url="https://c/v1", engine="cloud",
                              tier="cloud", model="cloud-rr-1", admitted="full"))
    p = tmp_path / "r.yaml"
    p.write_text(routing)
    return EgressGate(registry=reg, routing=RoutingTable.from_yaml(p),
                      trace=TraceStore(tmp_path / "t.db"), rerank_transport=rerank_transport)


def _rr_transport(scores, indexes=None):
    indexes = indexes if indexes is not None else list(range(len(scores)))

    async def _call(provider, payload):
        return {"model": payload["model"],
                "results": [{"index": i, "relevance_score": s}
                            for i, s in zip(indexes, scores)],
                "usage": {"prompt_tokens": 9, "total_tokens": 9}}
    return _call


def test_rerank_is_structurally_local_and_mechanical():
    # D3: quote scoring sends privileged draft+passage text — LOCAL_ONLY is a code-level
    # filter the routing table cannot relax; it is mechanical work like embedding.
    assert "rerank" in LOCAL_ONLY_TASKS and "rerank" in MECHANICAL_TASKS


@pytest.mark.asyncio
async def test_rerank_returns_scores_and_traces_one_row(tmp_path):
    from harness.gate import RerankRequest

    async def transport(provider, payload):
        assert payload["query"] == "when does property pass"
        assert payload["documents"] == ["a", "b"]
        assert "max_tokens" not in payload               # rerank does not generate
        return {"model": payload["model"],
                "results": [{"index": 0, "relevance_score": 0.99},
                            {"index": 1, "relevance_score": 0.01}],
                "usage": {"prompt_tokens": 9, "total_tokens": 9}}
    gate = _rr_gate(tmp_path, transport)
    res = await gate.rerank(RerankRequest(
        matter_ref="M-1", query="when does property pass", texts=["a", "b"]))
    assert res.scores == [0.99, 0.01]
    assert res.provider == "rr" and res.model == "qwen3-reranker-0.6b"
    recs = gate.trace.by_matter("M-1")
    assert len(recs) == 1 and recs[0].task_class == "rerank" and recs[0].status == "ok"
    assert recs[0].tokens_out == 0


def test_rerank_request_defaults_to_local_only():
    from harness.gate import RerankRequest
    req = RerankRequest(matter_ref="M", query="q", texts=["a"])
    assert req.classification == "LOCAL_ONLY" and req.max_texts == 64


@pytest.mark.asyncio
async def test_rerank_refuses_cloud_even_under_cloud_permitted(tmp_path):
    # the S7e C2 pattern at the gate: routing may list rr-cloud, rerank() must never
    # reach it; the local reranker FAILS so success could only come from the cloud one.
    from harness.gate import GateRefusal
    called = []

    async def transport(provider, payload):
        called.append(provider.name)
        if provider.name == "rr":
            raise RuntimeError("local reranker is down")
        return {"model": payload["model"],
                "results": [{"index": 0, "relevance_score": 0.5}], "usage": {}}
    gate = _rr_gate(tmp_path, transport)
    with pytest.raises(GateRefusal):
        await gate.rerank(_req(classification="CLOUD_PERMITTED"))
    assert called == ["rr"], f"cloud reranker was reached: {called}"


def _req(**kw):
    from harness.gate import RerankRequest
    return RerankRequest(matter_ref="M-1", query="q", texts=["a", "b"], **kw)


@pytest.mark.asyncio
async def test_rerank_misordered_results_are_an_error_not_silently_accepted(tmp_path):
    # the S7e embed lesson: a REVERSED response silently misaligns scores against
    # passages — alignment is enforced per index, violations are traced then raised.
    from harness.gate import GateRefusal
    gate = _rr_gate(tmp_path, _rr_transport([0.9, 0.1], indexes=[1, 0]))
    with pytest.raises(GateRefusal):
        await gate.rerank(_req())
    recs = gate.trace.by_matter("M-1")
    assert recs[0].status == "error"


@pytest.mark.asyncio
async def test_rerank_duplicate_index_is_an_error(tmp_path):
    from harness.gate import GateRefusal
    gate = _rr_gate(tmp_path, _rr_transport([0.9, 0.1], indexes=[0, 0]))
    with pytest.raises(GateRefusal):
        await gate.rerank(_req())


@pytest.mark.asyncio
async def test_rerank_batch_over_max_texts_is_refused_not_truncated(tmp_path):
    from harness.gate import GateRefusal
    gate = _rr_gate(tmp_path, _rr_transport([0.5]))
    with pytest.raises(GateRefusal):
        await gate.rerank(_req(max_texts=1))
    assert gate.trace.by_matter("M-1")[0].status == "refused"


@pytest.mark.asyncio
async def test_rerank_empty_texts_refused(tmp_path):
    from harness.gate import GateRefusal, RerankRequest
    gate = _rr_gate(tmp_path, _rr_transport([]))
    with pytest.raises(GateRefusal):
        await gate.rerank(RerankRequest(matter_ref="M-1", query="q", texts=[]))
    assert gate.trace.by_matter("M-1")[0].status == "refused"
