# tests/test_egress_proxy.py
import json, secrets, urllib.request, urllib.error
import pytest
from harness.gate import EgressGate, LLMRequest, GateRefusal
from harness.policy import RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore, DispatchRecord
from harness.egress_proxy import EgressProxy, UnknownMatter
from harness.capacity import Capacity
from harness.scheduler import TurnScheduler

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

def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    return urllib.request.urlopen(req, timeout=10)

def _mint(root, ref):
    """M1/S3: what sync_mount does — a token record naming the matter; returns the token."""
    tok = secrets.token_urlsafe(16)
    (root / "_tokens").mkdir(parents=True, exist_ok=True)
    (root / "_tokens" / f"{tok}.json").write_text(json.dumps({"matter_ref": ref}),
                                                  encoding="utf-8")
    return tok

def _write_matters(root, refs, classification="LOCAL_PREFERRED"):
    """A served matters directory holding `refs`, each with a token; returns (root, {ref: tok})."""
    root.mkdir(parents=True, exist_ok=True)
    for ref in refs:
        d = root / ref
        d.mkdir(parents=True, exist_ok=True)
        (d / "matter.json").write_text(json.dumps(
            {"matter_ref": ref, "classification": classification}), encoding="utf-8")
    return root, {ref: _mint(root, ref) for ref in refs}

def _serve(tmp_path, ref):
    """One-matter fixture: (matters root, the chat-completions path for its token)."""
    root, toks = _write_matters(tmp_path / "matters", [ref])
    return root, f"/v1/t/{toks[ref]}/chat/completions"

EXTRACT = {"model": "gate/extraction", "messages": [{"role": "user", "content": "Extract"}]}

def test_chat_completion_happy_path(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter, path = _serve(tmp_path, "m-001")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        r = _post(f"http://{host}:{port}{path}",
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
    matter, _path = _serve(tmp_path, "m-001")
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
    matter, path = _serve(tmp_path, "m-draft")
    # Add a drafting alias whose rule lists only unregistered providers → refuses.
    aliases["gate/drafting"] = {"task_class": "drafting"}
    rt._rules.append({"task_class": "drafting", "local_only": ["mini1-mlx"],
                      "local_preferred": ["mini1-mlx"], "cloud_permitted": ["mini1-mlx"]})
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}{path}",
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
    matter, path = _serve(tmp_path, "m-broken")

    async def dead(provider, payload):
        raise RuntimeError("ollama down")
    gate._transport = dead
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}{path}", EXTRACT)
        assert ex.value.code == 502
        rows = trace.by_matter("m-broken")
        assert len(rows) == 1 and rows[0].status == "error"
    finally:
        proxy.stop()

def test_a_token_naming_an_unregistered_matter_is_500_and_never_dispatches(gate_stack):
    # A valid token whose matter record is gone: no passthrough, no default matter.
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, _toks = _write_matters(tmp_path / "matters", ["m-known"])
    tok = _mint(root, "m-gone")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, root)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/t/{tok}/chat/completions", EXTRACT)
        assert ex.value.code == 500
        assert trace.summary()["dispatches"] == 0        # nothing reached the gate
    finally:
        proxy.stop()

def test_stream_true_returns_sse_with_one_delta(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter, path = _serve(tmp_path, "m-stream")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        req = urllib.request.Request(f"http://{host}:{port}{path}",
            data=json.dumps({"model": "gate/extraction", "stream": True,
                             "messages": [{"role": "user", "content": "Extract"}]}).encode(),
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode()
        assert raw.startswith("data: ")
        assert "[DONE]" in raw
        # A body of "data: {}\n\ndata: [DONE]" with the wrong content type would pass the two
        # assertions above. The SSE branch must present as an event stream and actually carry
        # the dispatched answer — parse the data: lines rather than substring-searching.
        assert resp.headers.get("Content-Type") == "text/event-stream"
        chunks = []
        for line in raw.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):]
            if payload == "[DONE]":
                continue
            chunks.append(json.loads(payload)["choices"][0]["delta"].get("content") or "")
        assert "".join(chunks) == "mock answer citing [Act, s 1]"
        parsed = [json.loads(l[len("data: "):]) for l in raw.splitlines()
                  if l.startswith("data: ") and l[len("data: "):] != "[DONE]"]
        assert parsed[-1]["choices"][0]["finish_reason"] == "stop", \
            "a non-terminal final chunk would leave the client hanging on the stream"
        assert parsed[-1]["choices"][0]["delta"] == {}
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
    matter, path = _serve(tmp_path, "m-race")

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
            _post(f"http://{host}:{port}{path}", EXTRACT)
        assert ex.value.code == 502            # not 403 — this request's own row was an error
        rows = trace.by_matter("m-race")
        assert [r.status for r in rows] == ["error", "refused"]
    finally:
        proxy.stop()

