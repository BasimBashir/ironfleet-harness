"""Stand up an OpenCode 1.18.25 workspace that talks ONLY to the egress gate.

Reusable primitives come from the spike driver (run_spike_opencode.py), which already
survived the live hazards: workspaces that are not their own git repo get a sibling
repo's instance attached; an inherited PWD != cwd steers instance resolution the same
way; cmd.exe truncates multi-line prompt args at newlines; orphaned opencode.exe
children need taskkill /T /F.

Usage:
  .venv/Scripts/python.exe scripts/stand_up_opencode.py \
      --matter-ref <uuid> --task-class extraction --prompt-file task.txt
"""
from __future__ import annotations

import argparse, asyncio, json, os, shutil, subprocess, sys, time
from pathlib import Path

from harness.alias import load_aliases
from harness.egress_proxy import EgressProxy
from harness.gate import EgressGate
from harness.module_e.skills import sync_skills
from harness.module_e.guard import render_guard_plugin
from harness.module_e.personas import generate_all
from harness.module_e.tools import ToolEntry, declared_tools, load_manifest, ported_tools
from harness.policy import RoutingTable
from harness.providers.probe import register_provider
from harness.providers.http_fetch import openai_fetch
from harness.keychain import get_key
from harness.trace import TraceStore

HOST, PORT = "127.0.0.1", 7373
ROOT = Path(__file__).resolve().parents[1]
# run_opencode_session resolves the spike driver by package path (scripts.run_spike_opencode),
# and scripts/ carries no __init__.py: run as a CLI, sys.path[0] is scripts/ itself, so that
# import cannot resolve without the repo root on sys.path (observed live 2026-10-01 — the gate
# came up, then the session died on ModuleNotFoundError before opencode ever started).
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
MOUNT = DATA / "opencode-a1"
MODULE_E = DATA / "module-e"
PLUGIN_SRC = ROOT / "src" / "harness" / "spike" / "candidates" / "opencode"
GUARD_TEMPLATE = PLUGIN_SRC / "ironfleet-guard-s7c.ts"
TOOLS_TEMPLATE = PLUGIN_SRC / "ironfleet-tools.ts"
GUARD_CLI = ROOT / "src" / "harness" / "spike" / "guard_cli.py"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
ROUTING = DATA / "routing-a1.yaml"
OLLAMA_URL = "http://127.0.0.1:11434/v1"
OPENCODE_EXE = os.path.join(os.environ.get("APPDATA", ""), "npm", "opencode.cmd")

# Env hardening from precheck §5: no model-catalog fetch, no telemetry handshake.
HARDEN_ENV = {
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}

# Variables that make opencode activate a BUILTIN provider, by name (exact) and by family
# (prefix). S7b final review finding S1: the child otherwise inherits the full parent env, and
# on a machine holding any of these the mount's single-provider guarantee is gone — the agent
# can select a provider that never touches the gate. Verified live 2026-10-01 against the
# pinned binary in a synced mount workspace: `opencode models` resolved 275 models
# (anthropic 19, openai 61, amazon-bedrock 178) under the key set a parent process might hold,
# where a scrubbed env resolves only gate-local (9).
#
# Prefixes, not just a name list — the names that activate a provider are not the names that
# read like bearer keys. Two cases found live:
#   * AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (the standard pair — there is no
#     "AWS_BEDROCK_API_KEY") light up amazon-bedrock, and so does bare AWS_REGION with no
#     credential at all: a region is enough to make the provider and its 178 models
#     SELECTABLE, which is the surface S1 is about, credential or not.
#   * this box carries ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL, which do NOT activate
#     anthropic on 1.18.25 (only ANTHROPIC_API_KEY does) but are bearer credentials and a
#     redirect target, so the whole family goes rather than relying on that accident.
BEARER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_GENERATIVE_AI_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AWS_BEDROCK_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
)
BEARER_ENV_PREFIXES = (
    "ANTHROPIC_",
    "OPENAI_",
    "GOOGLE_",
    "GEMINI_",
    "AZURE_",
    "AWS_",
    "DEEPSEEK_",
    "GROQ_",
    "MISTRAL_",
    "OPENROUTER_",
    "XAI_",
)


