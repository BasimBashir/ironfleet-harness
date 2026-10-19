# src/harness/session/workspace.py
"""Per-agent workspace isolation (finding F4) and the supervised spawn helper
(F8 watchdog, F9 colon-free).

Why this module exists: P4's first live run lost a leg to opencode's own
"database is locked" — two concurrent `opencode run` processes writing ONE
session store. The factory must therefore give every agent its own workspace
AND its own opencode data root; when the runtime offers no override, writes
serialize (see the shortcut below).

Nothing here re-invents the proven primitives: sync_mount, child_env, run_opencode
and flatten_prompt are imported from scripts/ (the namespace package — the repo
root goes on sys.path exactly as the other drivers do it).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]        # harness-core/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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
    from scripts.stand_up_opencode import child_env
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
    stays importable in a frozen distribution (scripts/ is a namespace package)."""
    from scripts.stand_up_opencode import MOUNT, PORT, sync_mount
    sync_mount(ws, MOUNT, matter_ref, classification, PORT,
               matters_root=ws.parent.parent / "matters")


def spawn_session(ws: Path, agent: str, prompt: str, *, timeout: int = DEFAULT_TIMEOUT_S,
                  env: dict | None = None, model: str = "gate-local/gate/extraction"
                  ) -> tuple[int, list[dict], str]:
    """One supervised opencode turn in this agent's workspace.

    Returns (code, events, session_id). Reuses the proven primitives rather
    than reinventing them: run_opencode (PWD-pinned, tree-killed on timeout,
    watchdog budget) and flatten_prompt (cmd.exe ends a command line at the
    first embedded newline). Watchdog+retry on the startup-hang signature:
    code 124 with nothing parsed — one retry, never a loop.

    The live spawn path is exercised by the acceptance drivers, never by the
    suite (house rule: live probes never run in tests)."""
    from scripts.run_spike_opencode import extract_final_text, flatten_prompt, parse_events, run_opencode
    argv = ["run", "--agent", agent, "--model", model, "--format", "json",
            flatten_prompt(prompt)]
    code, raw = run_opencode(ws, argv, timeout=timeout, env=env)
    events = parse_events(raw)
    if code == 124 and not events:
        # the known startup hang (~2 in 7 on this box) — retry once, then report
        code, raw = run_opencode(ws, argv, timeout=timeout, env=env)
        events = parse_events(raw)
    return code, events, _parse_session_id(events)


def git_snapshot_paths(ws: Path) -> list[str]:
    """Files this workspace's git tree tracks — the doc pane's live view is a
    file-tree + git diff watcher on exactly this."""
    r = subprocess.run(["git", "ls-files"], cwd=str(ws), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()] if r.returncode == 0 else []
