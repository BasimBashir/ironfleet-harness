"""Shim for the M3 substrate relocation: the real module is harness.session.cli.

Run as a CLI:
  .venv/Scripts/python.exe scripts/session_cli.py --list
"""
from __future__ import annotations

from harness.session.cli import *             # noqa: F401,F403 — public surface
from harness.session.cli import (            # noqa: F401 — names star-import skips
    WORKSPACE_SUBDIR, _store_and_driver, _fmt_session, main_with_args, _dispatch, main)

if __name__ == "__main__":
    raise SystemExit(main())