def bearer_keys(env: dict[str, str]) -> list[str]:
    """Which of `env`'s keys the scrub would drop — the one definition of "bearer" that both
    child_env and the rig's child-env check use, so they cannot drift apart."""
    out = []
    for key in env:
        if key in BEARER_ENV_KEYS or key.startswith(BEARER_ENV_PREFIXES):
            out.append(key)
    return sorted(out)


def child_env(ws: Path | str) -> dict[str, str]:
    """The env opencode's child must run under: the parent's env, PWD re-pinned to the
    workspace (instance resolution reads PWD, not cwd), the precheck §5 hardening, and NO
    provider credential or provider-activating variable.

    Copy-on-write by construction: this builds a new dict and never assigns into os.environ,
    so scrubbing cannot leak into the parent process (the previous hardening path mutated
    os.environ in main() and left the values set for the rest of the driver).

    The scrub closes the *credential* half of S1 only. The keyless `opencode/*` catalog
    models need no variable at all and survive any env scrub — `disabled_providers` in
    data/opencode-a1/opencode.json closes that half. Neither layer alone yields a
    gate-local-only provider set; verify_opencode_mount.py --live asserts the composition
    against the real binary."""
    env = {**os.environ, "PWD": str(ws), **HARDEN_ENV}
    for key in bearer_keys(env):
        del env[key]
    return env


def render_tools_plugin(template: str, ws: Path, python: str, manifest: Path,
                        entries: list[ToolEntry]) -> str:
    """Substitute the tools shim's four placeholders.

    The TOOLS payload is a JSON array literal, not a bare comma list — the same lesson as the
    guard's annotation whitelist (an unbracketed list renders something that matches nothing) —
    and json.dumps keeps descriptions containing quotes/backslashes valid TypeScript."""
    tools = json.dumps([{"name": e.name, "description": e.description}
                        for e in sorted(entries, key=lambda e: e.name)], ensure_ascii=False)
    return (template.replace("__SPIKE_WS__", str(ws).replace("\\", "/"))
                    .replace("__PYTHON__", str(python).replace("\\", "/"))
                    .replace("__MANIFEST__", str(manifest).replace("\\", "/"))
                    .replace("__TOOLS__", tools))


def sync_mount(ws: Path, mount: Path, matter_ref: str, classification: str,
               port: int = PORT) -> None:
    """Copy the mount into the workspace and write the matter record, then assemble the full
    S7c mount: every persona/variant agent file and its drive twin, the 26 skill documents,
    the guard and tools plugins rendered from the committed templates, and the guard's
    authorities.

    The baseURL port is substituted to match the proxy we will bind — never discovered
    from a free port, because then the mount could point at anything listening."""
    # Isolation seam (spike, observed 2026-09-01): OpenCode groups sibling git repos under
    # one parent into a multi-instance project, and a workspace that is not itself a repo
    # adopts a sibling's instance. The workspace must be its own repo — init only, no
    # commits, so the matter never enters any history.
    # The driver's callers may hand us a workspace that does not exist yet; git init below needs
    # a real cwd, and every later write needs the tree.
    ws.mkdir(parents=True, exist_ok=True)
    if not (ws / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(ws), check=True,
                       capture_output=True)
    (ws / ".opencode" / "agent").mkdir(parents=True, exist_ok=True)
    # baseURL lives under "options" — opencode's ProviderConfig schema is
    # additionalProperties:false, so a top-level baseURL is silently ignored at runtime and
    # the SDK builds "undefined/chat/completions". The spike's proven mount puts it here
    # (src/harness/spike/candidates/opencode/opencode.json).
    cfg = json.loads((mount / "opencode.json").read_text())
    cfg["provider"]["gate-local"].setdefault("options", {})["baseURL"] = \
        f"http://{HOST}:{port}/v1"
    (ws / "opencode.json").write_text(json.dumps(cfg, indent=2))
    (ws / "matter.json").write_text(json.dumps(
        {"matter_ref": matter_ref, "classification": classification}, indent=2))

    # --- S7c Module E (Task 10). The manifest is loaded ONCE and drives everything below, so
    # the personas' enablement, the guard's annotation whitelist and the tools shim's tool list
    # cannot drift apart: they are three projections of the same rows.
    manifest = load_manifest(MODULE_E / "tools.yaml")
    declared, ported = declared_tools(manifest), ported_tools(manifest)
    generate_all(MODULE_E / "personas.yaml", MODULE_E / "personas", ws / ".opencode" / "agent",
                 declared=declared, ported=ported)
    sync_skills(MODULE_E / "skills", ws / ".opencode" / "skills")
    (ws / ".opencode" / "plugins").mkdir(parents=True, exist_ok=True)
    plugins = {
        "ironfleet-guard.ts": render_guard_plugin(
            GUARD_TEMPLATE.read_text(encoding="utf-8"), ws=ws, python=str(PYTHON),
            guard_cli=str(GUARD_CLI), whitelist=ported),
        "ironfleet-tools.ts": render_tools_plugin(
            TOOLS_TEMPLATE.read_text(encoding="utf-8"), ws=ws, python=str(PYTHON),
            manifest=MODULE_E / "tools.yaml",
            entries=[t for t in manifest.values() if t.status == "ported"]),
    }
    for name, body in plugins.items():
        (ws / ".opencode" / "plugins" / name).write_text(body, encoding="utf-8")
    # Guard authorities: annotate-only and empty until a driver run writes real ones — the same
    # starting state the spike's sync_workspace ships (fail-closed in the plugin if unreadable).
    (ws / "allowed.json").write_text(json.dumps({"allowed": [], "block": False}),
                                     encoding="utf-8")
    # fresh guard log per sync (evidence lives in the transcripts and the sidecar too)
    (ws / "guard-log.jsonl").write_text("", encoding="utf-8")


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


