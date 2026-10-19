"""harness session — the non-TUI entry point to the R3 session driver (spec 17 s5.1).

The TUI (harness/session/tui.py) is the real shell, but every slice must be usable
before it is complete: this CLI drives the SAME SessionDriver the TUI drives, so
what works here works there — one code path, not two.

Usage:
  .venv/Scripts/python.exe scripts/session_cli.py --new --matter <ref> [--display ...]
  .venv/Scripts/python.exe scripts/session_cli.py --list
  .venv/Scripts/python.exe scripts/session_cli.py --resume <id|last>
  .venv/Scripts/python.exe scripts/session_cli.py --turn --agent <agent> --prompt <text> \
      [--session <id|last>] [--model gate-local/gate/extraction]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.paths import resolve_store_root          # noqa: E402
from harness.session.driver import (                  # noqa: E402
    SessionDriver, resolve_resume_target, session_cli_argv)
from harness.session.errors import read_errors, record_error   # noqa: E402
from harness.session.store import SessionStore        # noqa: E402

# The workspace base sits beside the session store, under the same store root:
# HARNESS_HOME/sessions/ (the record) and HARNESS_HOME/workspaces/ (the scratch
# sync_mount rebuilds), so one HARNESS_HOME owns both.
WORKSPACE_SUBDIR = "workspaces"


def _store_and_driver(home: Path) -> tuple[SessionStore, SessionDriver]:
    root = Path(home)
    store = SessionStore(root)
    driver = SessionDriver(store, root / WORKSPACE_SUBDIR)
    return store, driver


def _fmt_session(row: dict) -> str:
    """One line per session for --list: the fields the operator picks from."""
    sid = row["session_id"]
    matter = row.get("matter_ref") or "-"
    display = row.get("display") or "-"
    turns = row.get("turns", 0)
    updated = (row.get("updated") or "")[:19]
    return f"{sid}\t{matter}\t{display}\tturns={turns}\t{updated}"


def main_with_args(args: argparse.Namespace) -> int:
    """Run from an already-parsed namespace: src/harness/cli.py hands its own over, so
    the flags validate once and the namespace passes through untouched."""
    home, _src = resolve_store_root()
    store, driver = _store_and_driver(home)

    if args.errors:
        rows = read_errors(home)
        if not rows:
            print("(no recorded failures)")
            return 0
        for r in rows:
            print(f"{r['ts']}\t{r['where']}\t{r['exception']}: {r['message']}"
                  f"{f'  (cause: {r['cause']})' if r['cause'] else ''}")
            if r.get("line"):
                print(f"    at {r['line']}")
        return 0

    if args.list:
        rows = store.sessions()
        if not rows:
            print("(no sessions yet)")
            return 0
        print("session_id\tmatter\tdisplay\tturns\tupdated")
        for row in rows:
            print(_fmt_session(row))
        return 0

    if args.new:
        if not args.matter:
            print("--new requires --matter <ref>", file=sys.stderr)
            return 2
        sid = driver.start(args.matter, args.display)
        print(sid)
        return 0

    if args.turn:
        if not args.agent or not args.prompt:
            print("--turn requires --agent <name> and --prompt <text>", file=sys.stderr)
            return 2
        sid = resolve_resume_target(store, args.session or "last")
        meta = next(r for r in store.sessions() if r["session_id"] == sid)
        row = asyncio.run(driver.run_turn(sid, meta["matter_ref"], args.agent,
                                          args.prompt, model=args.model))
        print(f"{sid}\t{row.agent}\t{','.join(row.tools_used) or '-'}\t"
              f"{row.output_summary[:200]!r}\ttrace={row.trace_refs}")
        # A turn that produced neither text nor a tool call did not land — the row is
        # in the JSONL either way (the honest record), but the caller hears about it.
        return 0 if row.output_summary or row.tools_used else 1

    # --resume: the state a turn needs to continue (F6 — --continue is dead on 1.18.25;
    # the store owns last-session mapping and the caller drives --session <id>).
    try:
        sid = resolve_resume_target(store, args.resume)
    except ValueError as exc:
        print(f"session: {exc}", file=sys.stderr)
        return 2
    state = driver.resume(sid)
    print(f"session:   {state['session_id']}")
    print(f"matter:    {state['matter_ref']}")
    print(f"display:   {state['display'] or '-'}")
    print(f"turns:     {state['turns']}")
    print(f"continue:  {state.get('opencode_session') or '(none — a fresh turn starts one)'}")
    print(f"last said: {state['last_summary'][:400] or '-'}")
    return 0


def _dispatch(argv: list[str], home: Path) -> int:
    """Parse argv and run. Split from main() so every failure below can be recorded
    by the caller (a CLI that dies with only a traceback is locatable; one that
    dies silently is not)."""
    ap = argparse.ArgumentParser(prog="harness session", description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--new", action="store_true", help="start a new session")
    mode.add_argument("--list", action="store_true", help="list sessions (newest first)")
    mode.add_argument("--resume", metavar="ID", help="resume <id|last> and print its state")
    mode.add_argument("--turn", action="store_true", help="run one agent turn")
    # The error log is written to be READ — without this flag a recorded failure is
    # findable only with a text editor.
    mode.add_argument("--errors", action="store_true",
                      help="print the recorded error log (where/why/which line)")
    ap.add_argument("--matter", default=None, help="matter ref (with --new)")
    ap.add_argument("--display", default="", help="human label (with --new)")
    ap.add_argument("--session", metavar="ID", default=None,
                    help="session id for --turn/--resume (default: last)")
    ap.add_argument("--agent", default=None, help="agent/persona name (with --turn)")
    ap.add_argument("--prompt", default=None, help="the turn prompt (required with --turn)")
    ap.add_argument("--model", default="gate-local/gate/extraction",
                    help="routing model for the turn")
    return main_with_args(ap.parse_args(argv))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Validate before any side effect (F9): a colon in a matter/session id is a
    # Windows registry-dir name waiting to happen, so it fails at the CLI — as a
    # clean message, not a traceback (the operator typed it, it is not a bug).
    try:
        argv = session_cli_argv(argv)
    except ValueError as exc:
        print(f"session: {exc}", file=sys.stderr)
        return 2

    home, _src = resolve_store_root()
    try:
        return _dispatch(argv, home)
    except SystemExit:
        raise                      # argparse's own exit codes pass through
    except Exception as exc:                              # noqa: BLE001
        record_error(exc, where="scripts.session_cli.main", root=home)
        print(f"session: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