# --- M1/S3: matter identity comes ONLY from a per-sync token (audit 01 S3) ---------------
# The A-5 header, /v1/m/<ref> path and legacy single-record forms let any local process
# dispatch as any registered matter. sync_mount now mints a token per sync and the proxy
# resolves the matter from <matters_root>/_tokens/<token>.json — nothing else is read.

def _proxy_with_scheduler(gate_stack, matters_dir):
    """A proxy whose dispatch goes through a scheduler, serving a matters DIRECTORY."""
    gate, rt, aliases, trace, tmp_path = gate_stack
    sched = TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                   source_memory="t"), max_concurrent=1)
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matters_dir, scheduler=sched)
    return proxy, trace, tmp_path

def _queue_ms(host, port, tok, stream=False):
    """POST a dispatch and read back the scheduler's queue-wait header."""
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/t/{tok}/chat/completions",
        data=json.dumps({**EXTRACT, "stream": stream}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
        return float(r.headers.get("X-IronFleet-Queue-Ms", "0"))

def test_the_token_identifies_the_matter(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, toks = _write_matters(tmp_path / "matters", ["m-tok", "m-other"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        _post(f"http://{host}:{port}/v1/t/{toks['m-tok']}/chat/completions", EXTRACT).read()
        assert len(trace.by_matter("m-tok")) == 1
        assert trace.by_matter("m-other") == []
    finally:
        proxy.stop()

def test_a_header_naming_another_matter_is_ignored(gate_stack):
    # The header is never read: a valid token is served as the token's matter, whatever the
    # request claims.
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, toks = _write_matters(tmp_path / "matters", ["m-tok", "m-victim"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        _post(f"http://{host}:{port}/v1/t/{toks['m-tok']}/chat/completions", EXTRACT,
              headers={"X-IronFleet-Matter": "m-victim"}).read()
        assert len(trace.by_matter("m-tok")) == 1
        assert trace.by_matter("m-victim") == []
    finally:
        proxy.stop()

@pytest.mark.parametrize("path,headers", [
    ("/v1/chat/completions", {}),                                   # token-less legacy form
    ("/v1/chat/completions", {"X-IronFleet-Matter": "m-one"}),      # header identity, removed
    ("/v1/m/m-one/chat/completions", {}),                           # path identity, removed
    ("/v1/t/not-a-minted-token/chat/completions", {}),              # unknown token
    ("/v1/t/../chat/completions", {}),                              # not a token shape
])
def test_a_request_without_a_live_token_is_401_and_never_dispatches(gate_stack, path, headers):
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, _toks = _write_matters(tmp_path / "matters", ["m-one", "m-two"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}{path}", EXTRACT, headers=headers)
        assert ex.value.code == 401
        assert trace.summary()["dispatches"] == 0
    finally:
        proxy.stop()

def test_a_rotated_token_is_401(gate_stack):
    # sync_mount deletes the token it minted last sync; a client still holding it is out.
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, toks = _write_matters(tmp_path / "matters", ["m-rot"])
    (root / "_tokens" / f"{toks['m-rot']}.json").unlink()
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/t/{toks['m-rot']}/chat/completions", EXTRACT)
        assert ex.value.code == 401
        assert trace.summary()["dispatches"] == 0
    finally:
        proxy.stop()

def test_the_legacy_single_record_file_form_is_dead(gate_stack):
    # The S7b form — one matter.json served directly — has no _tokens directory, so no
    # request can authenticate against it. Every mount re-syncs to the directory form.
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-legacy", "classification": "LOCAL_PREFERRED"}),
                      encoding="utf-8")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/chat/completions", EXTRACT)
        assert ex.value.code == 401
        assert trace.by_matter("m-legacy") == []
    finally:
        proxy.stop()

def test_queue_timeout_returns_503_with_retry_after(gate_stack):
    # A saturated queue makes the client back off with a header it can act on, rather than
    # piling its own retries onto the queue (spec §3.4).
    import asyncio, threading, time
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, toks = _write_matters(tmp_path / "matters", ["m-q"])
    sched = TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                   source_memory="t"), max_concurrent=1, queue_timeout=0.05)

    async def slow(provider, payload):
        await asyncio.sleep(0.3)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}, "model": "m"}
    gate._transport = slow
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, root, scheduler=sched)
    proxy.start(); host, port = proxy.server_address
    url = f"http://{host}:{port}/v1/t/{toks['m-q']}/chat/completions"
    try:
        # First turn holds the only slot; the second queues and times out.
        t = threading.Thread(target=lambda: _post(url, EXTRACT), daemon=True)
        t.start()
        time.sleep(0.05)          # let the first dispatch acquire the single slot
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(url, EXTRACT)
        assert ex.value.code == 503
        assert ex.value.headers.get("Retry-After") is not None
        t.join(timeout=10)
    finally:
        proxy.stop()

def test_queue_wait_is_reported_in_a_header(gate_stack):
    # The scheduler knows how long a turn waited; the response carries it as a header so C6
    # can assert the queued turn genuinely queued from the scheduler's own measurement
    # rather than wall-clock inference. A body field would have to be optional in every SDK
    # consumer; a header touches no schema.
    import asyncio, threading, time
    gate, rt, aliases, trace, tmp_path = gate_stack
    root, toks = _write_matters(tmp_path / "matters", ["m-hdr", "m-queued"])
    sched = TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                   source_memory="t"), max_concurrent=1)

    async def slow(provider, payload):
        await asyncio.sleep(0.2)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}, "model": "m"}
    gate._transport = slow
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, root, scheduler=sched)
    proxy.start(); host, port = proxy.server_address
    waited = {}
    try:
        t = threading.Thread(target=lambda: waited.update(
            {"a": _queue_ms(host, port, toks["m-hdr"])}), daemon=True)
        t.start()
        time.sleep(0.05)          # let the first dispatch take the only slot
        waited["b"] = _queue_ms(host, port, toks["m-queued"])
        t.join(timeout=10)
        # And the header is present on the streaming path too — same uncontended ~0 as A.
        # Read it HERE, inside the try: the finally below stops the server, so a header
        # read after it is a connection refused, not a measurement.
        waited["stream"] = _queue_ms(host, port, toks["m-hdr"], stream=True)
    finally:
        proxy.stop()
    # The turn that had to wait reports a real queue wait; the one that went first reports
    # only the uncontended lock acquire (microseconds, not a wait). The distinction is
    # ORDERS OF MAGNITUDE: B waits behind a running turn, A does not — a slack-tolerant
    # comparison on A would pass even if queue_ms were never recorded at all.
    assert waited["b"] > 50, waited
    assert waited["a"] < 5, waited
    assert waited["stream"] < 5, waited


