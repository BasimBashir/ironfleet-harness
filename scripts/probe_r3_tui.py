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
            # opencode's --model/frontmatter name is provider/CATALOG — the mount's models
            # map is keyed `gate/<task-class>` under provider `gate-local`, so the full
            # name is gate-local/gate/<task-class> (accept_s7f.py:359, accept_s7c.py:9,
            # accept_s7i.py:268 — the live-accepted drivers all use the doubled form).
            "model: gate-local/gate/extraction\n"
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
        hit = run_capture(ws, ["run", "--agent", canary, "--model", "gate-local/gate/extraction",
                               "--format", "json", prompt], label="p1-canary", ev=ev, env=env)
        miss = run_capture(ws, ["run", "--agent", "r3-nonexistent", "--model",
                                "gate-local/gate/extraction", "--format", "json", prompt],
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


ANCHOR = "R3-ANCHOR-7Q"


def storage_roots() -> list[Path]:
    """Candidate opencode session-storage roots (linux/mac + windows layouts)."""
    home = Path.home()
    return [home / ".local" / "share" / "opencode",
            home / ".local" / "state" / "opencode",
            home / "AppData" / "Local" / "opencode",
            home / "AppData" / "Roaming" / "opencode",
            home / ".opencode"]


def find_session_file(sid: str) -> Path | None:
    """First file under any storage root whose head mentions the session id.
    Live-only (acceptance): the full-tree rglob never runs under pytest."""
    for root in storage_roots():
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and sid in p.read_text(encoding="utf-8", errors="ignore")[:8000]:
                return p
    return None


def anchor_in(text: str) -> bool:
    return ANCHOR in text


def probe_p3(ev: Path) -> dict:
    import re
    ws = WS_BASE / "r3-p3"
    proxy, env = start_stack(ws, "r3-p3")
    out: dict = {"resume": {}}
    try:
        # A. plant the anchor
        a = run_capture(ws, ["run", "--model", "gate-local/gate/extraction", "--format", "json",
                             flatten_prompt(f"Remember the token {ANCHOR} for later. Reply ACK.")],
                        label="p3-a", ev=ev, env=env)
        m = re.search(r'"sessionID"\s*:\s*"([^"]+)"', a.raw)
        out["session_id"] = m.group(1) if m else None
        # B. locate + schema the stored record
        rec = find_session_file(out["session_id"]) if out["session_id"] else None
        out["storage_root"] = str(rec) if rec else None
        if rec:
            try:
                data = json.loads(rec.read_text(encoding="utf-8", errors="ignore"))
                out["session_record_keys"] = sorted(data) if isinstance(data, dict) else ["<non-dict>"]
            except json.JSONDecodeError:
                out["session_record_keys"] = ["<not-plain-json>"]
        # C. kill mid-run, then resume per flag variant
        k = run_capture(ws, ["run", "--model", "gate-local/gate/extraction", "--format", "json",
                             flatten_prompt("Count from 1 to 400, one number per line, no commentary.")],
                        timeout=30, label="p3-kill", ev=ev, env=env)
        out["killed_as_planned"] = k.code == 124
        follow = flatten_prompt("What token did I ask you to remember? Reply with just the token.")
        for flag_argv, name in ((["--continue"], "--continue"), (["-c"], "-c")):
            r = run_capture(ws, ["run", *flag_argv, "--model", "gate-local/gate/extraction",
                                 "--format", "json", follow],
                            label=f"p3-resume{name}", ev=ev, env=env)
            out["resume"][name] = anchor_in(extract_final_text(r.events))
        if out["session_id"]:
            r = run_capture(ws, ["run", "--session", out["session_id"], "--model",
                                 "gate-local/gate/extraction", "--format", "json", follow],
                            label="p3-resume-session", ev=ev, env=env)
            out["resume"]["--session"] = anchor_in(extract_final_text(r.events))
        out["context_continuity"] = any(out["resume"].values())
    finally:
        proxy.stop()
    return out


PROBES["p3"] = probe_p3  # AFTER the stub loop so p3's stub is overwritten


def intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _timed_run(ws, argv, env, ev, label, results, key):
    t0 = time.monotonic()
    r = run_capture(ws, argv, env=env, ev=ev, label=label)
    results[key] = {"start": t0, "end": time.monotonic(), "code": r.code, "label": label}


def probe_p4(ev: Path) -> dict:
    import threading
    from scripts.run_spike_opencode import flatten_prompt
    shared_matters = WS_BASE / "matters-r3p4"          # ONE served directory
    ws_a = WS_BASE / "r3-p4-a"                          # own parent (WS_BASE)
    ws_b = Path.home() / "spike-ws-a2" / "r3-p4-b"      # DIFFERENT parent (instance seam)
    proxy, env_a = start_stack(ws_a, "r3-p4-a", matters_root=shared_matters)
    # second mount under its own parent, same proxy + same matters root
    from scripts.stand_up_opencode import PORT, MOUNT, child_env, sync_mount
    sync_mount(ws_b, MOUNT, "r3-p4-b", "LOCAL_PREFERRED", PORT, matters_root=shared_matters)
    env_b = child_env(ws_b)
    prompt = flatten_prompt("Summarise in two sentences: contracts require consideration.")
    results: dict = {}
    try:
        t = []
        pairs = [("a1", ws_a, env_a), ("b1", ws_b, env_b)]
        for key, ws, env in pairs:
            th = threading.Thread(target=_timed_run, args=(
                ws, ["run", "--model", "gate-local/gate/extraction", "--format", "json", prompt],
                env, ev, f"p4-{key}", results, key))
            th.start(); t.append(th)
        for th in t: th.join()
        overlap = intervals_overlap((results["a1"]["start"], results["a1"]["end"]),
                                    (results["b1"]["start"], results["b1"]["end"]))
        # FIFO: two same-matter runs must serialize (a3 starts after a2 ends)
        t = []
        for key in ("a2", "a3"):
            th = threading.Thread(target=_timed_run, args=(
                ws_a, ["run", "--model", "gate-local/gate/extraction", "--format", "json", prompt],
                env_a, ev, f"p4-{key}", results, key))
            th.start(); t.append(th)
        for th in t: th.join()
        serialized = not intervals_overlap((results["a2"]["start"], results["a2"]["end"]),
                                           (results["a3"]["start"], results["a3"]["end"]))
    finally:
        proxy.stop()
    trace = (ws_a / "trace.db")
    rows = 0
    if trace.is_file():
        import sqlite3
        con = sqlite3.connect(str(trace)); con.row_factory = sqlite3.Row
        rows = len(con.execute(
            "SELECT * FROM dispatches WHERE matter_ref LIKE 'r3-p4%'").fetchall())
        con.close()
    return {"overlap": overlap, "serialized": serialized,
            "cap_observed": 2 if overlap else 1,
            "trace_rows": rows,
            "runs": {k: {kk: round(vv, 2) if isinstance(vv, float) else vv
                         for kk, vv in v.items()} for k, v in results.items()}}


PROBES["p4"] = probe_p4  # AFTER the stub loop so p4's stub is overwritten


def summarize_events(raw: str) -> dict:
    """Per-line JSON type tally. Tallies BOTH event levels: the top-level `type` AND the
    proven run-mode part-level type (extract_tool_texts keys on `part.type == "tool"`,
    run_spike_opencode.py:254 — a top-level-only tally blinds P5's tool_call_seen).

    Robust to any JSON line shape, same convention as parse_events: non-object JSON
    (`[1,2]`, `"x"`, `42`, `null`) is skipped, not fatal — one odd line must never abort
    P5 before its verdict lands. `parsed` counts TALLIES (a double-typed line adds 2),
    not lines, and is evidence-only."""
    types: dict[str, int] = {}
    bad = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(obj, dict):
            continue
        t = obj.get("type")
        if isinstance(t, str):
            types[t] = types.get(t, 0) + 1
        part = obj.get("part")
        if isinstance(part, dict):
            pt = part.get("type")
            if isinstance(pt, str):
                types[pt] = types.get(pt, 0) + 1
    return {"parsed": sum(types.values()), "types": types, "bad_lines": bad}


P5_PROMPT = ("Call the ironfleet_without_prejudice tool on this text: "
             "'The claim is discontinued with no admission of liability.' "
             "Then reply with the tool's output verbatim.")

def probe_p5(ev: Path) -> dict:
    from scripts.stand_up_opencode import PORT, MOUNT, build_gate, child_env, sync_mount
    from harness.bootstrap import build_scheduler
    from harness.egress_proxy import EgressProxy
    ws = WS_BASE / "r3-p5"
    root = ws.parent / "matters"
    sync_mount(ws, MOUNT, "r3-p5", "LOCAL_PREFERRED", PORT, matters_root=root)
    gate, rt, aliases = build_gate(ws / "trace.db")
    proxy = EgressProxy("127.0.0.1", PORT, gate, rt, aliases, root, scheduler=build_scheduler())
    proxy.start()
    try:
        env = child_env(ws)
        r = run_capture(ws, ["run", "--model", "gate-local/gate/toolpath", "--format", "json",
                             flatten_prompt(P5_PROMPT)], label="p5-toolpath", ev=ev, env=env)
    finally:
        proxy.stop()
    s = summarize_events(r.raw)
    guard_lines = 0
    gl = ws / "guard-log.jsonl"
    if gl.is_file():
        guard_lines = sum(1 for ln in gl.read_text(encoding="utf-8").splitlines() if ln.strip())
    import sqlite3
    con = sqlite3.connect(str(ws / "trace.db")); con.row_factory = sqlite3.Row
    rows = [dict(x) for x in con.execute(
        "SELECT * FROM dispatches WHERE matter_ref='r3-p5'").fetchall()]
    con.close()
    usage_fields = sorted({k for row in rows for k in row if "token" in k.lower() or k == "verified"})
    # from the parsed events themselves, on the shape extract_tool_texts proved — the tally
    # above stays evidence; this is the verdict's boolean.
    tool_call_seen = any(isinstance(evt.get("part"), dict) and evt["part"].get("type") == "tool"
                         for evt in r.events)
    return {"event_types": s, "tool_call_seen": tool_call_seen,
            "usage_fields_seen": usage_fields, "guard_log_lines": guard_lines,
            "trace_rows": len(rows),
            "drilldown_equivalent": bool(tool_call_seen and guard_lines and rows),
            "final_text": extract_final_text(r.events)[:400]}


PROBES["p5"] = probe_p5  # AFTER the stub loop so p5's stub is overwritten


def spawn_plugin_ts(child_ws: Path) -> str:
    """Standalone plugin (NOT the manifest shim): one tool, spawn_agent, whose execute runs
    `opencode run` in the CHILD workspace and returns the raw stream. Same proven shape as
    ironfleet-tools.ts: args:{} passthrough (z.ZodRawShape), PWD re-pinned to the child (the
    instance-resolution trap), PATH-inherited opencode.cmd via cmd.exe (the .cmd shim
    run_opencode uses). Kept as a standalone plugin so P6 measures the mechanics without
    touching the ported-tool manifest (D-T2 shape 1 feasibility, not a product surface)."""
    cw = str(child_ws).replace("\\", "/")
    return (
        'import { spawnSync } from "node:child_process"\n'
        'import { tool, type Plugin } from "@opencode-ai/plugin"\n'
        f'const CHILD_WS = "{cw}"\n'
        'export const R3Spawn: Plugin = async () => ({\n'
        '  tool: {\n'
        '    spawn_agent: tool({\n'
        '      description: "Run the child agent on a prompt and return its full reply stream.",\n'
        '      args: {},\n'
        '      async execute(args) {\n'
        '        const a = (args ?? {}) as { prompt?: string }\n'
        '        const prompt = String(a.prompt ?? "Reply with your token.").replace(/\\r?\\n/g, " ")\n'
        '        const proc = spawnSync("cmd.exe", ["/c", "opencode.cmd", "run", "--agent",\n'
        '          "r3child", "--model", "gate-local/gate/extraction", "--format", "json", prompt],\n'
        '          { cwd: CHILD_WS, env: { ...process.env, PWD: CHILD_WS },\n'
        '            timeout: 480_000, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 })\n'
        '        return (proc.stdout ?? "") + (proc.stderr ? `\\n--stderr--\\n${proc.stderr}` : "")\n'
        '      },\n'
        '    }),\n'
        '  },\n'
        '})\n'
    )


CHILD_TOKEN = "R3-CHILD-TOKEN-4K"

def probe_p6(ev: Path) -> dict:
    from scripts.stand_up_opencode import PORT, MOUNT, sync_mount
    shared_matters = WS_BASE / "matters-r3p6"
    parent = WS_BASE / "r3-p6-parent"
    child = Path.home() / "spike-ws-a2" / "r3-p6-child"   # different parent, instance seam
    proxy, env = start_stack(parent, "r3-p6-p", matters_root=shared_matters)
    sync_mount(child, MOUNT, "r3-p6-c", "LOCAL_PREFERRED", PORT, matters_root=shared_matters)
    try:
        (child / ".opencode" / "agent" / "r3child.md").write_text(
            canary_primary_md("r3child", CHILD_TOKEN), encoding="utf-8")
        (parent / ".opencode" / "plugins" / "r3-spawn.ts").write_text(
            spawn_plugin_ts(child), encoding="utf-8")
        (parent / ".opencode" / "agent" / "r3parent.md").write_text(
            canary_primary_md("r3parent", "unused", tools={"spawn_agent": True})
            .replace("You are probe canary r3parent. Whatever the user asks, reply with"
                     " exactly unused and nothing else.",
                     "You orchestrate. When asked to run the child, you MUST call the "
                     "spawn_agent tool with prompt 'Reply with your token.', then reply "
                     "with exactly the token the tool returned and nothing else."),
            encoding="utf-8")
        prompt = flatten_prompt("Run the child agent and give me its token.")
        roundtrip = 0
        sessions = 3
        for i in range(sessions):
            r = run_capture(parent, ["run", "--agent", "r3parent", "--model",
                                     "gate-local/gate/toolpath", "--format", "json", prompt],
                            label=f"p6-parent-{i}", ev=ev, env=env)
            if CHILD_TOKEN in r.raw:   # token in the PARENT stream = full round trip
                roundtrip += 1
    finally:
        proxy.stop()
    return {"sessions": sessions, "token_roundtrip": roundtrip,
            "reliability": f"{roundtrip}/{sessions}"}


PROBES["p6"] = probe_p6  # AFTER the stub loop so p6's stub is overwritten


P7_FILE_TOKEN = "R3-HANDOFF-TOKEN-2W"
P7_PROMPT_TOKEN = "R3-FOX-TOKEN-5V"
P7_INTERJECT = "R3-INTERJECT-8Z"

def probe_p7(ev: Path) -> dict:
    import re
    ws = WS_BASE / "r3-p7"
    proxy, env = start_stack(ws, "r3-p7")
    try:
        (ws / ".opencode" / "agent" / "r3s1.md").write_text(
            canary_primary_md("r3s1", "unused", tools={"write": True}), encoding="utf-8")
        (ws / ".opencode" / "agent" / "r3s2.md").write_text(
            canary_primary_md("r3s2", "unused", tools={"read": True}), encoding="utf-8")
        # stage 1: produce two artifacts — a workspace FILE and a PROMPT-carriable line
        s1 = run_capture(ws, ["run", "--agent", "r3s1", "--model", "gate-local/gate/extraction",
                              "--format", "json",
                              flatten_prompt("Do exactly two things. 1: Write this exact line — "
                                             f"{P7_FILE_TOKEN} — to the file handoff.md in the "
                                             "workspace. 2: Reply with exactly this sentence: "
                                             f"The fox carries {P7_PROMPT_TOKEN}.")],
                          label="p7-s1", ev=ev, env=env)
        sid_m = re.search(r'"sessionID"\s*:\s*"([^"]+)"', s1.raw)
        sid = sid_m.group(1) if sid_m else None
        # file carry: stage 2 reads the workspace artifact
        f = run_capture(ws, ["run", "--agent", "r3s2", "--model", "gate-local/gate/extraction",
                             "--format", "json",
                             flatten_prompt("Read the file handoff.md in this workspace and "
                                            "reply with exactly the line it contains.")],
                        label="p7-file-carry", ev=ev, env=env)
        # prompt carry: the harness hands stage 1's final text to stage 2
        carried = extract_final_text(s1.events)
        p = run_capture(ws, ["run", "--agent", "r3s2", "--model", "gate-local/gate/extraction",
                             "--format", "json",
                             flatten_prompt(f"Stage 1 reported: {carried} — reply with just "
                                            "the token the report carries.")],
                        label="p7-prompt-carry", ev=ev, env=env)
        # interjection: continue STAGE 1's session with the user's idea, then re-carry
        interjection_ok = False
        if sid:
            u = run_capture(ws, ["run", "--session", sid, "--model", "gate-local/gate/extraction",
                                 "--format", "json",
                                 flatten_prompt(f"User idea: the handoff file must also include "
                                                f"this exact token: {P7_INTERJECT}. Update it now, "
                                                "reply UPDATED.")],
                            label="p7-interject", ev=ev, env=env)
            f2 = run_capture(ws, ["run", "--agent", "r3s2", "--model", "gate-local/gate/extraction",
                                  "--format", "json",
                                  flatten_prompt("Read the file handoff.md and reply with ALL "
                                                 "tokens it contains, comma-separated.")],
                             label="p7-after-interject", ev=ev, env=env)
            interjection_ok = P7_INTERJECT in extract_final_text(f2.events)
    finally:
        proxy.stop()
    f_text = extract_final_text(f.events)
    p_text = extract_final_text(p.events)
    return {"file_carry": P7_FILE_TOKEN in f_text,
            "prompt_carry": P7_PROMPT_TOKEN in p_text,
            "interjection_session": interjection_ok,
            "session_ids": {"stage1": sid}}


PROBES["p7"] = probe_p7  # AFTER the stub loop so p7's stub is overwritten


if __name__ == "__main__":
    raise SystemExit(main())
