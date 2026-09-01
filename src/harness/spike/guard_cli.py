# src/harness/spike/guard_cli.py
"""CLI shim so non-Python spike mounts (OpenCode plugins run under Bun/JS) can call the
REAL guard — `portable_grounding_guard` via `OpenCodeHookAdapter` — instead of a JS
re-implementation. stdin: one JSON object `{"output": str, "allowed": [str, ...]}`;
stdout: the adapter's decision JSON `{"decision", "reason", "output"}` (annotated text
in `output`). Exit 0 on a handled call; exit 2 on malformed stdin (fail loud, never
silently pass text through unguarded).

S4 mount detail: candidates that are Python-native (OpenHands) import guard_port
directly; this shim exists for the JS side only.
"""
from __future__ import annotations

import json
import sys


def handle(payload: dict) -> dict:
    from harness.spike.guard_port import OpenCodeHookAdapter
    return OpenCodeHookAdapter().handle(payload)


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or "output" not in payload:
            raise ValueError("stdin JSON must be an object with at least an 'output' field")
    except Exception as ex:                                  # noqa: BLE001 — one loud failure mode
        json.dump({"decision": "error", "reason": f"guard_cli bad stdin ({type(ex).__name__}): "
                                                  f"{ex}", "output": ""}, sys.stdout)
        return 2
    json.dump(handle(payload), sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
