# src/harness/session/workspace.py
"""Per-agent workspace isolation (finding F4) and the supervised spawn helper
(F8 watchdog, F9 colon-free).

Why this module exists: P4's first live run lost a leg to opencode's own
"database is locked" — two concurrent `opencode run` processes writing ONE
session store. The factory must therefore give every agent its own workspace
AND its own opencode data root; when the runtime offers no override, writes
serialize (see the shortcut below).

Nothing here re-invents the proven primitives: sync_mount, child_env, run_opencode
and flatten_prompt come from harness.substrate (the installed package — no repo
root goes on sys.path anymore, M3).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# The spawn timeout: the S7j-W watchdog budget. opencode hangs after init ~2 in 7
# on this box (load-sensitive), so every spawn gets one retry, never a loop.
DEFAULT_TIMEOUT_S = 480


def _require_colon_free(value: str, what: str) -> None:
    if ":" in value:
        raise ValueError(f"{what} must be colon-free (Windows registry directory"
                         f" names): {value!r}")


def agent_workspace(base: Path, session_id: str, agent: str,
                    matter_ref: str | None = None) -> Path:
    """This agent's own workspace under the session base. Each agent gets a
    distinct directory — two agents never share a tree, and opencode's
    instance-grouping seam (sibling repos under one parent) can't merge them
    because each workspace is its own git repo by construction (sync_mount)."""
    _require_colon_free(session_id, "session id")
    _require_colon_free(agent, "agent name")
    if matter_ref is not None:
        _require_colon_free(matter_ref, "matter ref")
        # Confidentiality: sibling workspaces feed this one (the factory's from-*
        # forward), so a session dir that already holds another matter's workspace
        # is refused outright — never reused, never silently adopted (2026-11-16:
        # the shared "api-admin" dir leaked one matter's case theory into another).
        for rec in (Path(base) / session_id).glob("*/matter.json"):
            try:
                other = json.loads(rec.read_text(encoding="utf-8")).get("matter_ref")
            except (ValueError, OSError):
                other = None
            if other != matter_ref:
                raise PermissionError(
                    f"workspace {rec.parent} belongs to matter {other!r}, not"
                    f" {matter_ref!r}: refusing to share session {session_id!r}"
                    " across matters")
    ws = Path(base) / session_id / agent
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def opencode_data_dir(base: Path, session_id: str, agent: str) -> Path:
    """The per-agent opencode data root (finding F4). opencode 1.18.25 resolves
    its data dir from the environment; we keep it per-agent so concurrent
    sessions never contend on one session DB."""
    _require_colon_free(session_id, "session id")
    _require_colon_free(agent, "agent name")
    dd = Path(base) / session_id / agent / ".opencode-data"
    dd.mkdir(parents=True, exist_ok=True)
    return dd


def spawn_env(ws: Path, extra: dict | None = None) -> dict:
    """The child env: the bearer scrub (S7b finding S1 — a dirty env lights up
    opencode's builtin providers; 275 foreign models observed live where a
    scrubbed env resolves 9) plus the precheck §5 hardening, with PWD re-pinned
    to the workspace. Copy-on-write: builds a new dict, never assigns into
    os.environ, so scrubbing cannot leak into the parent process."""
    from harness.substrate.mount import child_env
    env = child_env(ws)
    if extra:
        env.update(extra)
    return env


def _parse_session_id(events: list[dict]) -> str:
    """The opencode session id from the event stream — the handle /resume needs
    (P3: only --session <id> resumes; --continue is dead on 1.18.25)."""
    for ev in events:
        if isinstance(ev, dict) and ev.get("sessionID"):
            return str(ev["sessionID"])
    return ""


def sync_agent_workspace(ws: Path, matter_ref: str, classification: str = "LOCAL_PREFERRED") -> None:
    """sync_mount into an already-created workspace. Imported lazily so the module
    stays importable in a frozen distribution."""
    from harness.substrate.mount import MOUNT, PORT, sync_mount
    # The matter record goes to <store>/matters — the directory the proxy serves
    # (launcher shape, A-5). ws is <store>/workspaces/<sid>/<agent>, so the store
    # root is three levels up; the proxy refuses the dispatch otherwise
    # ("matter record unavailable" — the 2026-10-20 live run's root cause).
    sync_mount(ws, MOUNT, matter_ref, classification, PORT,
               matters_root=ws.parents[2] / "matters")


def turn_argv(agent: str, model: str, prompt: str,
              continue_session: str | None = None) -> list[str]:
    """One turn's argv — pure so the F6 consuming end is testable: a resume turn
    drives `--session <id>` (P3: only --session continues on 1.18.25)."""
    from harness.substrate.run import flatten_prompt
    argv = ["run", "--agent", agent, "--model", model, "--format", "json"]
    if continue_session:
        argv += ["--session", continue_session]
    argv.append(flatten_prompt(prompt))
    return argv


def spawn_session(ws: Path, agent: str, prompt: str, *, timeout: int = DEFAULT_TIMEOUT_S,
                  env: dict | None = None, model: str = "gate-local/gate/extraction",
                  continue_session: str | None = None, on_line=None
                  ) -> tuple[int, list[dict], str]:
    """One supervised opencode turn in this agent's workspace.

    Returns (code, events, session_id). Reuses the proven primitives rather
    than reinventing them: run_opencode (PWD-pinned, tree-killed on timeout,
    watchdog budget) and flatten_prompt (cmd.exe ends a command line at the
    first embedded newline). Watchdog+retry on the startup-hang signature:
    code 124 with nothing parsed — one retry, never a loop.

    The live spawn path is exercised by the acceptance drivers, never by the
    suite (house rule: live probes never run in tests)."""
    from harness.substrate.run import parse_events, run_opencode
    argv = turn_argv(agent, model, prompt, continue_session)
    code, raw = run_opencode(ws, argv, timeout=timeout, env=env, on_line=on_line)
    events = parse_events(raw)
    if code == 124 and not events:
        # the known startup hang (~2 in 7 on this box) — retry once, then report
        code, raw = run_opencode(ws, argv, timeout=timeout, env=env, on_line=on_line)
        events = parse_events(raw)
    return code, events, _parse_session_id(events)


def git_snapshot_paths(ws: Path) -> list[str]:
    """Files this workspace's git tree tracks — the doc pane's live view is a
    file-tree + git diff watcher on exactly this."""
    r = subprocess.run(["git", "ls-files"], cwd=str(ws), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()] if r.returncode == 0 else []
