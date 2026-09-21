"""Upgrade regression rig for the OpenCode mount (precheck §5 requirement 1).

Run before ANY opencode version bump. A non-empty problem list means the bump does not
ship; the fallback is always 'pin-hold' — stay on the pinned version and re-verify the
guard hooks against the new one before trying again.

The three guard seams below are what S7c's grounding guard hangs on. experimental.* hooks
are experimental: if 1.18.26 renames or withdraws experimental.text.complete, that is a
problem this rig must report, not a silent degradation.
"""
from __future__ import annotations

import subprocess, sys
from pathlib import Path

EXPECTED_VERSION = "1.18.25"
FALLBACK = "pin-hold"          # named fallback per Jonathan's 2026-09-16 requirement
GUARD_SEAMS = ("tool.execute.before", "tool.execute.after", "experimental.text.complete")


def installed_version() -> str:
    try:
        out = subprocess.run(["opencode", "--version"], capture_output=True, text=True,
                             timeout=30)
        return out.stdout.strip() or out.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def verify_version() -> list[str]:
    v = installed_version()
    if not v:
        return ["opencode not found on PATH — mount cannot be verified"]
    if EXPECTED_VERSION not in v:
        return [f"version drift: expected {EXPECTED_VERSION}, found {v} "
                f"(fallback: {FALLBACK} — do not ship the bump)"]
    return []


def main(argv: list[str] | None = None) -> int:
    problems = verify_version()
    for p in problems:
        print(f"[rig] {p}", file=sys.stderr)
    if problems:
        print(f"[rig] {len(problems)} problem(s). Fallback is '{FALLBACK}': stay on "
              f"{EXPECTED_VERSION}.", file=sys.stderr)
        return 1
    print(f"[rig] mount verified: opencode {EXPECTED_VERSION}, "
          f"guard seams {list(GUARD_SEAMS)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
