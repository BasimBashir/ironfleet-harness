# tests/test_gate.py
import pytest
from harness.gate import EgressGate, LLMRequest, GateRefusal
from harness.policy import RoutingTable
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
                              model="qwen-30b", admitted="full",      # as the probe would admit it
                              declared_provenance={"weights_revision": "rev-1"}))
    reg.upsert(ProviderConfig(name="cloud", base_url="https://c/v1", engine="cloud", tier="cloud",
                              model="glm-5.2", admitted="full",
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
async def test_server_revision_mismatching_declared_is_not_verified(tmp_path):
    # S6-2: dispatch-time verified uses the probe's semantics — a server-REPORTED revision
    # only counts when it MATCHES the declared (pinned) one. A different revision means
    # the endpoint is no longer serving what was probed -> verified=0.
    async def transport(provider, payload):                # reports a foreign revision
        return {"model": payload["model"], "choices": [{"message": {"content": "ans"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "_server_meta": {"engine": "mlx-lm", "weights_revision": "rev-OTHER"}}
    gate = _gate(tmp_path, transport)
    resp = await gate.dispatch(LLMRequest(matter_ref="M-4", task_class="drafting",
                                          messages=[{"role": "user", "content": "x"}]))
    assert resp.provenance.verified is False
    assert gate.trace.by_matter("M-4")[0].verified == 0    # reported != declared rev-1

@pytest.mark.asyncio
async def test_missing_model_refuses_instead_of_guessing(tmp_path, fake_transport):
    gate = _gate(tmp_path, fake_transport)
    for c in gate.registry.list():                        # strip default models
        gate.registry.upsert(c.model_copy(update={"model": ""}))
    with pytest.raises(GateRefusal):
        await gate.dispatch(LLMRequest(matter_ref="M-3", task_class="drafting",
                                       messages=[{"role": "user", "content": "x"}]))
    assert gate.trace.by_matter("M-3")[0].status == "refused"

@pytest.mark.asyncio
async def test_default_transport_omits_auth_header_when_no_key(monkeypatch, tmp_path, fake_transport):
    import harness.providers.http_fetch as hf
    captured: dict = {}
    async def fake_fetch(url, headers, payload=None):
        captured["url"], captured["headers"] = url, headers
        return {"model": "m", "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    monkeypatch.setattr(hf, "openai_fetch", fake_fetch)
    monkeypatch.setattr("harness.keychain._kv", {})          # empty keychain
    gate = _gate(tmp_path, fake_transport)
    await gate._default_transport(gate.registry.get("mini1"), {"model": "qwen-30b"})
    assert "Authorization" not in captured["headers"]        # no "Bearer " illegal header
    monkeypatch.setattr("harness.keychain._kv", {"mini1": "sk-real"})
    await gate._default_transport(gate.registry.get("mini1"), {"model": "qwen-30b"})
    assert captured["headers"].get("Authorization") == "Bearer sk-real"