# ── S7j-W: the tool-call carrier ─────────────────────────────────────────────
# Live finding 2026-10-12: the model emits tool_calls (replay-proven on the captured
# 14-tool payload -> finish_reason tool_calls), but the gate's batch response kept only
# content, and the proxy synthesized content-only deltas with a hardcoded "stop" — so NO
# model could ever exercise the tool path through the gate. The gate now carries the
# calls verbatim; policing the args stays the mount guard hook's job.

def _tool_call_transport():
    async def _call(provider, payload):
        return {
            "id": "chatcmpl-tool", "object": "chat.completion", "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": "",
                                     "tool_calls": [{"id": "call_1", "type": "function",
                                                     "function": {
                                                         "name": "ironfleet_without_prejudice",
                                                         "arguments": '{"content": "x", "trust_tier": "T2"}'}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_server_meta": {"engine": provider.engine or "unknown",
                              "weights_revision": provider.declared_provenance.get("weights_revision", "")},
        }
    return _call


def _tool_stack(tmp_path, transport=None):
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="ollama-local", base_url="http://127.0.0.1:11434/v1",
                              model="thomson1-chat:latest", engine="ollama", tier="local",
                              admitted="mechanical-only", max_output_tokens=8192))
    rt = RoutingTable(rules=[{"task_class": "extraction", "local_only": ["ollama-local"],
                              "local_preferred": ["ollama-local"],
                              "cloud_permitted": ["ollama-local"]}],
                      defaults={"local_only": [], "local_preferred": [], "cloud_permitted": []})
    trace = TraceStore(tmp_path / "trace.db")
    gate = EgressGate(reg, rt, trace, transport=transport or _tool_call_transport())
    return gate, rt, {"gate/extraction": {"task_class": "extraction"}}, trace


def _tool_proxy(tmp_path):
    gate, rt, aliases, trace = _tool_stack(tmp_path)
    matter, path = _serve(tmp_path, "m-001")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start()
    host, port = proxy.server_address
    return proxy, f"http://{host}:{port}{path}", trace


def test_the_gate_carries_tool_calls_on_the_response(tmp_path, fake_transport):
    gate, rt, aliases, trace = _tool_stack(tmp_path)
    import asyncio
    resp = asyncio.run(gate.dispatch(LLMRequest(
        matter_ref="m-001", task_class="extraction", max_tokens=100,
        messages=[{"role": "user", "content": "call the tool"}])))
    assert resp.tool_calls[0]["function"]["name"] == "ironfleet_without_prejudice"
    rows = trace.by_matter("m-001")
    assert len(rows) == 1 and rows[0].status == "ok"   # one gated, traced dispatch


