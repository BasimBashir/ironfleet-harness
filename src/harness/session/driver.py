# src/harness/session/driver.py
"""The session driver: the non-TUI path that owns a session (spec 17 s5.1).

Slice 2's job is to prove the whole ride-the-substrate path in OUR code: start a
session, run ONE agent turn through the proven stack (mount sync, scrubbed spawn,
the gate), and land a TurnRow in the JSONL — before the factory exists to orchestrate
stages.

Nothing here re-invents the substrate: sync_mount + the S7f live-stack builders are
imported, the spawn goes through workspace.spawn_session (which already carries the
watchdog/scrub), and every model call lands in the gate's trace with this session's
identity (finding F1's columns).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]        # harness-core/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.session.errors import record_error
from harness.session.store import SessionStore, TurnRow
from harness.session.workspace import (
    agent_workspace,
    sync_agent_workspace,
    spawn_env,
    spawn_session,
)

# The gateway the mount's baseURL points at. Every spawn goes through it; a driver
# that forgets to open it turns every turn into a connection-refused with no trace
# row (the 2026-10-20 acceptance run found exactly that).
PROXY_HOST, PROXY_PORT = "127.0.0.1", 7373


class SessionDriver:
    """Owns one session: its store row, its workspace, and its turns.

    The store and the workspace are separate on purpose — the JSONL is the durable
    record and the workspace is scratch that sync_mount rebuilds.
    `open_gate()` is the lifecycle seam the shell/driver owns: the trace lands at
    <store-root>/trace.db (the same place `harness serve` reads) and the port is
    released when the session ends."""

    def __init__(self, store: SessionStore, base: Path) -> None:
        from contextlib import contextmanager
        self.store = store
        self.base = Path(base)
        self.store_root = self.store.root
        self._contextmanager = contextmanager
        self._gate = None                     # the live proxy while a session runs
        self._open_gate_calls = 0             # how many times the lifecycle opened

    @property
    def trace_db(self) -> Path:
        """Where this session's dispatch rows land — the gate's own trace store."""
        return self.store.root / "trace.db"

    def open_gate(self):
        """Context manager: bind the egress proxy + scheduler for the session.
        Lazy imports so the module stays importable without the stack; the second
        concurrent open fails loud on the exclusive bind (the launcher's lesson).
        The routing YAML is repo data (cli.default_routing) — resolved from the
        file's own path like `harness serve` does, never from the CWD."""
        from harness.bootstrap import build_gate, build_scheduler
        from harness.cli import default_routing
        from harness.egress_proxy import EgressProxy

        @self._contextmanager
        def _open():
            gate, rt, aliases = build_gate(self.trace_db, default_routing())
            proxy = EgressProxy(PROXY_HOST, PROXY_PORT, gate, rt, aliases,
                                self.store.root / "matters",
                                scheduler=build_scheduler())
            proxy.start()
            self._gate = proxy
            self._open_gate_calls += 1
            try:
                yield proxy
            finally:
                proxy.stop()
                self._gate = None
        return _open()

    # -- the live path (acceptance-only, never in the suite) -------------------

    def start(self, matter_ref: str, display: str = "") -> str:
        """A new session, colon-free validated by the store itself."""
        return self.store.new_session(matter_ref, display)

    def workspace_for(self, session_id: str, agent: str, matter_ref: str,
                      classification: str = "LOCAL_PREFERRED") -> Path:
        """This agent's synced workspace (created + mount-refreshed on demand)."""
        ws = agent_workspace(self.base, session_id, agent, matter_ref)
        sync_agent_workspace(ws, matter_ref, classification)
        return ws

    async def run_turn(self, session_id: str, matter_ref: str, agent: str,
                       prompt: str, *, classification: str = "LOCAL_PREFERRED",
                       model: str = "gate-local/gate/extraction",
                       continue_session: str | None = None) -> TurnRow:
        """ONE agent turn through the proven stack, recorded in the JSONL.

        The spawn is supervised (watchdog + one retry on the startup hang), the env
        is the scrubbed child_env, and the trace rows this turn produced are read
        back from the session trace store (one db at the store root) so the row's
        trace_refs are real. The before/after id diff assumes no concurrent
        dispatch mid-turn — the shell runs turns sequentially.
        `continue_session` is F6's consuming end: the stored opencode session id
        drives `--session` (P3), so a resumed turn inherits its context.

        Failure policy (the user's ruling): a turn that could not run is a RECORDED
        event, not a crash — the row lands with whatever was produced (possibly
        nothing) and the cause goes to the error log, because a shell that dies on
        a dead spawn takes the whole session with it."""
        from asyncio import to_thread
        from datetime import datetime, timezone

        ws = self.workspace_for(session_id, agent, matter_ref, classification)
        env = spawn_env(ws)
        before = _trace_ids(self.trace_db)
        try:
            # to_thread: the spawn is a BLOCKING subprocess ride (watchdog, tree-kill)
            # — awaited inline it froze the TUI's event loop for the whole turn
            # (the 2026-10-20 live session's "shell dead while a stage runs").
            code, events, sid = await to_thread(
                spawn_session, ws, agent, prompt, env=env, model=model,
                continue_session=continue_session)
        except Exception as exc:                                  # noqa: BLE001
            # The spawn itself blew up (binary missing, mount unwritable, ...):
            # record where/why and land an honest row so the turn is not lost.
            record_error(exc, where="session.driver.run_turn.spawn", root=self.store.root,
                         context={"session_id": session_id, "agent": agent,
                                  "model": model, "workspace": str(ws)})
            events, code, sid = [], EXIT_NO_OUTPUT, ""
        if sid:
            # F6: the resume handle — /resume drives `--session <id>` (P3-proven),
            # so the id the spawn opened must outlive the turn.
            self.store.set_opencode_session(session_id, sid)
        after = _trace_ids(self.trace_db)
        new = sorted(after - before)
        if new:
            # Attribute the span to THIS agent + session — the meter's per-agent
            # ledger reads these columns, and the gate was never told who asked.
            from harness.trace import TraceStore
            TraceStore(self.trace_db).attr(agent, session_id, new)
        row = build_turn_row(session_id=session_id, matter_ref=matter_ref, agent=agent,
                             events=events, trace_refs=new,
                             ts=datetime.now(timezone.utc).isoformat())
        self.store.append_turn(row)
        return row

    def resume(self, session_id: str) -> dict:
        """What /resume needs: the matter, the display, the latest summary, and the
        turns so far (the caller re-opens the last opencode session by id).

        A session with no turns is legal — it was just created, and resuming it
        starts its first turn — so an empty row set is a zero-turn state, not an
        unknown session (the caller already validated existence)."""
        rows = self.store.turns(session_id)
        meta = next((r for r in self.store.sessions()
                     if r["session_id"] == session_id), None)
        if meta is None and not rows:
            raise ValueError(f"unknown session: {session_id!r}")
        last = rows[-1] if rows else None
        return {"session_id": session_id,
                "matter_ref": meta.get("matter_ref") if meta else last.matter_ref,
                "display": (meta or {}).get("display") or (last.display if last else ""),
                "opencode_session": (meta or {}).get("opencode_session") or "",
                "turns": len(rows),
                "last_summary": last.output_summary if last else ""}


# A spawn that produced no text and no tool call did not answer. This box hangs
# after init ~2 in 7 (F8), so it is a known signature, not an emergency — but it
# is still recorded and still fails the turn's exit code.
EXIT_NO_OUTPUT = 3


# -- pure assembly (tested without any spawn) ---------------------------------


def build_turn_row(*, session_id: str, matter_ref: str, agent: str,
                   events: list[dict], trace_refs: list[int], ts: str) -> TurnRow:
    """One completed turn, from the event stream.

    The row shape is what the acceptance checks read by name, so it is derived from
    the events exactly once, here: tools_used is the tool calls in order (the
    proven stream carries them at the part level), and output_summary is the LAST
    text part (stream order — the final assistant answer, per extract_final_text's
    documented rule)."""
    tools: list[str] = []
    final_text = ""
    thinking_parts: list[str] = []
    for ev in events:
        part = ev.get("part") if isinstance(ev, dict) else None
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind == "tool" and part.get("tool"):
            name = str(part["tool"])
            if name not in tools:
                tools.append(name)
        elif kind == "text" and isinstance(part.get("text"), str):
            final_text = part["text"]
        elif kind == "reasoning" and isinstance(part.get("text"), str):
            thinking_parts.append(part["text"])
    # The Thinking pane's raw material — capped so a reasoning-heavy turn cannot
    # bloat the JSONL (the stream itself is the full record while it lives).
    thinking = "\n".join(thinking_parts)[:8000]
    return TurnRow(ts=ts, session_id=session_id, matter_ref=matter_ref, display="",
                   agent=agent, tools_used=tools,
                   output_summary=final_text[:2000], docs_touched=[], trace_refs=trace_refs,
                   thinking=thinking)


def resolve_resume_target(store: SessionStore, target: str) -> str:
    """/resume <id|last> — OUR mapping. P3 proved --continue/-c are dead on 1.18.25,
    so the shell owns last-session resolution instead of asking opencode for it."""
    if ":" in target:
        raise ValueError(f"session id must be colon-free (Windows registry dir names): {target!r}")
    if target == "last":
        sid = store.last()
        if sid is None:
            raise ValueError("no session to resume — the store is empty")
        return sid
    if not any(r["session_id"] == target for r in store.sessions()):
        raise ValueError(f"unknown session: {target!r} (try `session --list`)")
    return target


def session_cli_argv(argv: list[str]) -> list[str]:
    """Validate + normalise the CLI argv for the session subcommand. The colon-free
    rule is enforced here (the registry directory names forbid ':'), so a bad id
    fails at the CLI, not deep inside a spawn."""
    if "--matter" in argv:
        i = argv.index("--matter")
        matter = argv[i + 1] if i + 1 < len(argv) else ""
        if ":" in matter:
            raise ValueError(f"matter ref must be colon-free: {matter!r}")
    if "--resume" in argv:
        i = argv.index("--resume")
        target = argv[i + 1] if i + 1 < len(argv) else ""
        if ":" in target and target != "last":
            raise ValueError(f"session id must be colon-free: {target!r}")
    return list(argv)


def _trace_ids(db_path: Path) -> set[int]:
    """The dispatch ids the session trace store already holds — the before/after
    span this turn produced. A missing db is an empty set (a first turn, or a
    store that never dispatched)."""
    if not db_path.is_file():
        return set()
    import sqlite3
    con = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in con.execute("SELECT id FROM dispatches").fetchall()}
    except sqlite3.Error:
        return set()
    finally:
        con.close()
