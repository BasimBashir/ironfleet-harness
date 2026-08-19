# tests/test_gate.py
import pytest
from harness.gate import EgressGate, LLMRequest, GateRefusal
from harness.policy import RoutingTable, MatterPolicy
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore

ROUTING = """rules: []
defaults:
  local_only: [mini1]
  local_preferred: [mini1, cloud]
  cloud_permitted: [cloud, mini1]
"""

def _gate(tmp_path, transport):
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="mini1", base_url="http://m/v1", engine="mlx-lm", tier="local",
                              model="qwen-30b",
                              declared_provenance={"weights_revision": "rev-1"}))
    reg.upsert(ProviderConfig(name="cloud", base_url="https://c/v1", engine="cloud", tier="cloud",
                              model="glm-5.2",
                              declared_provenance={"weights_revision": "glm@1"}))
    p = tmp_path / "r.yaml"; p.write_text(ROUTING)
    return EgressGate(registry=reg, routing=RoutingTable.from_yaml(p),
                      trace=TraceStore(tmp_path / "t.db"), transport=transport)

@pytest.mark.asyncio
async def test_dispatch_local_preferred_prefers_local_and_traces(tmp_path, fake_transport):
    gate = _gate(tmp_path, fake_transport)
    res = await gate.dispatch(LLMRequest(matter_ref="M-1", task_class="drafting",
                                         messages=[{"role": "user", "content": "draft"}]))
    assert res.provider == "mini1" and res.provenance.weights_revision == "rev-1"
    recs = gate.trace.by_matter("M-1")
    assert len(recs) == 1 and recs[0].provider == "mini1" and recs[0].verified == 1

@pytest.mark.asyncio
async def test_local_only_blocks_cloud_even_if_only_cloud_registered(tmp_path, fake_transport):
    gate = _gate(tmp_path, fake_transport)
    gate.registry.upsert(ProviderConfig(name="mini1", base_url="http://m/v1", engine="mlx-lm",
                                        tier="local", admitted="refused", model="qwen-30b"))
    with pytest.raises(GateRefusal):
        await gate.dispatch(LLMRequest(matter_ref="M-1", task_class="drafting",
                                       messages=[{"role": "user", "content": "x"}],
                                       classification="LOCAL_ONLY",))  # prefs = [mini1] only
    recs = gate.trace.by_matter("M-1")
    assert recs[0].status == "refused"                     # refusals are traced too
    assert recs[0].classification == "LOCAL_ONLY"          # the request's classification is what gated it

@pytest.mark.asyncio
async def test_unverified_provenance_marks_record_unverified(tmp_path):
    async def transport(provider, payload):                # no _server_meta at all
        return {"model": payload["model"], "choices": [{"message": {"content": "ans"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    gate = _gate(tmp_path, transport)
    await gate.dispatch(LLMRequest(matter_ref="M-2", task_class="drafting",
                                   messages=[{"role": "user", "content": "x"}]))
    assert gate.trace.by_matter("M-2")[0].verified == 0    # recorded honestly, not faked

@pytest.mark.asyncio
async def test_missing_model_refuses_instead_of_guessing(tmp_path, fake_transport):
    gate = _gate(tmp_path, fake_transport)
    for c in gate.registry.list():                        # strip default models
        gate.registry.upsert(c.model_copy(update={"model": ""}))
    with pytest.raises(GateRefusal):
        await gate.dispatch(LLMRequest(matter_ref="M-3", task_class="drafting",
                                       messages=[{"role": "user", "content": "x"}]))
    assert gate.trace.by_matter("M-3")[0].status == "refused"
