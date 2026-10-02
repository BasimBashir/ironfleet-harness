# tests/test_egress_proxy.py
import json, urllib.request, urllib.error
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

# --- A-5: the proxy is multi-matter, identity from header / path / legacy (spec §4) -----

def _proxy_with_scheduler(gate_stack, matters_dir):
    """A proxy whose dispatch goes through a scheduler, serving a matters DIRECTORY."""
    gate, rt, aliases, trace, tmp_path = gate_stack
    sched = TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                   source_memory="t"), max_concurrent=1)
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matters_dir, scheduler=sched)
    return proxy, trace, tmp_path

def _write_matters(root, refs):
    root.mkdir(parents=True, exist_ok=True)
    for ref in refs:
        d = root / ref
        d.mkdir(parents=True, exist_ok=True)
        (d / "matter.json").write_text(json.dumps(
            {"matter_ref": ref, "classification": "LOCAL_PREFERRED"}))
    return root

def _queue_ms(host, port, ref, stream=False):
    """POST a dispatch and read back the scheduler's queue-wait header."""
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/m/{ref}/chat/completions",
        data=json.dumps({"model": "gate/extraction", "stream": stream,
                         "messages": [{"role": "user", "content": "Extract"}]}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
        return float(r.headers.get("X-IronFleet-Queue-Ms", "0"))

def test_header_identifies_the_matter(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    root = _write_matters(tmp_path / "matters", ["m-hdr", "m-other"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        req = urllib.request.Request(f"http://{host}:{port}/v1/chat/completions",
            data=json.dumps({"model": "gate/extraction",
                             "messages": [{"role": "user", "content": "Extract"}]}).encode(),
            headers={"Content-Type": "application/json", "X-IronFleet-Matter": "m-hdr"})
        r = urllib.request.urlopen(req, timeout=10)
        assert json.loads(r.read())["choices"][0]["message"]["content"]
        rows = trace.by_matter("m-hdr")
        assert len(rows) == 1                      # dispatched under the HEADER's matter
        assert trace.by_matter("m-other") == []    # and no other matter's record was touched
    finally:
        proxy.stop()

def test_path_identifies_the_matter(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    root = _write_matters(tmp_path / "matters", ["m-path", "m-other"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        r = _post(f"http://{host}:{port}/v1/m/m-path/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
        rows = trace.by_matter("m-path")
        assert len(rows) == 1
        assert trace.by_matter("m-other") == []
    finally:
        proxy.stop()

def test_header_wins_over_path_when_both_are_present(gate_stack):
    # Precedence is fixed and deterministic (spec §4): header first, then path, then the
    # legacy record — so an operator can always tell which form identified the turn.
    gate, rt, aliases, trace, tmp_path = gate_stack
    root = _write_matters(tmp_path / "matters", ["m-hdr", "m-path"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        req = urllib.request.Request(f"http://{host}:{port}/v1/m/m-path/chat/completions",
            data=json.dumps({"model": "gate/extraction",
                             "messages": [{"role": "user", "content": "Extract"}]}).encode(),
            headers={"Content-Type": "application/json", "X-IronFleet-Matter": "m-hdr"})
        urllib.request.urlopen(req, timeout=10).read()
        assert len(trace.by_matter("m-hdr")) == 1
        assert trace.by_matter("m-path") == []
    finally:
        proxy.stop()

def test_unknown_matter_is_500_and_never_dispatches(gate_stack):
    gate, rt, aliases, trace, tmp_path = gate_stack
    root = _write_matters(tmp_path / "matters", ["m-known"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/m/m-unknown/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
        assert ex.value.code == 500
        assert trace.summary()["dispatches"] == 0   # no passthrough, no default matter
    finally:
        proxy.stop()

def test_legacy_single_matter_file_still_works(gate_stack):
    # The S7b form — one matter.json, no matters directory — must keep working so no
    # existing mount breaks (spec §4).
    gate, rt, aliases, trace, tmp_path = gate_stack
    matter = tmp_path / "matter.json"
    matter.write_text(json.dumps({"matter_ref": "m-legacy", "classification": "LOCAL_PREFERRED"}))
    sched = TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                   source_memory="t"), max_concurrent=1)
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, matter, scheduler=sched)
    proxy.start(); host, port = proxy.server_address
    try:
        _post(f"http://{host}:{port}/v1/chat/completions",
              {"model": "gate/extraction",
               "messages": [{"role": "user", "content": "Extract"}]})
        assert len(trace.by_matter("m-legacy")) == 1
    finally:
        proxy.stop()

def test_no_identity_in_a_matters_directory_is_refused(gate_stack):
    # A matters DIRECTORY holding two records, with no identity on the request, must NOT
    # fall back to either record — there is no default matter (spec §4). The legacy
    # single-record fallback is a property of the ONE-record form, not of the directory.
    gate, rt, aliases, trace, tmp_path = gate_stack
    root = _write_matters(tmp_path / "matters", ["m-one", "m-two"])
    proxy, _trace, _tp = _proxy_with_scheduler(gate_stack, root)
    proxy.start(); host, port = proxy.server_address
    try:
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
        assert ex.value.code == 500
        assert trace.summary()["dispatches"] == 0
    finally:
        proxy.stop()

def test_queue_timeout_returns_503_with_retry_after(gate_stack):
    # A saturated queue makes the client back off with a header it can act on, rather than
    # piling its own retries onto the queue (spec §3.4).
    import asyncio, threading, time
    gate, rt, aliases, trace, tmp_path = gate_stack
    root = _write_matters(tmp_path / "matters", ["m-q"])
    sched = TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                   source_memory="t"), max_concurrent=1, queue_timeout=0.05)

    async def slow(provider, payload):
        await asyncio.sleep(0.3)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}, "model": "m"}
    gate._transport = slow
    proxy = EgressProxy("127.0.0.1", 0, gate, rt, aliases, root, scheduler=sched)
    proxy.start(); host, port = proxy.server_address
    try:
        # First turn holds the only slot; the second queues and times out.
        t = threading.Thread(target=lambda: _post(
            f"http://{host}:{port}/v1/m/m-q/chat/completions",
            {"model": "gate/extraction",
             "messages": [{"role": "user", "content": "Extract"}]}), daemon=True)
        t.start()
        time.sleep(0.05)          # let the first dispatch acquire the single slot
        with pytest.raises(urllib.error.HTTPError) as ex:
            _post(f"http://{host}:{port}/v1/m/m-q/chat/completions",
                  {"model": "gate/extraction",
                   "messages": [{"role": "user", "content": "Extract"}]})
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
    root = _write_matters(tmp_path / "matters", ["m-hdr", "m-queued"])
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
            {"a": _queue_ms(host, port, "m-hdr")}), daemon=True)
        t.start()
        time.sleep(0.05)          # let the first dispatch take the only slot
        waited["b"] = _queue_ms(host, port, "m-queued")
        t.join(timeout=10)
        # And the header is present on the streaming path too — same uncontended ~0 as A.
        # Read it HERE, inside the try: the finally below stops the server, so a header
        # read after it is a connection refused, not a measurement.
        waited["stream"] = _queue_ms(host, port, "m-hdr", stream=True)
    finally:
        proxy.stop()
    # The turn that had to wait reports a real queue wait; the one that went first reports
    # only the uncontended lock acquire (microseconds, not a wait). The distinction is
    # ORDERS OF MAGNITUDE: B waits behind a running turn, A does not — a slack-tolerant
    # comparison on A would pass even if queue_ms were never recorded at all.
    assert waited["b"] > 50, waited
    assert waited["a"] < 5, waited
    assert waited["stream"] < 5, waited
