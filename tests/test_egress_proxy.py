# tests/test_egress_proxy.py
import json, urllib.request
import pytest
from harness.gate import EgressGate, LLMRequest
from harness.policy import RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore
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
