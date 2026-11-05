"""Shim for the M3 substrate relocation: the real module is harness.substrate.mount.

Every name below is a re-export, so the ~20 accept/bench/probe scripts and the tests that
`from scripts.stand_up_opencode import ...` keep working unchanged. Run as a CLI:
  .venv/Scripts/python.exe scripts/stand_up_opencode.py --matter-ref <uuid> ...
"""
from __future__ import annotations

import sys

from harness.substrate.mount import *          # noqa: F401,F403 — public surface
from harness.substrate.mount import (          # noqa: F401 — names star-import skips
    HOST, PORT, ROOT, DATA, MOUNT, MODULE_E, PLUGIN_SRC, GUARD_TEMPLATE, TOOLS_TEMPLATE,
    GUARD_CLI, PYTHON, ROUTING, MATTERS_ROOT, OLLAMA_URL, OPENCODE_EXE,
    HARDEN_ENV, BEARER_ENV_KEYS, BEARER_ENV_PREFIXES, EXPECTED_VERSION,
    _probe_ollama, _scalar_usage, build_scheduler, build_gate as _bootstrap_build_gate,
    bearer_keys, child_env, render_tools_plugin, inject_memory, sync_mount, build_gate,
    installed_version, main, run_opencode_session,
)

if __name__ == "__main__":
    sys.exit(main())
