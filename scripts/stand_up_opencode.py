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
from harness.policy import RoutingTable
from harness.providers.probe import register_provider
from harness.providers.http_fetch import openai_fetch
from harness.keychain import get_key
from harness.trace import TraceStore

HOST, PORT = "127.0.0.1", 7373
DATA = Path(__file__).resolve().parent.parent / "data"
MOUNT = DATA / "opencode-a1"
ROUTING = DATA / "routing-a1.yaml"
OLLAMA_URL = "http://127.0.0.1:11434/v1"
OPENCODE_EXE = os.path.join(os.environ.get("APPDATA", ""), "npm", "opencode.cmd")

# Env hardening from precheck §5: no model-catalog fetch, no telemetry handshake.
HARDEN_ENV = {
    "OPENCODE_DISABLE_MODELS_FETCH": "1",
    "OPENCODE_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}


def sync_mount(ws: Path, mount: Path, matter_ref: str, classification: str,
               port: int = PORT) -> None:
    """Copy the mount into the workspace and write the matter record.

    The baseURL port is substituted to match the proxy we will bind — never discovered
    from a free port, because then the mount could point at anything listening."""
    # Isolation seam (spike, observed 2026-09-01): OpenCode groups sibling git repos under
    # one parent into a multi-instance project, and a workspace that is not itself a repo
    # adopts a sibling's instance. The workspace must be its own repo — init only, no
    # commits, so the matter never enters any history.
    if not (ws / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(ws), check=True,
                       capture_output=True)
    (ws / ".opencode" / "agent").mkdir(parents=True, exist_ok=True)
    cfg = json.loads((mount / "opencode.json").read_text())
    cfg["provider"]["gate-local"]["baseURL"] = f"http://{HOST}:{port}/v1"
    (ws / "opencode.json").write_text(json.dumps(cfg, indent=2))
    (ws / "matter.json").write_text(json.dumps(
        {"matter_ref": matter_ref, "classification": classification}, indent=2))


def build_gate(trace_path: Path) -> tuple[EgressGate, RoutingTable, dict]:
    rt = RoutingTable.from_yaml(ROUTING)
    aliases = load_aliases(ROUTING)       # the model catalog OpenCode sees
    trace = TraceStore(trace_path)
    reg = _probe_ollama()
    gate = EgressGate(reg, rt, trace)          # default transport talks to Ollama
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
    # Hardening lands in os.environ BEFORE run_opencode_session: run_opencode builds the
    # child env from os.environ (with PWD=ws), so an env argument would be ignored.
    for k, v in HARDEN_ENV.items():
        os.environ[k] = v
    try:
        code, text = run_opencode_session(ws, f"gate/{args.task_class}", prompt,
                                          args.timeout)
    finally:
        proxy.stop()
    print(text, file=sys.stderr)
    return code


def run_opencode_session(ws: Path, model: str, prompt: str, timeout: int) -> tuple[int, str]:
    """Supervised, tree-killed opencode run; returns (exit code, final assistant text).

    Reuses the spike driver's proven primitives (not reinvented): run_opencode(ws, args,
    timeout) takes an argv list, builds its own env with PWD=ws scrubbed, and tree-kills
    on timeout. We only assemble the argv in the shape the spike verified live:
    `run --model <provider/model> --auto --format json <prompt>`. --format json so the
    final text is recoverable by extract_final_text(parse_events(raw)); the prompt is
    flattened because cmd.exe ends the command line at the first embedded newline."""
    from scripts.run_spike_opencode import run_opencode, flatten_prompt, extract_final_text, parse_events
    code, raw = run_opencode(ws, ["run", "--model", f"gate-local/{model}", "--auto",
                                  "--format", "json", flatten_prompt(prompt)], timeout)
    return code, extract_final_text(parse_events(raw))


if __name__ == "__main__":
    sys.exit(main())
