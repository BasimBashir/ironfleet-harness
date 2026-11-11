# src/harness/api/__main__.py — python -m harness.api seed-operator|serve (M7 plan §2)
"""seed-operator: create the admin. With HARNESS_OPERATOR_PASSWORD set that is
the password; without it the account is admin/admin and must set a real password
at first sign-in (B, ask #8). serve: uvicorn on 127.0.0.1 only (02 §12: loopback
bind, no TLS)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from harness.paths import resolve_store_root


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.api")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed-operator")
    s.add_argument("--username", default="admin")
    v = sub.add_parser("serve")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--worker", choices=["demo", "live"], default=None,
                   help="run executions in-process: demo body (M8) or the live opencode crew")
    v.add_argument("--web-dist", default=str(Path(__file__).resolve().parents[3] / "web" / "dist"),
                   help="built React client to serve at / (skipped if missing)")
    args = ap.parse_args(argv)
    root = resolve_store_root()[0]
    if args.cmd == "seed-operator":
        from harness.service import auth, system
        pw = os.environ.get("HARNESS_OPERATOR_PASSWORD")
        con = system.open_db(root)
        try:
            if pw:
                uid = auth.create_user(con, args.username, pw, role_id="admin")
                print(f"operator {args.username} created ({uid}) in {root}")
            else:
                uid = auth.create_user(con, args.username, "admin", role_id="admin",
                                       must_change_password=True)
                print(f"operator {args.username} created ({uid}) in {root} —"
                      " password 'admin'; a new password is required at first sign-in")
        finally:
            con.close()
        return 0
    import uvicorn
    from harness.api.app import create_app
    try:  # M11 T4: startup failures leave a local log under <root>/crash/
        uvicorn.run(create_app(root, web_dist=args.web_dist, worker=args.worker),
                    host="127.0.0.1", port=args.port)
    except Exception:
        from harness.crashlog import capture
        capture(root, "api-serve")  # never a network send — 02 §15
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
