# scripts/probe_r3_tui.py
"""R3 TUI research-gate probe driver (spec 16): P1-P7, live on opencode 1.18.25, no mocks.

Subcommands:
  python scripts/probe_r3_tui.py p1|p2|...|p7|all [--evidence-root DIR]

Every probe asserts the pin FIRST (spec 16 §7: drift = refuse to measure), starts the
gate-backed proxy itself, and writes <probe>.json + <probe>.log into the evidence dir
data/eval/R3-RESEARCH-<date>/. Live-driver discipline: the suite runs only pure helpers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess  # noqa: F401 — probe bodies (Tasks 3-9) shell out through it
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV_ROOT = ROOT / "data" / "eval"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_spike_opencode import (  # noqa: E402,F401 — Task 2's run helper consumes these
    extract_final_text, flatten_prompt, opencode_cmd, parse_events, run_opencode)

DEFAULT_TIMEOUT_S = 480  # the S7j-W watchdog budget; startup hang ~2 in 7


def _opencode_version() -> str:
    code, raw = run_opencode(ROOT, ["--version"], timeout=60)
    if code != 0:
        raise SystemExit(f"FAIL: opencode --version exited {code}: {raw[:200]}")
    return raw.strip().splitlines()[-1].strip()


def _autoupdate_global() -> bool:
    cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not cfg.is_file():
        return False
    return '"autoupdate": false' in cfg.read_text(encoding="utf-8")


def pin_check() -> dict:
    from harness.packaging.macdist import PINS
    # PINS holds the npm spec ("opencode-ai@1.18.25") while --version prints the bare
    # number — compare (and report) at the bare version so the gate OPENS on the pinned
    # box; a literal string == would refuse forever (verify_opencode_mount.py precedent).
    expected = PINS["opencode"].rsplit("@", 1)[-1]
    found = _opencode_version().rsplit("@", 1)[-1]
    auto = _autoupdate_global()
    return {"expected": expected, "found": found, "autoupdate": auto,
            "ok": found == expected and auto}


def require_pin() -> dict:
    report = pin_check()
    if not report["ok"]:
        # exit 3 per contract: acceptance must distinguish "pin drifted" (3) from
        # "probe crashed" (1) — a string SystemExit would collapse both to 1.
        print(f"REFUSING TO MEASURE — pin drift: {report} (spec 16 §7)", file=sys.stderr)
        raise SystemExit(3)
    return report


def evidence_dir(root: Path | None = None) -> Path:
    d = (root or EV_ROOT) / f"R3-RESEARCH-{date.today().isoformat()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_evidence(ev: Path, name: str, body: str) -> None:
    (ev / name).write_text(body, encoding="utf-8")


@dataclass
class RunResult:
    code: int
    raw: str
    events: list
    attempts: int
    label: str
    seconds: float


def run_capture(ws: Path, args: list[str], timeout: int = DEFAULT_TIMEOUT_S,
                env: dict[str, str] | None = None, label: str = "run",
                ev: Path | None = None) -> RunResult:
    """run_opencode + parse_events + evidence tee. Retries ONCE on the startup-hang
    signature (timeout tree-kill AND nothing parsed — the binary died before speaking).
    A second identical failure is fatal: two hangs in a row means the box or the mount
    is broken, and the probe must not burn the schedule retrying (spec 16 §7)."""
    t0 = time.monotonic()
    code, raw = run_opencode(ws, args, timeout=timeout, env=env)
    events = parse_events(raw)
    attempts = 1
    if code == 124 and not events:
        print(f"[{label}] hang signature (124, no events) — retrying once", flush=True)
        code, raw = run_opencode(ws, args, timeout=timeout, env=env)
        events = parse_events(raw)
        attempts = 2
        if code == 124 and not events:
            raise SystemExit(f"[{label}] hung twice — aborting probe")
    if ev is not None:
        _write_evidence(ev, f"{label}.log", raw)
    return RunResult(code, raw, events, attempts, label, time.monotonic() - t0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("probe", choices=[*PROBES, "all"])
    ap.add_argument("--evidence-root", type=Path, default=None)
    args = ap.parse_args(argv)
    ev = evidence_dir(args.evidence_root)
    require_pin()
    names = list(PROBES) if args.probe == "all" else [args.probe]
    results = {}
    for name in names:
        print(f"[{name}] running…", flush=True)
        results[name] = PROBES[name](ev)
        _write_evidence(ev, f"{name}.json", json.dumps(results[name], indent=2))
        print(f"[{name}] -> {json.dumps(results[name])[:400]}", flush=True)
    return 0


PROBES: dict[str, object] = {}  # populated per-probe below; registry validated by tests


def _stub(ev: Path) -> dict:
    raise NotImplementedError("probe lands in its own task")


for _n in ("p1", "p2", "p3", "p4", "p5", "p6", "p7"):
    PROBES[_n] = _stub


def canary_primary_md(name: str, token: str, tools: dict[str, bool] | None = None) -> str:
    """A minimal primary-mode agent that answers with exactly `token`. The token is the
    selectability oracle: if the final text contains it, THIS file drove the session —
    the default-agent fallback (S7i, live-proven) cannot know the token."""
    tool_lines = tools if tools is not None else {}
    body = {n: False for n in ("read", "glob", "grep", "task", "todowrite", "skill",
                               "bash", "edit", "write", "webfetch")}
    body.update(tool_lines)
    tool_yaml = "\n".join(f"  {k}: {str(v).lower()}" for k, v in body.items())
    return ("---\n"
            f"description: R3 probe canary ({name})\n"
            "mode: primary\n"
            "model: gate-local/research\n"
            "tools:\n"
            f"{tool_yaml}\n"
            "---\n"
            f"You are probe canary {name}. Whatever the user asks, reply with exactly "
            f"{token} and nothing else.\n")


WS_BASE = Path.home() / "spike-ws-a1"  # the S7c parent; probes add their own leaf dirs


def start_stack(ws: Path, matter_ref: str, matters_root: Path | None = None):
    """sync_mount + gate + scheduler + proxy. Returns (proxy, env). Caller MUST stop()."""
    from scripts.stand_up_opencode import (
        PORT, MOUNT, build_gate, child_env, sync_mount)
    from harness.bootstrap import build_scheduler
    from harness.egress_proxy import EgressProxy
    root = matters_root or ws.parent / "matters"
    sync_mount(ws, MOUNT, matter_ref, "LOCAL_PREFERRED", PORT, matters_root=root)
    gate, rt, aliases = build_gate(ws / "trace.db")
    scheduler = build_scheduler()
    proxy = EgressProxy("127.0.0.1", PORT, gate, rt, aliases, root, scheduler=scheduler)
    proxy.start()
    return proxy, child_env(ws)


P1_TOKEN = "R3-CANARY-TOKEN-9X"

def probe_p1(ev: Path) -> dict:
    from scripts.run_spike_opencode import flatten_prompt, extract_final_text
    ws = WS_BASE / "r3-p1"
    canary = "r3canary"
    proxy, env = start_stack(ws, "r3-p1")
    try:
        (ws / ".opencode" / "agent" / f"{canary}.md").write_text(
            canary_primary_md(canary, P1_TOKEN), encoding="utf-8")
        prompt = flatten_prompt("What is your token?")
        hit = run_capture(ws, ["run", "--agent", canary, "--model", "gate-local/research",
                               "--format", "json", prompt], label="p1-canary", ev=ev, env=env)
        miss = run_capture(ws, ["run", "--agent", "r3-nonexistent", "--model",
                                "gate-local/research", "--format", "json", prompt],
                           label="p1-fallback", ev=ev, env=env)
        # CLI surfaces that might list agents — record what exists, evidence for the verdict
        listing = {}
        for argv in (["--help"], ["run", "--help"], ["agent", "list"], ["agents"]):
            r = run_capture(ws, argv, timeout=60, label="p1-cli-" + argv[0].strip("-")[:12],
                            ev=ev, env=env)
            listing[" ".join(argv)] = {
                "code": r.code,
                "mentions_agent_flag": "agent" in r.raw.lower(),
            }
    finally:
        proxy.stop()
    hit_text = extract_final_text(hit.events)
    miss_text = extract_final_text(miss.events)
    return {
        "primary_selectable": hit.code == 0 and P1_TOKEN in hit_text,
        "fallback_silent": P1_TOKEN not in miss_text,
        "cli_agent_listing": listing,
        "final_texts": {"canary": hit_text[:400], "fallback": miss_text[:400]},
        "attempts": {"canary": hit.attempts, "fallback": miss.attempts},
    }


PROBES["p1"] = probe_p1  # AFTER the stub loop so p1's stub is overwritten


def custom_command_md(token: str) -> str:
    """A prompt-template command file; opencode custom commands need no frontmatter."""
    return f"Reply with exactly {token} and nothing else.\n"


def npm_pkg_dirs() -> list[Path]:
    """Candidates for the globally-installed opencode-ai package. APPDATA is read at
    CALL time so tests can monkeypatch it."""
    appdata = Path(os.environ.get("APPDATA", ""))
    return [appdata / "npm" / "node_modules" / "opencode-ai",
            appdata / "npm" / "node_modules" / "opencode-ai" / "node_modules" / "@opencode-ai"]


def probe_p2(ev: Path) -> dict:
    ws = WS_BASE / "r3-p2"
    proxy, env = start_stack(ws, "r3-p2")
    out: dict = {}
    try:
        # (a) custom command: drop the file, try the invocation variants run mode allows
        cmd_dir = ws / ".opencode" / "command"
        cmd_dir.mkdir(parents=True, exist_ok=True)
        (cmd_dir / "r3ping.md").write_text(custom_command_md("R3-CMD-TOKEN-4F"),
                                           encoding="utf-8")
        tried = {}
        for i, argv in enumerate((["run", "--format", "json", "/r3ping"],
                                  ["run", "--command", "r3ping", "--format", "json"],
                                  ["run", "--format", "json", "--command", "r3ping"]), 1):
            # unique label per variant: run_capture tees <label>.log, a shared one overwrites
            r = run_capture(ws, argv, timeout=180, label=f"p2-cmd-{i}", ev=ev, env=env)
            tried[" ".join(argv)] = "R3-CMD-TOKEN-4F" in r.raw
        out["custom_commands"] = {"tried": tried,
                                  "works_via": next((k for k, v in tried.items() if v), None)}
        # (b) plugin type surface: does the pinned package expose ANY TUI-facing plugin API?
        tui_mentions: list[str] = []
        files = 0
        for pkg in npm_pkg_dirs():
            if not pkg.is_dir():
                continue
            for dts in pkg.rglob("*.d.ts"):
                files += 1
                text = dts.read_text(encoding="utf-8", errors="replace")
                for kw in ("pane", "panel", "widget", "theme", "tui"):
                    if kw in text.lower():
                        tui_mentions.append(f"{dts.name}:{kw}")
        out["plugin_type_surface"] = {"files": files, "tui_mentions": sorted(set(tui_mentions))[:40]}
        # (c) custom panes: nothing above counts as a renderable-pane API => default False,
        # flipped only if tui_mentions shows a real component-registration surface
        out["custom_panes_possible"] = any(":pane" in m or ":panel" in m for m in tui_mentions)
    finally:
        proxy.stop()
    return out


PROBES["p2"] = probe_p2  # AFTER the stub loop so p2's stub is overwritten


if __name__ == "__main__":
    raise SystemExit(main())
