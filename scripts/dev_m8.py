# scripts/dev_m8.py — M8 dev/demo server: scratch store + seeded operator + built client + demo worker.
"""Usage (from harness-core):  .venv/Scripts/python.exe scripts/dev_m8.py [--store DIR] [--port 8765] [--fresh]

The store defaults to <tmp>/ironfleet-m8-dev (never the real HARNESS_HOME). On first run it
seeds user `operator` with HARNESS_OPERATOR_PASSWORD, or a random one printed ONCE here (dev
only, loopback bind). Build the client first: `cd web && npm run build`."""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(Path(tempfile.gettempdir()) / "ironfleet-m8-dev"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fresh", action="store_true", help="wipe the scratch store first")
    args = ap.parse_args(argv)
    root = Path(args.store)
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    from harness.service import auth, system
    con = system.open_db(root)
    try:
        if con.execute("SELECT 1 FROM users WHERE username='operator'").fetchone() is None:
            pw = os.environ.get("HARNESS_OPERATOR_PASSWORD") or secrets.token_urlsafe(9)
            auth.create_user(con, "operator", pw, role_id="admin")
            print(f"[dev_m8] seeded operator / {pw}  (store {root})", flush=True)
        else:
            print(f"[dev_m8] store {root} (operator already seeded)", flush=True)
    finally:
        con.close()

    dist = CORE / "web" / "dist"
    if not (dist / "index.html").is_file():
        print("[dev_m8] web/dist missing — run `npm run build` in web/ first", flush=True)
        return 2
    import uvicorn

    from harness.api.app import create_app
    uvicorn.run(create_app(root, web_dist=dist, worker="demo"), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
