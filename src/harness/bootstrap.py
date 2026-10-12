"""Live-stack construction: probe -> registry -> gate, and the machine's scheduler.

Moved verbatim from scripts/stand_up_opencode.py, which now re-exports these under the
same names — the six acceptance drivers and the tests import build_gate from there and
must not notice. The move gives harness.ops.ironfleet_launcher (the production entry
point, S7g-M) a scripts-free import path: PyInstaller's static analysis cannot see a
namespace `scripts` package that is not on sys.path.

The one deliberate signature change: build_gate takes the routing YAML as a REQUIRED
argument. The repo default (data/routing-a1.yaml) stays in the script layer, which
knows where the repo's data is; a library function cannot.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from harness.alias import load_aliases
from harness.gate import EgressGate
from harness.keychain import get_key
from harness.policy import RoutingTable
from harness.providers.http_fetch import openai_fetch
from harness.trace import TraceStore

OLLAMA_URL = "http://127.0.0.1:11434/v1"


def _scalar_usage(result: dict) -> dict:
    """Keep only the scalar token counts in a provider usage dict.

    Ollama's /v1 endpoint returns OpenAI-shaped usage whose prompt_tokens_details /
    completion_tokens_details are OBJECTS ({"cached_tokens": 3930}). LLMResponse.usage is
    typed dict[str, int] — gate.py is byte-locked for this plan — so a nested object fails
    validation at dispatch and the call 502s; opencode marks that isRetryable and replays it,
    so one query lands as a fan of identical rows instead of a single dispatch (observed
    live: 9 rows, rc=1). The breakdown objects are optional in the OpenAI schema; the scalar
    counts are what the gate traces and what the SDK consumes."""
    usage = result.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {k: v for k, v in usage.items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return result


def build_gate(trace_path: Path, routing: Path) -> tuple[EgressGate, RoutingTable, dict]:
    rt = RoutingTable.from_yaml(routing)
    aliases = load_aliases(routing)   # the model catalog OpenCode sees
    trace = TraceStore(trace_path)
    reg = _probe_ollama()
    gate = EgressGate(reg, rt, trace)          # default transport talks to Ollama
    # The transport seam is the one non-byte-locked place to normalise provider response
    # shape before the gate validates it. Wrapping the gate's own default transports
    # (rather than reimplementing them) keeps the key/baseURL logic in one place.
    # _default_transport / _default_embedding_transport are private in gate.py — this
    # coupling is deliberate and this guard is the seam's side of it: if gate.py renames
    # or restructures either attribute, fail loudly and EARLY, here, with something
    # actionable. A bare AttributeError would instead surface at live-run time, because
    # every suite test stubs build_gate (it probes real Ollama).
    _ATTRS = ("_default_transport", "_default_embedding_transport")
    transports = {}
    missing = []
    for _attr in _ATTRS:
        _t = getattr(gate, _attr, None)
        if not callable(_t):
            missing.append(_attr)
        else:
            transports[_attr] = _t
    if missing:
        raise RuntimeError(
            f"{type(gate).__name__} no longer exposes {', '.join(missing)} — the transport "
            f"seams in build_gate need the gate's default transports to wrap. If gate.py "
            f"renamed or restructured these attributes, re-point these seams (and the "
            f"{_ATTRS} references) at the replacements; do not silently fall back to an "
            f"unwrapped transport, or Ollama's nested usage objects will fail validation "
            f"inside dispatch again.")

    def _wrap(_t):
        async def _transport(provider, payload):
            result = await _t(provider, payload)
            return _scalar_usage(result)
        return _transport
    gate._transport = _wrap(transports["_default_transport"])
    gate._embedding_transport = _wrap(transports["_default_embedding_transport"])
    return gate, rt, aliases


def build_scheduler(capacity: "Capacity | None" = None) -> "TurnScheduler":
    """The scheduler for the live stack, from the real machine's capacity (spec §3).

    Built in the same place build_gate assembles the gate, so one module owns the live
    system's construction. An explicit capacity is for tests; the live path probes."""
    from harness.capacity import machine_capacity, Capacity
    from harness.scheduler import TurnScheduler
    return TurnScheduler(capacity if capacity is not None else machine_capacity())


def _probe_ollama():
    """CR-3: the registry is populated by evidence, never hand-edited.

    Both providers are registered through the SAME probe: the embedding slot is a
    gate-classified provider, not a new kind of provider (spec §1 item 3)."""
    from harness.providers.config import ProviderRegistry
    from harness.providers.probe import register_provider
    reg = ProviderRegistry()
    # register_provider is a coroutine (it awaits openai_fetch over the network); the
    # driver is synchronous, so drive it to completion here. Calling it unawaited would
    # hand back a coroutine object and every attribute read below would blow up at
    # live-run time — the unit tests cannot see this, build_gate is stubbed there.
    specs = [("ollama-local", "thomson1-chat:latest"), ("ollama-embed", "bge-m3:567m")]
    for name, model in specs:
        res = asyncio.run(register_provider(name, OLLAMA_URL, get_key(name) or "",
                                            model=model, engine="ollama",
                                            registry=reg, fetch=openai_fetch))
        if res.admission == "refused":
            print(f"[gate] {name} REFUSED: reachable={res.reachable} "
                  f"auth={res.auth_ok} models={res.models}", file=sys.stderr)
        else:
            print(f"[gate] {name} admitted as {res.admission} "
                  f"(verified={res.provenance.verified})", file=sys.stderr)
    return reg
