"""The production launcher — the entry point pack_macos.sh's PyInstaller step compiles
(S7g-M) and the Windows shell runs the same way.

Binds the multi-matter egress proxy on 127.0.0.1:7373 against the privileged store
resolved by harness.paths.resolve_store_root() — this module is that resolver's first
core consumer, the live call site its docstring defers to "that later step".

The routing YAML is repo data, not package data: pass --routing (or IRONFLEET_ROUTING).
With neither, fail loud naming both rather than resolving a CWD-relative default — the
PWD-steering hazard the spike recorded twice.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from harness.bootstrap import build_scheduler
from harness.egress_proxy import EgressProxy

HOST, PORT = "127.0.0.1", 7373


def main(argv: list[str] | None = None) -> int:
    from harness.bootstrap import build_gate
    from harness.paths import resolve_store_root

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--routing", default=os.environ.get("IRONFLEET_ROUTING"),
                    help="routing YAML (default: $IRONFLEET_ROUTING)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--trace-db", default=None,
                    help="trace store path (default: <store-root>/trace.db)")
    args = ap.parse_args(argv)
    if not args.routing:
        ap.error("--routing or IRONFLEET_ROUTING is required — the routing YAML is repo "
                 "data, not package data, and a CWD-relative default would silently "
                 "depend on where the launcher was started")

    root, source = resolve_store_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "matters").mkdir(exist_ok=True)
    print(f"[launcher] store {root} (source: {source})", file=sys.stderr)

    trace_db = Path(args.trace_db) if args.trace_db else root / "trace.db"
    try:  # M11 T4: any startup/serve crash leaves a local log under <root>/crash/
        gate, rt, aliases = build_gate(trace_db, Path(args.routing))
        scheduler = build_scheduler()
        # ThreadingHTTPServer binds in its CONSTRUCTOR (stand_up_opencode.py precedent):
        # start() only spawns the serve_forever thread and cannot raise OSError, so the
        # collision guard must wrap construction — a bind failure aborts here rather than
        # letting a mount's baseURL point at whatever else is listening on the port.
        try:
            proxy = EgressProxy(HOST, args.port, gate, rt, aliases, root / "matters",
                                scheduler=scheduler)
        except OSError as ex:
            print(f"[launcher] cannot bind {HOST}:{args.port} — refusing to start: {ex}",
                  file=sys.stderr)
            return 2
        proxy.start()
        print(f"[launcher] proxy on http://{HOST}:{args.port}/v1, models: "
              f"{sorted(aliases)}", file=sys.stderr)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            proxy.stop()
        return 0
    except Exception:
        from harness.crashlog import capture
        capture(root, "launcher", source=source)  # never a network send — 02 §15
        raise


if __name__ == "__main__":
    raise SystemExit(main())