def build_gate(trace_path: Path, routing: Path | None = None) -> tuple[EgressGate, RoutingTable, dict]:
    rt = RoutingTable.from_yaml(routing or ROUTING)
    aliases = load_aliases(routing or ROUTING)   # the model catalog OpenCode sees
    trace = TraceStore(trace_path)
    reg = _probe_ollama()
    gate = EgressGate(reg, rt, trace)          # default transport talks to Ollama
    # The transport seam is the one non-byte-locked place to normalise provider response
    # shape before gate.dispatch validates it. Wrapping the gate's own default transport
    # (rather than reimplementing it) keeps the key/baseURL logic in one place.
    # _default_transport is private in gate.py — this coupling is deliberate and this guard
    # is the seam's side of it: if gate.py renames or restructures the attribute, fail loudly
    # and EARLY, here, with something actionable. A bare AttributeError would instead surface
    # at live-run time, because every suite test stubs build_gate (it probes real Ollama).
    _ATTR = "_default_transport"
    _default_transport = getattr(gate, _ATTR, None)
    if not callable(_default_transport):
        raise RuntimeError(
            f"{type(gate).__name__} no longer exposes {_ATTR} — the transport seam in "
            f"build_gate needs the gate's default transport to wrap. If gate.py renamed or "
            f"restructured it, re-point this seam (and the {_ATTR} reference) at the "
            f"replacement; do not silently fall back to an unwrapped transport, or Ollama's "
            f"nested usage objects will fail validation inside dispatch again.")

    async def _transport(provider, payload):
        result = await _default_transport(provider, payload)
        return _scalar_usage(result)
    gate._transport = _transport
    return gate, rt, aliases


