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
import os
import sys
from pathlib import Path

from harness.alias import load_aliases
from harness.gate import EgressGate
from harness.keychain import get_key
from harness.policy import RoutingTable
from harness.providers.http_fetch import openai_fetch
from harness.trace import TraceStore

# R3 (2026-10-19): the provider registry — url + model + engine + kind + provenance
# per row — lives in data/providers.yaml, loaded by _provider_specs below. Code no
# longer hardcodes any endpoint: a user swapping provider/model/url edits that file
# (or sets IRONFLEET_<NAME>_URL/_MODEL/_REVISION), and the key lands in the keychain
# via `harness providers set-key`. See _probe_ollama.


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


def _saved_settings() -> dict:
    """<store_root>/model-settings.json (written by service/settings.py); {} when
    absent or unparsable — a corrupt settings file must not take dispatch down."""
    import json
    from harness.paths import resolve_store_root
    try:
        doc = json.loads((resolve_store_root()[0] / "model-settings.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _apply_assign(rt: RoutingTable) -> None:
    """M13.7: the admin's manual per-stage assignment leads route()'s candidates — any
    provider, not just the YAML-listed ones (policy.RoutingTable.assign); gate.py's
    availability walk still falls back to the rest. Applied at gate build: an
    assignment lands on the next build_gate (a restart, or a fresh dispatch session)."""
    assign = _saved_settings().get("assign")
    rt.assign = assign if isinstance(assign, dict) else {}


def build_gate(trace_path: Path, routing: Path) -> tuple[EgressGate, RoutingTable, dict]:
    rt = RoutingTable.from_yaml(routing)
    _apply_assign(rt)
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


def _validate_url_override(env_var: str, url: str, declared_hosts: set[str]) -> str:
    """M1/S9: IRONFLEET_<NAME>_URL is an untrusted seam — whoever sets it points a
    'provider' at an endpoint that would receive matter documents and the bearer key.
    Allowed: http/https to the loopback (the local gate/proxy/ollama), or https to a
    host the operator already declared in providers.yaml. Everything else (bad scheme,
    userinfo, undeclared host, unparsable) raises naming the env var; valid, the url
    comes back unchanged."""
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
    except ValueError as ex:
        raise ValueError(f"{env_var}: unparsable URL {url!r} ({ex})") from ex
    host = u.hostname or ""
    if (u.scheme in ("http", "https") and not u.username and not u.password
            and (host in ("127.0.0.1", "localhost", "::1")
                 or (u.scheme == "https" and host in declared_hosts))):
        return url
    raise ValueError(f"{env_var}: URL override {url!r} is outside the allow-list "
                     f"(http/https loopback or https to a declared provider host)")


def _provider_specs(path: Path | None = None, saved: dict | None = None) -> list[dict]:
    """The provider registry AS DATA (data/providers.yaml) — one row = url + model +
    engine + kind, so a user swapping provider/model/url edits data, never code.

    Required by R3 (2026-10-19, user directive): when the provider and model change,
    the target URL changes WITH them — that coupling is the row. Env override per row:
    IRONFLEET_<NAME>_URL / _MODEL / _REVISION (name upper-cased, '-' kept), for quick
    swaps with no file edit. M1/S9: a _URL override is validated against the allow-list
    (_validate_url_override) — it is env-settable, unlike the file itself. A missing
    file raises (never silently probes nothing): the same fail-loud shape as
    cli.default_routing's stranded-data check.

    M13.7: on the live (path=None) read, the admin's Settings-tab edits apply on top —
    saved["providers"][name] overrides base_url/model, saved["custom"] appends rows
    (URLs validated when saved, service/settings._url). Env overrides still win."""
    import yaml
    if path is None:
        saved = _saved_settings() if saved is None else saved
    saved = saved or {}
    p = path or (Path(__file__).resolve().parents[2] / "data" / "providers.yaml")
    if not p.is_file():
        raise FileNotFoundError(f"provider registry not found at {p} — the distribution "
                               f"ships data/ at its repo paths; reinstall or set the file")
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    rows = doc.get("providers") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"provider registry {p}: no 'providers' rows — refusing to probe")
    edits = saved.get("providers") or {}
    rows = [{**r, **{k: v for k, v in (edits.get(r["name"]) or {}).items()
                     if k in ("base_url", "model")}} for r in rows]
    rows += [c for c in saved.get("custom") or []      # a hand-mangled row is skipped, not fatal
             if isinstance(c, dict) and all(c.get(k) for k in ("name", "base_url", "model", "engine"))]
    from urllib.parse import urlparse
    declared = {urlparse(r["base_url"]).hostname for r in rows}
    out = []
    for row in rows:
        env = "IRONFLEET_" + row["name"].upper().replace("-", "_")
        url_env = f"{env}_URL"
        override = os.environ.get(url_env)
        # D-T3: the user-declared context window + reliability-derived safe fill ride
        # the row too — the R3 shell's used-vs-remaining meter and auto-/compact read
        # these, so swapping models keeps the meter honest. Env-overridable like the rest.
        out.append({
            "name": row["name"],
            "base_url": (_validate_url_override(url_env, override, declared)
                         if override is not None else row["base_url"]),
            "model": os.environ.get(f"{env}_MODEL", row["model"]),
            "engine": row["engine"],
            "kind": row.get("kind", "chat"),
            "declared": {"weights_revision": os.environ.get(
                f"{env}_REVISION", row.get("weights_revision", ""))},
            "context_window": int(os.environ.get(
                f"{env}_CONTEXT_WINDOW", row.get("context_window", 0)) or 0),
            "safe_fill": float(os.environ.get(
                f"{env}_SAFE_FILL", row.get("safe_fill", 0.8)) or 0.8),
        })
    return out


def _probe_ollama(path: Path | None = None):
    """CR-3: the registry is populated by evidence, never hand-edited.

    Every row in data/providers.yaml is registered through the SAME probe (the embedding
    slot is a gate-classified provider, not a new kind of provider — spec §1 item 3)."""
    from harness.providers.config import ProviderRegistry
    from harness.providers.probe import register_provider
    reg = ProviderRegistry()
    # register_provider is a coroutine (it awaits openai_fetch over the network); the
    # driver is synchronous, so drive it to completion here. Calling it unawaited would
    # hand back a coroutine object and every attribute read below would blow up at
    # live-run time — the unit tests cannot see this, build_gate is stubbed there.
    for spec in _provider_specs(path):
        res = asyncio.run(register_provider(spec["name"], spec["base_url"],
                                            get_key(spec["name"]) or "",
                                            model=spec["model"], engine=spec["engine"],
                                            kind=spec["kind"], declared=spec["declared"],
                                            registry=reg, fetch=openai_fetch))
        if res.admission == "refused":
            print(f"[gate] {spec['name']} REFUSED: reachable={res.reachable} "
                  f"auth={res.auth_ok} models={res.models}", file=sys.stderr)
        else:
            print(f"[gate] {spec['name']} admitted as {res.admission} "
                  f"(verified={res.provenance.verified})", file=sys.stderr)
    return reg
