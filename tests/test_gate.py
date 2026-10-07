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

@pytest.mark.asyncio
async def test_provider_output_cap_clamps_max_tokens(tmp_path):
    # S6-4: strict APIs 400 on the generous 128k default. A provider carrying its own
    # output cap gets the request clamped to it before dispatch (ceiling, not floor).
    seen: list[int] = []
    async def transport(provider, payload):
        seen.append(payload["max_tokens"])
        return {"model": payload["model"], "choices": [{"message": {"content": "ans"}}]}
    gate = _gate(tmp_path, transport)
    capped = gate.registry.get("mini1").model_copy(update={"max_output_tokens": 4096})
    gate.registry.upsert(capped)
    await gate.dispatch(LLMRequest(matter_ref="M-5", task_class="drafting",
                                   messages=[{"role": "user", "content": "x"}]))   # default 128k
    await gate.dispatch(LLMRequest(matter_ref="M-5", task_class="drafting",
                                   messages=[{"role": "user", "content": "x"}], max_tokens=2048))
    assert seen == [4096, 2048]                       # clamped down / request below cap unchanged

@pytest.mark.asyncio
async def test_backend_wire_meta_wins_over_probe_finding(tmp_path):
    # Dispatch-time evidence is fresher than registration-time: if the server ever reports
    # a backend on the wire, it outranks the probe's earlier finding (S7d rule).
    async def transport(provider, payload):
        return {"model": payload["model"], "choices": [{"message": {"content": "ans"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "_server_meta": {"engine": "llamacpp", "backend": "from-wire",
                                 "weights_revision": "rev-1"}}
    gate = _gate(tmp_path, transport)
    gate.registry.upsert(gate.registry.get("mini1").model_copy(
        update={"discovered_backend": "from-probe"}))
    res = await gate.dispatch(LLMRequest(matter_ref="M-6", task_class="drafting",
                                         messages=[{"role": "user", "content": "x"}]))
    assert res.provenance.backend == "from-wire"
    assert gate.trace.by_matter("M-6")[0].backend == "from-wire"   # row and response agree

@pytest.mark.asyncio
async def test_backend_probe_finding_fills_when_wire_silent(tmp_path, fake_transport):
    # conftest's fake_transport _server_meta carries engine+weights_revision but NO backend
    # key — the shape of every real OpenAI-compatible endpoint today.
    gate = _gate(tmp_path, fake_transport)
    gate.registry.upsert(gate.registry.get("mini1").model_copy(
        update={"discovered_backend": "from-probe"}))
    res = await gate.dispatch(LLMRequest(matter_ref="M-7", task_class="drafting",
                                         messages=[{"role": "user", "content": "x"}]))
    assert res.provenance.backend == "from-probe"
    assert gate.trace.by_matter("M-7")[0].backend == "from-probe"

@pytest.mark.asyncio
async def test_backend_empty_and_unverified_when_no_source(tmp_path):
    # The Ollama shape: no wire meta, probe found nothing. Both fields stay honest-zeros.
    async def transport(provider, payload):                # no _server_meta at all
        return {"model": payload["model"], "choices": [{"message": {"content": "ans"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    gate = _gate(tmp_path, transport)
    res = await gate.dispatch(LLMRequest(matter_ref="M-8", task_class="drafting",
                                         messages=[{"role": "user", "content": "x"}]))
    assert res.provenance.backend == ""
    row = gate.trace.by_matter("M-8")[0]
    assert row.backend == "" and row.verified == 0

# --- A-4: the embedding dispatch path (gate.embed) ------------------------------------

EMB_ROUTING = """rules:
  - task_class: embedding
    local_only: [emb]
    local_preferred: [emb]
    cloud_permitted: [emb, emb-cloud]
defaults:
  local_only: []
  local_preferred: []
  cloud_permitted: []
"""

def _emb_gate(tmp_path, embedding_transport, routing=EMB_ROUTING):
    from harness.gate import EgressGate
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="emb", base_url="http://m/v1", engine="ollama", tier="local",
                              model="bge-m3:567m", admitted="mechanical-only"))
    reg.upsert(ProviderConfig(name="emb-cloud", base_url="https://c/v1", engine="cloud",
                              tier="cloud", model="cloud-emb-1", admitted="full"))
    p = tmp_path / "r.yaml"; p.write_text(routing)
    return EgressGate(registry=reg, routing=RoutingTable.from_yaml(p),
                      trace=TraceStore(tmp_path / "t.db"), embedding_transport=embedding_transport)

def _emb_transport(vectors):
    async def _call(provider, payload):
        return {"model": payload["model"],
                "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)],
                "usage": {"prompt_tokens": 12, "total_tokens": 12}}
    return _call

@pytest.mark.asyncio
async def test_embed_returns_vectors_and_traces_one_row(tmp_path):
    from harness.gate import EmbeddingRequest
    async def transport(provider, payload):
        assert payload["input"] == ["a", "b"]
        assert "max_tokens" not in payload          # embeddings do not generate
        return {"model": payload["model"],
                "data": [{"index": 0, "embedding": [1.0, 0.0]},
                         {"index": 1, "embedding": [0.0, 1.0]}],
                "usage": {"prompt_tokens": 7, "total_tokens": 7}}
    gate = _emb_gate(tmp_path, transport)
    res = await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a", "b"]))
    assert res.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert res.provider == "emb" and res.model == "bge-m3:567m"
    recs = gate.trace.by_matter("M-1")
    assert len(recs) == 1
    r = recs[0]
    assert r.task_class == "embedding" and r.status == "ok"
    assert r.tokens_in == 7 and r.tokens_out == 0      # embeddings emit no completion tokens

def test_embed_request_defaults_to_local_only():
    # Not async — nothing is awaited. (pytest-asyncio in auto mode errors on a sync
    # function carrying the asyncio marker, so this one stays bare.)
    from harness.gate import EmbeddingRequest
    req = EmbeddingRequest(matter_ref="M", texts=["a"])
    assert req.classification == "LOCAL_ONLY"          # strictest tier, inverted from dispatch
    assert req.max_texts == 64

@pytest.mark.asyncio
async def test_embed_refuses_cloud_even_under_cloud_permitted(tmp_path):
    # The gate-level view of the spec's C2: routing may list emb-cloud, but embed() must
    # never dispatch to it. The local embedder is made to FAIL so success can only come
    # from the cloud one — then the refusal proves the filter, not the fixture (the same
    # negative-control discipline as the C2 check in scripts/accept_s7e.py).
    from harness.gate import EmbeddingRequest, GateRefusal
    called = []
    async def transport(provider, payload):
        called.append(provider.name)
        if provider.name == "emb":
            raise RuntimeError("local embedder is down")
        return {"model": payload["model"], "data": [{"index": 0, "embedding": [1.0]}],
                "usage": {"prompt_tokens": 1}}
    gate = _emb_gate(tmp_path, transport)
    with pytest.raises(GateRefusal):
        await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a"],
                                          classification="CLOUD_PERMITTED"))
    assert called == ["emb"], f"cloud embedder was reached: {called}"

@pytest.mark.asyncio
async def test_embed_count_mismatch_is_an_error_not_silently_accepted(tmp_path):
    # An endpoint returning fewer vectors than inputs would corrupt the index while
    # appearing to succeed — refuse and trace, never silently truncate.
    from harness.gate import EmbeddingRequest, GateRefusal
    async def transport(provider, payload):
        return {"model": payload["model"], "data": [{"index": 0, "embedding": [1.0]}],
                "usage": {"prompt_tokens": 1}}        # 1 vector for 2 inputs
    gate = _emb_gate(tmp_path, transport)
    with pytest.raises(GateRefusal):
        await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a", "b"]))
    recs = gate.trace.by_matter("M-1")
    assert recs[0].status == "error"
    assert "1 vectors for 2 inputs" in recs[0].error

@pytest.mark.asyncio
async def test_embed_batch_over_max_texts_is_refused_not_truncated(tmp_path):
    from harness.gate import EmbeddingRequest, GateRefusal
    gate = _emb_gate(tmp_path, _emb_transport([[1.0]]))
    with pytest.raises(GateRefusal):
        await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a", "b"], max_texts=1))
    assert gate.trace.by_matter("M-1")[0].status == "refused"

@pytest.mark.asyncio
async def test_embed_empty_texts_refused(tmp_path):
    from harness.gate import EmbeddingRequest, GateRefusal
    gate = _emb_gate(tmp_path, _emb_transport([[1.0]]))
    with pytest.raises(GateRefusal):
        await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=[]))
    assert gate.trace.by_matter("M-1")[0].status == "refused"

@pytest.mark.asyncio
async def test_embed_without_an_embedding_rule_refuses_and_traces(tmp_path):
    # A routing table with no embedding rule falls to the empty defaults -> no candidates
    # -> the SAME refusal path dispatch uses (provider='-', status='refused').
    from harness.gate import EmbeddingRequest, GateRefusal
    NO_RULE = "rules: []\ndefaults:\n  local_only: []\n  local_preferred: []\n  cloud_permitted: []\n"
    gate = _emb_gate(tmp_path, _emb_transport([[1.0]]), routing=NO_RULE)
    with pytest.raises(GateRefusal):
        await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a"]))
    r = gate.trace.by_matter("M-1")[0]
    assert r.status == "refused" and r.provider == "-"

@pytest.mark.asyncio
async def test_embed_provenance_uses_the_same_rule_as_dispatch(tmp_path):
    # Embeddings must not become a second-class dispatch with weaker provenance.
    from harness.gate import EmbeddingRequest
    async def transport(provider, payload):
        return {"model": payload["model"], "data": [{"index": 0, "embedding": [1.0]}],
                "usage": {"prompt_tokens": 1},
                "_server_meta": {"engine": "ollama", "weights_revision": "rev-x",
                                 "backend": ""}}
    gate = _emb_gate(tmp_path, transport)
    res = await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a"]))
    assert res.provenance.engine == "ollama"
    assert res.provenance.weights_revision == "rev-x"
    assert res.provenance.backend == ""                # honest: Ollama cannot report it


@pytest.mark.asyncio
async def test_ollamas_nested_usage_breakdown_is_reduced_to_scalar_counts(tmp_path):
    # Live-only: Ollama nests prompt_tokens_details: {cached_tokens: 0} inside usage, which the
    # dict[str,int] contract rejects with ValidationError. Only the scalar counts are consumed by
    # the trace, the sidecar and the proxy, so the gate reduces usage to those.
    async def transport(provider, payload):
        return {"model": payload["model"], "choices": [{"message": {"content": "ans"}}],
                "usage": {"prompt_tokens": 46, "completion_tokens": 16, "total_tokens": 62,
                          "prompt_tokens_details": {"cached_tokens": 0}}}
    gate = _gate(tmp_path, transport)
    resp = await gate.dispatch(LLMRequest(matter_ref="M-nested", task_class="drafting",
                                          messages=[{"role": "user", "content": "x"}]))
    assert resp.usage == {"prompt_tokens": 46, "completion_tokens": 16, "total_tokens": 62}
    rec = gate.trace.by_matter("M-nested")[0]
    assert rec.tokens_in == 46 and rec.tokens_out == 16


@pytest.mark.asyncio
async def test_embed_reduces_ollamas_nested_usage_breakdown(tmp_path):
    from harness.gate import EmbeddingRequest
    async def transport(provider, payload):
        return {"model": payload["model"], "data": [{"index": 0, "embedding": [1.0]}],
                "usage": {"prompt_tokens": 7, "total_tokens": 7,
                          "prompt_tokens_details": {"cached_tokens": 0}}}
    gate = _emb_gate(tmp_path, transport)
    resp = await gate.embed(EmbeddingRequest(matter_ref="M-1", texts=["a"]))
    assert resp.usage == {"prompt_tokens": 7, "total_tokens": 7}
