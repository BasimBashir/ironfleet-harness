# src/harness/api/__main__.py — python -m harness.api seed-operator|serve (M7 plan §2)
"""seed-operator: create the single admin (password from HARNESS_OPERATOR_PASSWORD
or a prompt — never an argv flag, so it stays out of shell history).
serve: uvicorn on 127.0.0.1 only (02 §12: loopback bind, no TLS)."""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from harness.paths import resolve_store_root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.api")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed-operator")
    s.add_argument("--username", required=True)
    v = sub.add_parser("serve")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--worker", choices=["demo"], default=None,
                   help="run executions in-process with the named demo body (M8)")
    v.add_argument("--web-dist", default=str(Path(__file__).resolve().parents[3] / "web" / "dist"),
                   help="built React client to serve at / (skipped if missing)")
    args = ap.parse_args(argv)
    root = resolve_store_root()[0]
    if args.cmd == "seed-operator":
        from harness.service import auth, system
        pw = os.environ.get("HARNESS_OPERATOR_PASSWORD") or getpass.getpass("password: ")
        con = system.open_db(root)
        try:
            uid = auth.create_user(con, args.username, pw, role_id="admin")
        finally:
            con.close()
        print(f"operator {args.username} created ({uid}) in {root}")
        return 0
    import uvicorn
    from harness.api.app import create_app
    uvicorn.run(create_app(root, web_dist=args.web_dist, worker=args.worker),
                host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
