"""OpenCode run primitives — the production subset of the old scripts/run_spike_opencode.py.

Moved verbatim (M3 substrate relocation): the spike script itself stays in scripts/ because
it importlib-loads two sibling scripts by file path (run_eval_ollama.py,
run_eval_persona_ollama.py) and therefore cannot live in the package; its eval/parity mains
import these back.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

RUN_TIMEOUT_S = 5400          # 90 min ceiling per case (parity cap 8192 tok @ ~4.3 tok/s + overhead)


def opencode_cmd() -> list[str]:
    exe = shutil.which("opencode")
    if not exe:
        raise SystemExit("FAIL: opencode not on PATH — npm i -g opencode-ai@1.18.25")
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", exe]
    return [exe]


def _drain(pipe, sink: list[str], on_line=None) -> None:
    """Reader-thread body. Line by line so each opencode JSON event reaches `on_line`
    (the live log) as it is printed; a failing callback never stops the drain."""
    for line in pipe:
        sink.append(line)
        if on_line is not None:
            try:
                on_line(line)
            except Exception:                             # noqa: BLE001
                pass


def run_opencode(ws: Path, args: list[str], timeout: int = RUN_TIMEOUT_S,
                 env: dict[str, str] | None = None, on_line=None) -> tuple[int, str]:
    """Run opencode in the workspace; return (exit code, combined stdout+stderr text).
    PWD must be scrubbed: opencode reads the env's PWD for project/instance resolution and
    an inherited PWD pointing elsewhere (e.g. harness-core) steers the session into THAT
    repo's instance — observed live 2026-09-01 (ProviderModelNotFound despite cwd=ws).
    Timeout uses a TREE kill: killing only the direct child (cmd.exe) leaves opencode.exe
    holding the stdout pipe, and communicate() then blocks forever despite the timeout —
    observed live 2026-09-01 (driver hung >1 h on a dead case).

    `env` is the seam the bearer-key scrub hangs on (S7b review finding S1): without it the
    child inherits the FULL parent env, and any provider key on the machine (ANTHROPIC_API_KEY,
    OPENAI_API_KEY, the AWS pair, …) activates opencode's builtin providers and makes them
    selectable — verified live 2026-10-01 (275 models resolved where a scrubbed env resolves
    9). None (the default, and every spike-driver call) keeps the historical behaviour of
    building the child env from os.environ. A caller-supplied env is used verbatim for
    everything EXCEPT PWD, which is always re-pinned to `ws`: the process runs with cwd=ws,
    and a stale PWD is the wrong-instance failure above, so this seam never reintroduces it.

    Deadlock law (2026-10-21 live freeze, root-caused): the pipes are drained by READER
    threads, never by communicate(). opencode's grandchild (node.exe, e.g. the tools
    shim's dispatch spawns) can survive its parent's tree-kill and keep the pipe's write
    end open; communicate() then blocks on read() FOREVER — the timeout means nothing and
    the whole runner thread wedges (the session's remaining stages never start). Reading
    on threads makes the timeout authoritative: kill the tree, join the readers with a
    bounded wait, return 124 whatever the grandchild does."""
    import os
    import threading
    if env is None:
        env = {**os.environ, "PWD": str(ws)}
    else:
        env = {**env, "PWD": str(ws)}
    proc = subprocess.Popen(opencode_cmd() + args, cwd=str(ws),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", env=env)
    chunks: dict[str, list[str]] = {"out": [], "err": []}
    readers = [threading.Thread(target=_drain, args=(proc.stdout, chunks["out"], on_line),
                                daemon=True),
               threading.Thread(target=_drain, args=(proc.stderr, chunks["err"]), daemon=True)]
    for th in readers:
        th.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass                                  # the grandchild may outlive the tree
    for th in readers:                            # bounded: a dead pipe closes now
        th.join(5)
    out, err = "".join(chunks["out"]), "".join(chunks["err"])
    # Explicit closes: an inherited pipe handle keeps the parent's FDs alive.
    for pipe in (proc.stdout, proc.stderr):
        try:
            pipe.close()
        except OSError:
            pass
    if proc.returncode == 124 or (proc.returncode is None):
        # returncode None: the process is still running after the bounded wait —
        # the spawn KILLED its turn; report the watchdog's code, never a crash.
        return 124, (out or "") + f"\n--timeout: tree-killed after {timeout}s--\n"
    return proc.returncode, (out or "") + ("\n--stderr--\n" + (err or "") if err else "")


def flatten_prompt(prompt: str) -> str:
    """cmd.exe ends the command line at the first embedded newline — a multi-line prompt
    passed as one argv element arrives TRUNCATED (observed live 2026-09-01: hunter answered
    'Your message looks cut off'). Flatten newlines to single spaces; the persona cases'
    prompts are plain prose so meaning is unchanged, and scorer needles live in OUTPUTS."""
    return " ".join(line.strip() for line in prompt.splitlines() if line.strip())


def parse_events(raw: str) -> list[dict]:
    events = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def extract_final_text(events: list[dict]) -> str:
    """Final assistant text. Two observed event shapes are handled:
    1. run-mode flat parts: {"type": "text", "part": {"messageID", "text"}} — the final
       answer is the concat of text parts of the LAST messageID seen (stream order).
    2. server/SDK snapshots: message.updated {properties: {info: {role}, parts: [...]}} —
       last assistant snapshot wins; reasoning parts excluded."""
    flat: dict[str, list[str]] = {}
    last_mid = ""
    for ev in events:
        part = ev.get("part")
        if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
            mid = part.get("messageID", "")
            flat.setdefault(mid, []).append(part["text"])
            last_mid = mid
    if last_mid:
        return "".join(flat[last_mid])
    snapshots: list[dict] = []
    for ev in events:
        if ev.get("type") != "message.updated":
            continue
        props = ev.get("properties") or {}
        info = props.get("info") or {}
        if info.get("role") != "assistant":
            continue
        snapshots.append(props)
    if not snapshots:
        return ""
    last = snapshots[-1]
    texts = [p.get("text", "") for p in last.get("parts", []) if p.get("type") == "text"]
    return "".join(texts)


def extract_tool_texts(events: list[dict]) -> list[str]:
    """Every tool-result text seen in run-mode events. Observed shape: tool parts carry
    state.output (opencode-internal JSON envelope for built-in tools) and/or top-level
    output/text/content; all are collected — the inject verifier scans them for the
    annotation marker wherever it lands."""
    out = []
    for ev in events:
        part = ev.get("part")
        if isinstance(part, dict) and part.get("type") == "tool":
            state = part.get("state") or {}
            if isinstance(state.get("output"), str):
                out.append(state["output"])
            for key in ("output", "text", "content"):
                if isinstance(part.get(key), str):
                    out.append(part[key])
                    break
    return out