def _probe_ollama():
    """CR-3: the registry is populated by evidence, never hand-edited."""
    from harness.providers.config import ProviderRegistry
    reg = ProviderRegistry()
    key = get_key("ollama-local") or ""
    # register_provider is a coroutine (it awaits openai_fetch over the network); the
    # driver is synchronous, so drive it to completion here. Calling it unawaited would
    # hand back a coroutine object and every attribute read below would blow up at
    # live-run time — the unit tests cannot see this, build_gate is stubbed there.
    res = asyncio.run(register_provider("ollama-local", OLLAMA_URL, key,
                                        model="thomson1-chat:latest", engine="ollama",
                                        registry=reg, fetch=openai_fetch))
    if res.admission == "refused":
        print(f"[gate] ollama-local REFUSED: reachable={res.reachable} "
              f"auth={res.auth_ok} models={res.models}", file=sys.stderr)
    else:
        print(f"[gate] ollama-local admitted as {res.admission} "
              f"(verified={res.provenance.verified})", file=sys.stderr)
    return reg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matter-ref", required=True)
    ap.add_argument("--task-class", default="extraction")
    ap.add_argument("--classification", default="LOCAL_PREFERRED")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--prompt", default=None, help="prompt text (default: a smoke prompt)")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args(argv)

    # Distinct parent from the spike's ~/spike-ws/opencode: opencode groups sibling git
    # repos under one parent into a multi-instance project and the session can attach the
    # WRONG instance (spike, observed 2026-09-01: session directory=harness-core despite
    # cwd=spike-ws). ~/spike-ws-a1 has no sibling repos to adopt — the spike's own premise
    # (run_spike_opencode.py:57-60), preserved by not reusing its parent.
    ws = Path(args.workspace) if args.workspace else Path.home() / "spike-ws-a1" / "opencode-a1"
    ws.mkdir(parents=True, exist_ok=True)
    sync_mount(ws, MOUNT, args.matter_ref, args.classification, PORT)

    gate, rt, aliases = build_gate(ws / "trace.db")
    # ThreadingHTTPServer binds in its CONSTRUCTOR, so the port-collision guard must wrap
    # construction, not start() — start() only spawns the serve_forever thread and cannot
    # raise OSError. A bind failure here aborts rather than letting the mount's hardcoded
    # baseURL point at whatever else is listening on 7373.
    try:
        proxy = EgressProxy(HOST, PORT, gate, rt, aliases, ws / "matter.json")
    except OSError as ex:
        print(f"[gate] cannot bind {HOST}:{PORT} — refusing to start a mount that "
              f"would point elsewhere: {ex}", file=sys.stderr)
        return 2
    proxy.start()
    print(f"[gate] proxy on http://{HOST}:{PORT}/v1, models: "
          f"{sorted(aliases)}", file=sys.stderr)

    prompt = args.prompt or ("Extract the party names from the following text and "
                             "list them as bullets. Text: 'ACME Ltd and Beta Corp "
                             "entered into an agreement on 3 March 2026.'")
    # run_opencode's env seam takes the scrubbed env directly, so the driver's own process env
    # is never mutated: the hardening used to be written into os.environ and left there for the
    # remainder of the run, and a bearer-key scrub done that way would have been destructive and
    # irreversible on failure. child_env is pure — os.environ is read, never written.
    try:
        code, text = run_opencode_session(ws, f"gate/{args.task_class}", prompt,
                                          args.timeout, env=child_env(ws))
    finally:
        proxy.stop()
    print(text, file=sys.stderr)
    return code


def run_opencode_session(ws: Path, model: str, prompt: str, timeout: int,
                         env: dict[str, str] | None = None) -> tuple[int, str]:
    """Supervised, tree-killed opencode run; returns (exit code, final assistant text).

    Reuses the spike driver's proven primitives (not reinvented): run_opencode(ws, args,
    timeout) takes an argv list, builds its own env with PWD=ws scrubbed, and tree-kills
    on timeout. We only assemble the argv in the shape the spike verified live:
    `run --model <provider/model> --auto --format json <prompt>`. --format json so the
    final text is recoverable by extract_final_text(parse_events(raw)); the prompt is
    flattened because cmd.exe ends the command line at the first embedded newline.

    `env` is passed through to run_opencode; the caller passes child_env(ws) so the child
    runs without bearer credentials (finding S1). None keeps run_opencode's own default."""
    from scripts.run_spike_opencode import run_opencode, flatten_prompt, extract_final_text, parse_events
    code, raw = run_opencode(ws, ["run", "--model", f"gate-local/{model}", "--auto",
                                  "--format", "json", flatten_prompt(prompt)], timeout,
                             env=env)
    return code, extract_final_text(parse_events(raw))


if __name__ == "__main__":
    sys.exit(main())
