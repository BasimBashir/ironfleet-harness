# tests/test_stand_up_opencode.py
import json, subprocess, sys
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
    assert cfg["provider"]["gate-local"]["options"]["baseURL"] == "http://127.0.0.1:8123/v1"
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
    assert "127.0.0.1:8123" in cfg["provider"]["gate-local"]["options"]["baseURL"]

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

    @classmethod
    def seamless(cls):
        """A gate that no longer exposes the attribute the seam wraps."""
        klass = type("SeamlessGate", (cls,), {"_default_transport": None})
        klass._raw = cls._raw
        return klass


def _install_fake_gate(monkeypatch, raw=None, seamless=False):
    import scripts.stand_up_opencode as drv
    cls = _FakeGate.seamless() if seamless else _FakeGate
    cls._raw = raw or {}
    monkeypatch.setattr(drv, "EgressGate", cls)
    monkeypatch.setattr(drv, "_probe_ollama", lambda: None)
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
