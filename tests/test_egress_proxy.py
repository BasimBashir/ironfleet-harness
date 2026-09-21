# tests/test_egress_proxy.py
import json, urllib.request, urllib.error
import pytest
from harness.gate import EgressGate, LLMRequest, GateRefusal
from harness.policy import RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore, DispatchRecord
from harness.egress_proxy import EgressProxy, UnknownMatter

@pytest.fixture
def gate_stack(tmp_path, fake_transport):
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="ollama-local", base_url="http://127.0.0.1:11434/v1",
                              model="thomson1-chat:latest", engine="ollama", tier="local",
                              admitted="mechanical-only", max_output_tokens=8192))
    rt = RoutingTable(rules=[{"task_class": "extraction",
                              "local_only": ["ollama-local"],
                              "local_preferred": ["ollama-local"],
                              "cloud_permitted": ["ollama-local"]}],
                      defaults={"local_only": [], "local_preferred": [], "cloud_permitted": []})
    aliases = {"gate/extraction": {"task_class": "extraction"}}
    trace = TraceStore(tmp_path / "trace.db")
    gate = EgressGate(reg, rt, trace, transport=fake_transport)
    return gate, rt, aliases, trace, tmp_path

def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=10)

def test_chat_completion_happy_path(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-001", "classification": "LOCAL_PREFERRED"}))
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        r = _post(f"http://{host}:{port}/v1/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract the parties"}],
                   "max_tokens": 100})
        body = json.loads(r.read())
        assert body["choices"][0]["message"]["content"] == \
            "mock answer citing [Act, s 1]"
        rows = trace.by_matter("m-001")
        assert len(rows) == 1 and rows[0].provider == "ollama-local"
        assert rows[0].model == "thomson1-chat:latest"
        assert rows[0].verified == 0          # CR-3: Ollama cannot report its engine — honest 0
    finally:
        proxy.stop()

def test_models_endpoint_lists_aliases(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-001", "classification": "LOCAL_PREFERRED"}))
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        r = urllib.request.urlopen(f"http://{host}:{port}/v1/models", timeout=10)
        ids = {m["id"] for m in json.loads(r.read())["data"]}
        assert ids == set(aliases)
    finally:
        proxy.stop()

def test_refusal_returns_403_and_traces(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-draft", "classification": "LOCAL_PREFERRED"}))
    # Add a drafting alias whose rule lists only unregistered providers → refuses.
    aliases["gate/drafting"] = {"task_class": "drafting"}
    rt._rules.append({"task_class": "drafting", "local_only": ["mini1-mlx"],
                      "local_preferred": ["mini1-mlx"], "cloud_permitted": ["mini1-mlx"]})
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/chat/completions",
                  {"model": "gate/drafting",
                   "messages": [{"role": "user", "content": "Draft a claim"}]})
        assert ex.value.code == 403
        rows = trace.by_matter("m-draft")
        assert len(rows) == 1
        assert rows[0].status == "refused" and rows[0].provider == "-"
    finally:
        proxy.stop()

def test_transport_error_returns_502_and_traces(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-broken", "classification": "LOCAL_PREFERRED"}))

    async def dead(provider, payload):
        raise RuntimeError("ollama down")
    gate._transport = dead
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
        assert ex.value.code == 502
        rows = trace.by_matter("m-broken")
        assert len(rows) == 1 and rows[0].status == "error"
    finally:
        proxy.stop()

def test_missing_matter_returns_500_and_never_dispatches(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, tmp_path / "nope.json")
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
        assert ex.value.code == 500
        assert trace.summary()["dispatches"] == 0        # nothing reached the gate
    finally:
        proxy.stop()

def test_stream_true_returns_sse_with_one_delta(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-stream", "classification": "LOCAL_PREFERRED"}))
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        req = urllib.request.Request(f"http://{host}:{port}/v1/chat/completions",
            data=json.dumps({"model": "gate/extraction", "stream": True,
                             "messages": [{"role": "user", "content": "Extract"}]}).encode(),
            headers={"Content-Type": "application/json"})
        raw = urllib.request.urlopen(req, timeout=10).read().decode()
        assert raw.startswith("data: ")
        assert "[DONE]" in raw
        assert trace.by_matter("m-stream")
    finally:
        proxy.stop()

def test_concurrent_same_matter_keeps_each_request_own_code(gate_stack):
    # Two ThreadingHTTPServer requests share a matter_ref (parallel tool calls in one
    # OpenCode session). Request A is a transport error → 502; request B is a policy
    # refusal → 403. If B's refused row lands after A's own error row but before A's
    # handler reads the trace, by_matter()[-1] is B's row and A misreports 403 where the
    # spec requires 502. The pre-dispatch snapshot must point A at its own row.
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-race", "classification": "LOCAL_PREFERRED"}))

    async def dead(provider, payload):
        raise RuntimeError("ollama down")
    gate._transport = dead

    # Simulate B's row landing between A's traced error and A's trace read. That window
    # lives inside the gate's append→raise, which cannot be hit deterministically from
    # outside a byte-locked gate, so the interleaving is reproduced here instead.
    real_dispatch = gate.dispatch
    async def racing_dispatch(request):
        try:
            return await real_dispatch(request)
        except GateRefusal:
            trace.append(DispatchRecord(
                matter_ref=request.matter_ref, task_class="other",
                classification=request.classification, provider="-", model="-",
                status="refused", error="no eligible provider"))
            raise
    gate.dispatch = racing_dispatch

    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
        assert ex.value.code == 502            # not 403 — this request's own row was an error
        rows = trace.by_matter("m-race")
        assert [r.status for r in rows] == ["error", "refused"]
    finally:
        proxy.stop()
