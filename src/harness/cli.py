"""The user-facing entry point (S7j-W step 2): version, serve, drive.

The distribution tree IS the repo tree (editable install), so the packaged data
resolves from this file's own path — the launcher keeps its no-CWD-default rule;
this module is the layer that knows where the packaged data lives and hands it over
explicitly.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import harness


def default_routing() -> Path:
    """The packaged routing YAML. FileNotFoundError here means a non-editable install
    stranded the data — reinstall editable, per the install script."""
    p = Path(__file__).resolve().parents[2] / "data" / "routing-a1.yaml"
    if not p.is_file():
        raise FileNotFoundError(
            f"packaged routing not found at {p} — the distribution tree ships data/ at "
            f"its repo paths; install editable (pip install -e .) per the install script")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harness", description=__doc__)
    ap.add_argument("--version", action="version", version=f"harness {harness.__version__}")
    sub = ap.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="stand up the egress proxy against the privileged store")
    serve.add_argument("--routing", default=None, help="routing YAML (default: the packaged one)")
    serve.add_argument("--port", type=int, default=7373)
    drive = sub.add_parser("drive", help="one live opencode session through the gate (smoke)")
    drive.add_argument("--matter-ref", required=True)
    drive.add_argument("--task-class", default="extraction")
    drive.add_argument("--workspace", default=None)
    drive.add_argument("--prompt", default=None)
    drive.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from harness.ops.ironfleet_launcher import main as serve_main
        routing = args.routing or os.environ.get("IRONFLEET_ROUTING") or str(default_routing())
        return serve_main(["--routing", routing, "--port", str(args.port)])
    if args.cmd == "drive":
        # scripts/ is a namespace package at the repo root, not installed — the drivers
        # resolve it the same way (stand_up_opencode inserts ROOT into sys.path).
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from scripts.stand_up_opencode import main as drive_main
        argv2 = ["--matter-ref", args.matter_ref, "--task-class", args.task_class,
                 "--timeout", str(args.timeout)]
        if args.workspace:
            argv2 += ["--workspace", args.workspace]
        if args.prompt:
            argv2 += ["--prompt", args.prompt]
        return drive_main(argv2)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
