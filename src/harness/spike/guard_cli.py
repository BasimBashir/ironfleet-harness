# src/harness/spike/guard_cli.py
"""CLI shim so non-Python spike mounts (OpenCode plugins run under Bun/JS) can call the
REAL guard — `portable_grounding_guard` via `OpenCodeHookAdapter` — instead of a JS
re-implementation. A JS re-implementation would not be a port of the guard and would
break spike parity.

Two transports:
  stdin  : one JSON object `{"output": str, "allowed": [str, ...]}` on stdin; the
           adapter's decision JSON on stdout. Fine for small texts (tests, smoke).
  files  : `guard_cli.py <in.json> <out.json>` — payload read from / written to files.
           REQUIRED for model outputs: Bun's spawnSync on Windows deadlocks once stdin
           exceeds the pipe buffer (~64 KB; observed live 2026-09-01 — status=null,
           empty stderr, hook timeout, subagent killed). Long completions ride this mode.

Both fail loud (non-zero exit / error decision) rather than passing text through unguarded.
"""
from __future__ import annotations

import json
import sys


def handle(payload: dict) -> dict:
    from harness.spike.guard_port import OpenCodeHookAdapter
    return OpenCodeHookAdapter().handle(payload)


def _run(payload: dict) -> int:
    if not isinstance(payload, dict) or "output" not in payload:
        json.dump({"decision": "error", "reason": "stdin JSON must be an object with at "
                                                  "least an 'output' field", "output": ""},
                  sys.stdout)
        return 2
    json.dump(handle(payload), sys.stdout, ensure_ascii=False)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 2:                       # file mode: <in.json> <out.json>
        with open(args[0], "r", encoding="utf-8") as f:
            payload = json.load(f)
        with open(args[1], "w", encoding="utf-8") as f:
            if not isinstance(payload, dict) or "output" not in payload:
                json.dump({"decision": "error", "reason": "input JSON must be an object "
                                                          "with an 'output' field", "output": ""}, f)
                return 2
            json.dump(handle(payload), f, ensure_ascii=False)
        return 0
    return _run(json.loads(sys.stdin.read()))


if __name__ == "__main__":
    sys.exit(main())
