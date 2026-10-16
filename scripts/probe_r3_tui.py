# scripts/probe_r3_tui.py
"""R3 TUI research-gate probe driver (spec 16): P1-P7, live on opencode 1.18.25, no mocks.

Subcommands:
  python scripts/probe_r3_tui.py p1|p2|...|p7|all [--evidence-root DIR]

Every probe asserts the pin FIRST (spec 16 §7: drift = refuse to measure), starts the
gate-backed proxy itself, and writes <probe>.json + <probe>.log into the evidence dir
data/eval/R3-RESEARCH-<date>/. Live-driver discipline: the suite runs only pure helpers.
"""
from __future__ import annotations

import argparse
import json
import subprocess  # noqa: F401 — probe bodies (Tasks 3-9) shell out through it
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EV_ROOT = ROOT / "data" / "eval"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_spike_opencode import (  # noqa: E402,F401 — Task 2's run helper consumes these
    extract_final_text, flatten_prompt, opencode_cmd, parse_events, run_opencode)

DEFAULT_TIMEOUT_S = 480  # the S7j-W watchdog budget; startup hang ~2 in 7


def _opencode_version() -> str:
    code, raw = run_opencode(ROOT, ["--version"], timeout=60)
    if code != 0:
        raise SystemExit(f"FAIL: opencode --version exited {code}: {raw[:200]}")
    return raw.strip().splitlines()[-1].strip()


def _autoupdate_global() -> bool:
    cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not cfg.is_file():
        return False
    return '"autoupdate": false' in cfg.read_text(encoding="utf-8")


def pin_check() -> dict:
    from harness.packaging.macdist import PINS
    # PINS holds the npm spec ("opencode-ai@1.18.25") while --version prints the bare
    # number — compare (and report) at the bare version so the gate OPENS on the pinned
    # box; a literal string == would refuse forever (verify_opencode_mount.py precedent).
    expected = PINS["opencode"].rsplit("@", 1)[-1]
    found = _opencode_version().rsplit("@", 1)[-1]
    auto = _autoupdate_global()
    return {"expected": expected, "found": found, "autoupdate": auto,
            "ok": found == expected and auto}


def require_pin() -> dict:
    report = pin_check()
    if not report["ok"]:
        # exit 3 per contract: acceptance must distinguish "pin drifted" (3) from
        # "probe crashed" (1) — a string SystemExit would collapse both to 1.
        print(f"REFUSING TO MEASURE — pin drift: {report} (spec 16 §7)", file=sys.stderr)
        raise SystemExit(3)
    return report


def evidence_dir(root: Path | None = None) -> Path:
    d = (root or EV_ROOT) / f"R3-RESEARCH-{date.today().isoformat()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_evidence(ev: Path, name: str, body: str) -> None:
    (ev / name).write_text(body, encoding="utf-8")


@dataclass
class RunResult:
    code: int
    raw: str
    events: list
    attempts: int
    label: str
    seconds: float


def run_capture(ws: Path, args: list[str], timeout: int = DEFAULT_TIMEOUT_S,
                env: dict[str, str] | None = None, label: str = "run",
                ev: Path | None = None) -> RunResult:
    """run_opencode + parse_events + evidence tee. Retries ONCE on the startup-hang
    signature (timeout tree-kill AND nothing parsed — the binary died before speaking).
    A second identical failure is fatal: two hangs in a row means the box or the mount
    is broken, and the probe must not burn the schedule retrying (spec 16 §7)."""
    t0 = time.monotonic()
    code, raw = run_opencode(ws, args, timeout=timeout, env=env)
    events = parse_events(raw)
    attempts = 1
    if code == 124 and not events:
        print(f"[{label}] hang signature (124, no events) — retrying once", flush=True)
        code, raw = run_opencode(ws, args, timeout=timeout, env=env)
        events = parse_events(raw)
        attempts = 2
        if code == 124 and not events:
            raise SystemExit(f"[{label}] hung twice — aborting probe")
    if ev is not None:
        _write_evidence(ev, f"{label}.log", raw)
    return RunResult(code, raw, events, attempts, label, time.monotonic() - t0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("probe", choices=[*PROBES, "all"])
    ap.add_argument("--evidence-root", type=Path, default=None)
    args = ap.parse_args(argv)
    ev = evidence_dir(args.evidence_root)
    require_pin()
    names = list(PROBES) if args.probe == "all" else [args.probe]
    results = {}
    for name in names:
        print(f"[{name}] running…", flush=True)
        results[name] = PROBES[name](ev)
        _write_evidence(ev, f"{name}.json", json.dumps(results[name], indent=2))
        print(f"[{name}] -> {json.dumps(results[name])[:400]}", flush=True)
    return 0


PROBES: dict[str, object] = {}  # populated per-probe below; registry validated by tests


def _stub(ev: Path) -> dict:
    raise NotImplementedError("probe lands in its own task")


for _n in ("p1", "p2", "p3", "p4", "p5", "p6", "p7"):
    PROBES[_n] = _stub


if __name__ == "__main__":
    raise SystemExit(main())
