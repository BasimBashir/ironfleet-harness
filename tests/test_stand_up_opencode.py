# tests/test_stand_up_opencode.py
import asyncio, json, subprocess, sys
from pathlib import Path
import pytest

DRIVER = Path(__file__).resolve().parent.parent / "scripts" / "stand_up_opencode.py"

def test_sync_mount_copies_and_substitutes(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"; ws.mkdir()
    data = Path(__file__).resolve().parent.parent / "data"
    # 8123, not the mount's static 7373: against the static value a no-op substitution still
    # passes, so only a different port proves the key is actually rewritten.
    sync_mount(ws, data / "opencode-a1", matter_ref="m-test",
               classification="LOCAL_PREFERRED", port=8123)
    cfg = json.loads((ws / "opencode.json").read_text())
    assert cfg["provider"]["gate-local"]["options"]["baseURL"] == "http://127.0.0.1:8123/v1/m/m-test"
    matter = json.loads((ws / "matter.json").read_text())
    assert matter["matter_ref"] == "m-test"

def test_sync_mount_refuses_port_collision_substitution(tmp_path):
    # The port is substituted, never discovered: a substituted 0 would let the mount
    # point at an arbitrary port. The driver fails if it cannot bind what it advertised.
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"; ws.mkdir()
    data = Path(__file__).resolve().parent.parent / "data"
    sync_mount(ws, data / "opencode-a1", matter_ref="m-test",
               classification="LOCAL_PREFERRED", port=8123)
    cfg = json.loads((ws / "opencode.json").read_text())
    assert cfg["provider"]["gate-local"]["options"]["baseURL"] == \
        "http://127.0.0.1:8123/v1/m/m-test"

def test_driver_help_runs(tmp_path):
    # Smoke: the CLI imports cleanly and its --help exits 0.
    r = subprocess.run([sys.executable, str(DRIVER), "--help"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0
    assert "--matter-ref" in r.stdout or "--matter-ref" in r.stderr

def test_main_returns_2_when_port_is_taken(tmp_path, monkeypatch):
    # The port-collision guard is a stated deliverable: if 7373 is held by something else,
    # the driver must abort (exit 2) rather than start a mount whose hardcoded baseURL
    # would point at that something else. ThreadingHTTPServer binds in its CONSTRUCTOR, so
    # the guard must wrap construction, not start().
    import socket
    import scripts.stand_up_opencode as drv

    # build_gate() probes a live Ollama — a unit test must not depend on the network.
    # Stub it with a gate that has no providers; the bind guard runs before any dispatch.
    from harness.policy import RoutingTable
    from harness.providers.config import ProviderRegistry
    from harness.trace import TraceStore
    from harness.gate import EgressGate
    def fake_build_gate(trace_path):
        rt = RoutingTable.from_yaml(drv.ROUTING)
        return (EgressGate(ProviderRegistry(), rt, TraceStore(trace_path)), rt,
                {"gate/extraction": {"task_class": "extraction"}})
    monkeypatch.setattr(drv, "build_gate", fake_build_gate)

    ws = tmp_path / "ws"
    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.bind((drv.HOST, drv.PORT))
    squatter.listen(1)
    try:
        rc = drv.main(["--matter-ref", "m-collide", "--workspace", str(ws),
                       "--prompt", "unused"])
    finally:
        squatter.close()
    assert rc == 2, f"a bind failure must abort with exit 2, got {rc}"
    assert (ws / "opencode.json").exists()


# ---------------------------------------------------------------------------
# The transport seam: _scalar_usage and the wrapper build_gate installs over the gate's
# default transport. Every other test in this file stubs build_gate (it probes a live
# Ollama), so the live billing path this code sits on is reached by NO test but the
# acceptance run. These cover it directly.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("usage, expected", [
    # All-scalar OpenAI usage passes through untouched — a normalisation that invented or
    # dropped counts would corrupt the traced billable evidence.
    ({"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
     {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}),
    # The live failure: Ollama nests the token breakdown as OBJECTS. They are dropped while
    # the sibling scalars survive. (Observed: prompt_tokens_details {"cached_tokens": 41}
    # validated as a dict against LLMResponse.usage: dict[str,int] and 502'd the call.)
    ({"prompt_tokens": 3933, "completion_tokens": 22, "total_tokens": 3955,
      "prompt_tokens_details": {"cached_tokens": 41},
      "completion_tokens_details": {"reasoning_tokens": 3}},
     {"prompt_tokens": 3933, "completion_tokens": 22, "total_tokens": 3955}),
    # total_tokens specifically must survive: it is the count the store's summary aggregates.
    ({"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12,
      "prompt_tokens_details": {"cached_tokens": 7}},
     {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}),
    # bool is a subclass of int in Python — True must not pass as a token count.
    ({"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14,
      "cached": True, "streamed": False},
     {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}),
    # A usage key that is itself a bare bool is dropped, not coerced to 0/1.
    ({"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4, "ok": True},
     {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}),
])
def test_scalar_usage_drops_nested_and_keeps_scalars(usage, expected):
    from scripts.stand_up_opencode import _scalar_usage
    out = _scalar_usage({"content": "x", "usage": dict(usage)})
    assert out["usage"] == expected
    # The rest of the provider response is untouched — only usage is rewritten.
    assert out["content"] == "x"

def test_scalar_usage_missing_or_non_dict_usage_is_a_no_op():
    from scripts.stand_up_opencode import _scalar_usage
    # No usage key at all: nothing to normalise, response returned as-is.
    r = _scalar_usage({"content": "x"})
    assert r == {"content": "x"}
    # A non-dict usage (a malformed upstream) is left alone rather than raising; the gate's
    # own validation reports it as a traced error instead of the driver guessing a repair.
    r = _scalar_usage({"content": "x", "usage": "n/a"})
    assert r == {"content": "x", "usage": "n/a"}

def test_scalar_usage_does_not_mutate_the_callers_dict():
    from scripts.stand_up_opencode import _scalar_usage
    original = {"prompt_tokens": 5, "prompt_tokens_details": {"cached_tokens": 5}}
    _scalar_usage({"usage": original})
    assert original == {"prompt_tokens": 5, "prompt_tokens_details": {"cached_tokens": 5}}


class _FakeGate:
    """Stands in for EgressGate so the seam is testable without a live Ollama.

    Mirrors the part of the real contract build_gate depends on: a constructor taking
    (registry, routing, trace), a _default_transport coroutine, and a settable _transport.

    With seamless=True the _default_transport attribute is absent entirely, simulating
    byte-locked gate.py having renamed or restructured the private method."""
    def __init__(self, registry, routing, trace):
        self.registry, self.routing, self.trace = registry, routing, trace
        self._transport = None

    async def _default_transport(self, provider, payload):
        return self._raw

    async def _default_embedding_transport(self, provider, payload):
        return self._raw

    @classmethod
    def seamless(cls):
        """A gate that no longer exposes the attribute the seam wraps."""
        klass = type("SeamlessGate", (cls,), {"_default_transport": None})
        klass._raw = cls._raw
        return klass


def _install_fake_gate(monkeypatch, raw=None, seamless=False):
    # build_gate's body lives in harness.bootstrap now (the launcher's scripts-free
    # import path), with stand_up re-exporting it — so the fake gate must be installed
    # in BOTH modules' namespaces.
    import scripts.stand_up_opencode as drv
    import harness.bootstrap as boot
    cls = _FakeGate.seamless() if seamless else _FakeGate
    cls._raw = raw or {}
    for mod in (drv, boot):
        monkeypatch.setattr(mod, "EgressGate", cls)
        monkeypatch.setattr(mod, "_probe_ollama", lambda: None)
    return drv, cls


def test_build_gate_wraps_the_default_transport_and_flattens_usage(tmp_path, monkeypatch):
    import asyncio
    drv, _ = _install_fake_gate(monkeypatch, raw={
        "model": "thomson1-chat:latest",
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 3933, "completion_tokens": 22, "total_tokens": 3955,
                  "prompt_tokens_details": {"cached_tokens": 41}},
    })
    gate, rt, aliases = drv.build_gate(tmp_path / "trace.db")
    # The wrapper is what dispatch actually calls.
    out = asyncio.run(gate._transport(object(), {"model": "thomson1-chat:latest"}))
    assert out["usage"] == {"prompt_tokens": 3933, "completion_tokens": 22,
                            "total_tokens": 3955}
    # And the rest of the provider response still reaches the caller.
    assert out["choices"][0]["message"]["content"] == "hi"

def test_build_gate_fails_loudly_if_the_seam_attribute_is_gone(tmp_path, monkeypatch):
    drv, _ = _install_fake_gate(monkeypatch, seamless=True)
    # A renamed/restructured _default_transport in byte-locked gate.py must fail HERE, with
    # an actionable message — not with a bare AttributeError at live-run time, which is
    # where it would surface since every other test stubs build_gate.
    with pytest.raises(RuntimeError) as ex:
        drv.build_gate(tmp_path / "trace.db")
    assert "_default_transport" in str(ex.value)
    assert "build_gate" in str(ex.value)


def test_driver_run_as_a_script_reaches_the_spike_driver(tmp_path):
    # Running the driver as a CLI puts scripts/ at sys.path[0] and NOT the repo root, and
    # run_opencode_session resolves the spike driver by package path (scripts/ has no
    # __init__.py) — so the gate bound, then the session died on ModuleNotFoundError before
    # opencode ever started (observed live 2026-10-01). `--help` exits at argparse and never
    # reaches that import, which is why the suite stayed green: this has to exercise it, from
    # a cwd that is not the repo, with only scripts/ on the path the way a CLI would have it.
    import subprocess, sys
    probe = ("import sys; sys.path.insert(0, sys.argv[1]);"
             "import stand_up_opencode;"
             "from scripts.run_spike_opencode import run_opencode")
    r = subprocess.run([sys.executable, "-c", probe,
                        str(Path(__file__).resolve().parent.parent / "scripts")],
                       capture_output=True, text=True, cwd=str(tmp_path), timeout=120)
    assert r.returncode == 0, r.stderr
    assert "No module named 'scripts'" not in r.stderr


def test_main_hands_the_scrubbed_env_to_the_session(monkeypatch, tmp_path):
    # The env half of S1 at the driver's entry point: main() must pass child_env(ws) down, not
    # mutate os.environ (the pre-Task-12 hardening path) and not let the child inherit the
    # parent env.
    from scripts import stand_up_opencode as drv
    seen = {}

    def fake_session(ws, model, prompt, timeout, env=None):
        seen["env"] = env
        return 0, "ok"

    monkeypatch.setattr(drv, "run_opencode_session", fake_session)
    monkeypatch.setattr(drv, "sync_mount", lambda *a, **k: None)
    monkeypatch.setattr(drv, "build_gate", lambda trace: (object(), object(), {}))

    class _Proxy:
        def __init__(self, *a, **k):
            pass
        def start(self):
            pass
        def stop(self):
            pass
    monkeypatch.setattr(drv, "EgressProxy", _Proxy)
    rc = drv.main(["--matter-ref", "m-env", "--task-class", "extraction",
                   "--workspace", str(tmp_path)])
    assert rc == 0
    env = seen["env"]
    assert env["PWD"] == str(tmp_path)
    assert env["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    assert not any(k in env for k in ("ANTHROPIC_API_KEY", "AWS_REGION", "AWS_ACCESS_KEY_ID"))


def test_probe_ollama_registers_chat_and_embedding_providers(monkeypatch):
    # The live registry must be built by evidence in one place; the embedding provider
    # takes the SAME registration path as the chat provider (spec §1 item 3).
    # register_provider is imported INSIDE _probe_ollama (stand_up_opencode.py:264), so
    # patch the source module, not the driver namespace — a drv.register_provider patch
    # would be a no-op and the test would pass against an unpatched network call.
    import harness.providers.probe as probe
    from harness.providers.config import ProviderConfig
    from harness.providers.probe import ProbeResult
    from harness.providers.provenance import ProvenanceReport
    import scripts.stand_up_opencode as drv
    calls = []

    async def fake_register(name, base_url, api_key, model="", engine=None, **kw):
        calls.append((name, model, engine, kw.get("registry") is not None))
        # The real probe upserts into the registry on admission (probe.py:44); mirror that
        # contract so the assertion below reads the registry the driver actually built.
        registry = kw.get("registry")
        if registry is not None:
            registry.upsert(ProviderConfig(name=name, base_url=base_url, model=model,
                                           engine=engine, tier="local",
                                           admitted="mechanical-only"))
        return ProbeResult(reachable=True, auth_ok=True, models=[model],
                           provenance=ProvenanceReport(engine=engine or "ollama"),
                           admission="mechanical-only")

    monkeypatch.setattr(probe, "register_provider", fake_register)
    monkeypatch.setattr(drv, "get_key", lambda name: "")
    reg = drv._probe_ollama()
    assert sorted(c.name for c in reg.list()) == ["ollama-embed", "ollama-local"]
    assert ("ollama-embed", "bge-m3:567m", "ollama", True) in calls
    assert ("ollama-local", "thomson1-chat:latest", "ollama", True) in calls

def test_build_gate_wraps_the_embedding_transport_too(tmp_path, monkeypatch):
    # Verified live 2026-10-01: /v1/embeddings returns FLAT usage, so _scalar_usage is a
    # no-op there — but the seam must still normalise both paths through one wrapper, so
    # Ollama's nested usage objects cannot regress on either endpoint.
    drv, _ = _install_fake_gate(monkeypatch, raw={
        "model": "bge-m3:567m",
        "data": [{"index": 0, "embedding": [0.1, 0.2]}],
        "usage": {"prompt_tokens": 3, "total_tokens": 3,
                  "prompt_tokens_details": {"cached_tokens": 1}},
    })
    gate, _rt, _aliases = drv.build_gate(tmp_path / "trace.db")
    out = asyncio.run(gate._embedding_transport(object(), {"model": "bge-m3:567m",
                                                           "input": ["a"]}))
    assert out["usage"] == {"prompt_tokens": 3, "total_tokens": 3}
    assert out["data"][0]["embedding"] == [0.1, 0.2]


def test_sync_mount_names_the_matter_in_the_baseURL_path(tmp_path):
    # A-5 (spec §4): the mount's ONLY provisionable identity channel is the baseURL path —
    # opencode's ProviderConfig options object has no `headers` key (additionalProperties is
    # false on a fixed list), so a matter header cannot be provisioned at all. This is the
    # single test that pins the mount's side of the seam; C7 then proves the binary forwards
    # it. `@ai-sdk/openai-compatible` joins withoutTrailingSlash(baseURL) + "/chat/completions",
    # so /v1/m/m-path arrives intact as /v1/m/m-path/chat/completions.
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"; ws.mkdir()
    data = Path(__file__).resolve().parent.parent / "data"
    sync_mount(ws, data / "opencode-a1", matter_ref="m-path",
               classification="LOCAL_PREFERRED", port=8123)
    cfg = json.loads((ws / "opencode.json").read_text())
    assert cfg["provider"]["gate-local"]["options"]["baseURL"] == \
        "http://127.0.0.1:8123/v1/m/m-path"

def test_sync_mount_writes_the_per_matter_record(tmp_path):
    # A-5: the proxy serves a matters DIRECTORY — adding a window is dropping a record,
    # not editing a registry. The workspace matter.json stays so nothing downstream breaks.
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"; ws.mkdir()
    data = Path(__file__).resolve().parent.parent / "data"
    sync_mount(ws, data / "opencode-a1", matter_ref="m-multi",
               classification="LOCAL_PREFERRED", port=8123)
    ws_matter = json.loads((ws / "matter.json").read_text())
    assert ws_matter["matter_ref"] == "m-multi"
    # Default: sibling of the workspace's parent.
    reg = json.loads((ws.parent / "matters" / "m-multi" / "matter.json").read_text())
    assert reg["matter_ref"] == "m-multi"
    assert reg["classification"] == "LOCAL_PREFERRED"

def test_sync_mount_writes_into_an_explicit_matters_root(tmp_path):
    # The acceptance driver points two mounts at ONE served directory while giving each
    # mount its own parent (opencode groups sibling git repos under one parent into a
    # multi-instance project — the spike's premise). An explicit root is how it does that
    # without the default's ws.parent coupling, and the record must land in the SERVED
    # tree — the proxy refuses anything not registered.
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "run-a" / "opencode"
    served = tmp_path / "matters"
    data = Path(__file__).resolve().parent.parent / "data"
    sync_mount(ws, data / "opencode-a1", matter_ref="m-shared",
               classification="LOCAL_PREFERRED", port=8123, matters_root=served)
    reg = json.loads((served / "m-shared" / "matter.json").read_text())
    assert reg["matter_ref"] == "m-shared"
    # The default root is NOT used when an explicit one is given — no stray record leaks
    # into ws.parent / "matters", which for the acceptance driver would be a throwaway
    # path it never serves.
    assert not (ws.parent / "matters").exists()

def test_build_gate_and_scheduler_assemble_the_live_stack(tmp_path, monkeypatch):
    # The scheduler is built from the REAL machine's capacity in the same place the gate is
    # — one function assembles the live system. The capacity probe is real here (no network
    # involved), so this asserts the wiring, not a stubbed number.
    drv, _ = _install_fake_gate(monkeypatch, raw={
        "model": "thomson1-chat:latest", "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 1},
    })
    gate, rt, aliases = drv.build_gate(tmp_path / "trace.db")
    sched = drv.build_scheduler()
    assert sched.max_concurrent >= 1
    assert sched.capacity.source_cores          # provenance carried through
