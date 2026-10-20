# src/harness/module_e/spawn_tool.py
"""The spawn_agent tool body (spec 17 §5.7, plan Task 8) — the factory's
delegation seam for agent-os mode (D-T2 shape 1, P6-proven mechanics).

Called through the standard dispatch path (the TS shim spawns
`python -m harness.module_e.dispatch`, which imports this module's `spawn_agent`
and hands it the model's args JSON), so the tool's behaviour stays in Python
where pytest reaches it — the mount's constitutional rule, not a preference.

The parent's workspace IS the coordinate system: the dispatch subprocess runs
with cwd = the parent agent's workspace (`<session base>/<session>/<agent>`),
so the child workspace is the sibling `<...>/<child-agent>` and the matter
identity rides the parent's matter.json (sync_mount writes it). The spawn
itself reuses workspace.spawn_session — the supervised, watchdog+retry,
scrubbed-env primitive the driver uses; nothing here reinvents it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]        # harness-core/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def spawn_agent(args: dict) -> dict:
    """One child-agent turn in its own workspace; returns its final reply.

    Failure contract = dispatch's: any problem raises, and the traceback reaches
    the MODEL as the tool result — a mis-delegated spawn must be visible to the
    agent that made it, not swallowed into an empty string."""
    agent = str(args.get("agent") or "").strip()
    prompt = str(args.get("prompt") or "").strip()
    if not agent or not prompt:
        raise KeyError("spawn_agent needs non-empty 'agent' and 'prompt'"
                       " (the manifest schema declares both)")
    if ":" in agent:
        raise ValueError(f"agent name must be colon-free (Windows registry"
                         f" directory names): {agent!r}")
    parent = Path.cwd()
    matter_ref, classification = _matter_of(parent)
    child = _child_workspace(parent, agent)
    from scripts.stand_up_opencode import MOUNT, PORT, child_env, sync_mount
    sync_mount(child, MOUNT, matter_ref, classification, PORT,
               matters_root=child.parent.parent / "matters")
    agent_dir = child / ".opencode" / "agent"
    # S7i: the drivable carriers are the plain persona file and the canon-carrying
    # `<name>-memory.md` primary (subagent-mode files fall back to the default
    # agent on the pinned binaries — drive the primaries, never raw subagents).
    stem = next((c[:-3] for c in (f"{agent}.md", f"{agent}-memory.md")
                 if (agent_dir / c).is_file()), None)
    if stem is None:
        raise RuntimeError(f"spawn_agent: no drivable agent file for {agent!r}"
                           f" in {child} (looked for {agent}.md, {agent}-memory.md)")
    from harness.session.workspace import spawn_session
    code, events, sid = spawn_session(child, stem, prompt, env=child_env(child))
    from scripts.run_spike_opencode import extract_final_text
    return {"agent": agent, "workspace": str(child), "session_id": sid,
            "exit_code": code, "final_text": extract_final_text(events)}


def _child_workspace(parent_ws: Path, agent: str) -> Path:
    """The child's workspace: a sibling of the parent's under the same session."""
    return parent_ws.parent / agent


def _matter_of(ws: Path) -> tuple[str, str]:
    """(matter_ref, classification) from the workspace's matter.json — a workspace
    without one is not a synced matter workspace, which is a loud error: spawning
    a child into an unidentified matter would break the gate's per-matter provenance."""
    f = ws / "matter.json"
    if not f.is_file():
        raise RuntimeError(f"spawn_agent: {ws} is not a synced matter workspace"
                           f" (no matter.json; cwd must be the parent agent's workspace)")
    d = json.loads(f.read_text(encoding="utf-8"))
    return str(d["matter_ref"]), str(d.get("classification", "LOCAL_PREFERRED"))
