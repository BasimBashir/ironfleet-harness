# src/harness/module_e/dispatch.py
"""CLI entry point for tool calls from the TS tools plugin.

The TS shim (src/harness/spike/candidates/opencode/ironfleet-tools.ts) holds no logic: it writes
the model's args to a file, spawns

    python -m harness.module_e.dispatch <toolName> <argsJsonFile> <outFile>

and returns stdout. This module owns the resolution — manifest row, ported-status gate,
`module:fn` import, JSON transport — so every tool's behaviour stays in Python, where pytest
reaches it.

Exit contract: 0 on success; ANY failure propagates and exits non-zero with the traceback on
stderr, which the shim hands back as the tool result. Nothing here catches and converts a
KeyError or TypeError into a silent empty result (Task 7 characterisation: missing dict keys
raise KeyError, and `route` with no intent must stay loud).
"""
from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path

from .tools import ToolEntry, load_manifest


def dispatch(manifest_path: str, tool_name: str, args_file: str, out_file: str) -> int:
    """Entry point for tool calls from the TS plugin. Resolves the manifest row, imports its
    `module:fn` entry, and writes the JSON result. A deferred/blocked tool is an error here —
    the manifest is the single source of truth for what is callable.

    Lookup is by ROW name (`ironfleet_statutory_demand`, `route`, ...): a row's kernel aliases
    (`companies_act`, `cccfa_2003`, ...) are fields on the row, never keys."""
    entry: ToolEntry = load_manifest(Path(manifest_path))[tool_name]
    if entry.status != "ported":
        raise RuntimeError(f"{tool_name}: status={entry.status} ({entry.reason})")
    mod_name, fn_name = entry.entry.split(":", 1)
    fn = getattr(import_module(mod_name), fn_name)
    args = json.loads(Path(args_file).read_text(encoding="utf-8"))
    # json.dumps with no `default=` is deliberate: a tool returning a non-JSON type (a Decimal,
    # a datetime) must fail loud here rather than be silently stringified into the result.
    Path(out_file).write_text(
        json.dumps(fn(args), ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(dispatch(*sys.argv[1:]))