def test_the_plain_transport_yields_no_tool_calls(tmp_path, fake_transport):
    gate, rt, aliases, trace = _tool_stack(tmp_path, transport=fake_transport)
    import asyncio
    resp = asyncio.run(gate.dispatch(LLMRequest(
        matter_ref="m-001", task_class="extraction", max_tokens=10,
        messages=[{"role": "user", "content": "hi"}])))
    assert resp.tool_calls == []


def test_proxy_json_body_carries_tool_calls_and_finish_reason(tmp_path):
    proxy, url, trace = _tool_proxy(tmp_path)
    try:
        body = json.loads(_post(url, {"model": "gate/extraction", "max_tokens": 100,
                                      "messages": [{"role": "user", "content": "call"}]}).read())
        choice = body["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        assert choice["message"]["tool_calls"][0]["function"]["name"] == \
            "ironfleet_without_prejudice"
    finally:
        proxy.stop()


def test_proxy_sse_body_carries_indexed_tool_calls(tmp_path):
    proxy, url, trace = _tool_proxy(tmp_path)
    try:
        req = urllib.request.Request(url, data=json.dumps(
            {"model": "gate/extraction", "stream": True, "max_tokens": 100,
             "messages": [{"role": "user", "content": "call"}]}).encode(),
            headers={"Content-Type": "application/json"})
        raw = urllib.request.urlopen(req, timeout=10).read().decode()
        chunks = [json.loads(l[len("data: "):]) for l in raw.splitlines()
                  if l.startswith("data: ") and l != "data: [DONE]"]
        delta = chunks[0]["choices"][0]["delta"]
        assert delta["tool_calls"][0]["function"]["name"] == "ironfleet_without_prejudice"
        assert delta["tool_calls"][0]["index"] == 0    # stream-assembly convention
        assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    finally:
        proxy.stop()


def test_plain_content_keeps_stop_finish(tmp_path, gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter, path = _serve(tmp_path, "m-001")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        body = json.loads(_post(f"http://{host}:{port}{path}",
                                {"model": "gate/extraction", "max_tokens": 100,
                                 "messages": [{"role": "user", "content": "x"}]}).read())
        assert body["choices"][0]["finish_reason"] == "stop"
        assert "tool_calls" not in body["choices"][0]["message"]
    finally:
        proxy.stop()


# ── the request side: the tools array must REACH the provider payload ────────
# Second half of the 2026-10-12 finding: opencode sends the 14-tool array, but the
# proxy built an LLMRequest with no tools field and the gate built the provider
# payload from that request — so the provider never saw a tool to call, whatever the
# model. (The driver's replay proved the model calls tools when it CAN see them.)

def test_the_gate_puts_tools_in_the_provider_payload(tmp_path):
    captured = {}

    async def spy(provider, payload):
        captured.update(payload)
        return await _tool_call_transport()(provider, payload)

    gate, rt, aliases, trace = _tool_stack(tmp_path, transport=spy)
    import asyncio
    asyncio.run(gate.dispatch(LLMRequest(
        matter_ref="m-001", task_class="extraction", max_tokens=100,
        messages=[{"role": "user", "content": "call"}],
        tools=[{"type": "function", "function": {"name": "ironfleet_without_prejudice",
                                                 "parameters": {}}}])))
    assert captured["tools"][0]["function"]["name"] == "ironfleet_without_prejudice"


def test_a_toolless_request_sends_no_tools_key(tmp_path, fake_transport):
    gate, rt, aliases, trace = _tool_stack(tmp_path, transport=fake_transport)
    captured = {}

    async def spy(provider, payload):
        captured.update(payload)
        return await fake_transport(provider, payload)

    gate._transport = spy
    import asyncio
    asyncio.run(gate.dispatch(LLMRequest(
        matter_ref="m-001", task_class="extraction", max_tokens=10,
        messages=[{"role": "user", "content": "hi"}])))
    assert "tools" not in captured


def test_the_proxy_forwards_the_client_tools_array(tmp_path):
    seen = {}

    async def spy(provider, payload):
        seen.update(payload)
        return await _tool_call_transport()(provider, payload)

    gate, rt, aliases, trace = _tool_stack(tmp_path, transport=spy)
    matter, path = _serve(tmp_path, "m-001")
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter)
    proxy.start(); host, port = proxy.server_address
    try:
        _post(f"http://{host}:{port}{path}",
              {"model": "gate/extraction", "max_tokens": 100,
               "messages": [{"role": "user", "content": "call"}],
               "tools": [{"type": "function", "function": {"name": "ironfleet_without_prejudice",
                                                           "parameters": {}}}]})
        assert seen["tools"][0]["function"]["name"] == "ironfleet_without_prejudice"
    finally:
        proxy.stop()
