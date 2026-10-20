"""The IronFleet shell — the TUI entry point (spec 17 s5, plan Task 15 handoff).

Wires what the acceptance driver wires, for a human at the keyboard: the store,
the gate lifecycle for the app's lifetime (open_gate — without it every turn
dies connection-refused), the mode->runner factory (D-T2: shift+TAB rebuilds
the runner), the trace store for the meter/agents panes, and the doc pane's
watched workspace (hunter-drive — the workhorse persona; the pane watches one
workspace, not every stage's).

Usage:
  .venv/Scripts/python.exe scripts/tui.py --new --matter <ref>
  .venv/Scripts/python.exe scripts/tui.py --session <id|last>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.paths import resolve_store_root          # noqa: E402
from harness.session.driver import (                  # noqa: E402
    SessionDriver, resolve_resume_target)
from harness.session.factory import FactoryRunner     # noqa: E402
from harness.session.store import SessionStore        # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new", action="store_true", help="start a new session")
    ap.add_argument("--matter", default=None, help="matter ref (with --new)")
    ap.add_argument("--session", default="last", help="session id or 'last'")
    args = ap.parse_args(argv)

    home, _src = resolve_store_root()
    store = SessionStore(Path(home))
    driver = SessionDriver(store, Path(home) / "workspaces")

    if args.new:
        if not args.matter:
            ap.error("--new requires --matter <ref>")
        sid = driver.start(args.matter, "TUI")
    else:
        sid = resolve_resume_target(store, args.session)
    matter = driver.resume(sid)["matter_ref"]

    from harness.session.tui import IronFleetApp
    from harness.trace import TraceStore

    def make_runner(mode: str) -> FactoryRunner:
        return FactoryRunner(driver, store=store, mode=mode)

    app = IronFleetApp(store, runner=make_runner("shell-drives"),
                       mode="shell-drives", session_id=sid,
                       runner_factory=make_runner,
                       trace=TraceStore(store.root / "trace.db"),
                       provider_name="nvidia-nim",
                       base=Path(home) / "workspaces",
                       docs_ws=driver.workspace_for(sid, "hunter-drive", matter))
    with driver.open_gate():
        app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
