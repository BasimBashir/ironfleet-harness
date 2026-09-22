# scripts/accept_s7b.py
"""Live acceptance for S7b (A-1). Two paths, both through the same mount:

  positive   — a real extraction query reaches Ollama and lands in the trace store
               with verified=0 (honest: Ollama cannot report its engine)
  fail-closed — a drafting query refuses, traces status=refused, and OpenCode has
               no second provider to fall back to

Run: .venv/Scripts/python.exe scripts/accept_s7b.py
"""
from __future__ import annotations

import json, os, sqlite3, subprocess, sys, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.stand_up_opencode import (HOST, PORT, MOUNT, ROUTING, sync_mount,
                                       build_gate, run_opencode_session, HARDEN_ENV)
from harness.egress_proxy import EgressProxy

EXTRACTION_PROMPT = ("List the party names as bullets. Text: 'ACME Ltd and Beta Corp "
                     "entered into an agreement on 3 March 2026; Gamma Inc joined as "
                     "guarantor on 1 April 2026.'")
DRAFTING_PROMPT = "Draft a statement of claim for a breach of contract."

# run_opencode() builds its child env as {**os.environ, "PWD": ws} — it does NOT accept an
# env argument. So hardening only reaches the child by mutating THIS process's os.environ,
# which happens once in main(); do not re-derive a local env dict here.


def run_case(task_class: str, prompt: str, gate, rt, ws: Path, timeout: int) -> dict:
    matter = f"a1-{task_class}-{uuid.uuid4()}"
    sync_mount(ws, MOUNT, matter, "LOCAL_PREFERRED", PORT)
    model = f"gate/{task_class}"
    rc, text = run_opencode_session(ws, model, prompt, timeout)
    rows = gate.trace.by_matter(matter)
    return {"task_class": task_class, "model": model, "rc": rc, "rows": rows,
            "out_tail": (text or "")[-400:]}


def distinct_providers(trace_db: Path) -> set[str]:
    """Every distinct provider the store has ever recorded.

    TraceStore.summary() returns dispatches/errors/by_engine — it has no per-provider view,
    and trace.py is byte-locked for this plan. Query the DB directly, read-only: the sandbox
    rule is mode=ro, counts/names only, never row content."""
    con = sqlite3.connect(f"file:{trace_db}?mode=ro", uri=True)
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT provider FROM dispatches")}
    finally:
        con.close()


def main() -> int:
    # NOT under ~/spike-ws: that parent already holds the spike's own opencode repo, and
    # opencode groups sibling git repos under one parent into a multi-instance project whose
    # session can attach the wrong instance (observed 2026-09-01). spike-ws-a1 is the same
    # parent the driver's default uses since Task 6's fix round 1.
    ws = Path.home() / "spike-ws-a1" / "opencode-a1-accept"
    ws.mkdir(parents=True, exist_ok=True)
    gate, rt, aliases = build_gate(ws / "trace.db")
    # ThreadingHTTPServer binds in its CONSTRUCTOR, not in start() — start() only spawns the
    # serve_forever thread and cannot raise OSError. The guard must wrap construction or the
    # bind failure escapes uncaught. Same placement as the driver's port-collision guard.
    try:
        proxy = EgressProxy(HOST, PORT, gate, rt, aliases, ws / "matter.json")
    except OSError as ex:
        print(f"port {PORT} busy — close whatever holds it and retry: {ex}", file=sys.stderr)
        return 2
    proxy.start()

    # Hardening must land in os.environ BEFORE run_opencode_session, which copies
    # os.environ into the child rather than accepting an env argument.
    for k, v in HARDEN_ENV.items():
        os.environ[k] = v

    results = {}
    try:
        results["positive"] = run_case("extraction", EXTRACTION_PROMPT, gate, rt, ws, 300)
        results["failclosed"] = run_case("drafting", DRAFTING_PROMPT, gate, rt, ws, 120)
    finally:
        proxy.stop()

    ok = True
    pos, fc = results["positive"], results["failclosed"]

    def check(label: str, cond: bool, detail: str) -> None:
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {label} — {detail}", file=sys.stderr)
        ok = ok and cond

    check("positive traced one dispatch", len(pos["rows"]) == 1,
          f"{len(pos['rows'])} row(s)")
    if pos["rows"]:
        r = pos["rows"][0]
        check("provider is ollama-local", r.provider == "ollama-local", r.provider)
        check("model is thomson1-chat", "thomson1" in r.model, r.model)
        check("verified is 0 (honest CR-3)", r.verified == 0, f"verified={r.verified}")
        check("status ok", r.status == "ok", r.status)
    check("fail-closed refused", bool(fc["rows"]) and fc["rows"][0].status == "refused",
          f"{len(fc['rows'])} row(s)" + (f", status={fc['rows'][0].status}" if fc["rows"] else ""))
    check("fail-closed provider is '-'", bool(fc["rows"]) and fc["rows"][0].provider == "-",
          fc["rows"][0].provider if fc["rows"] else "no row")
    # No dispatch may ever have gone anywhere but ollama-local. summary() has no provider
    # view, so this reads the store's distinct providers directly (read-only).
    providers = distinct_providers(ws / "trace.db")
    check("no non-local provider in the store",
          providers <= {"ollama-local", "-"},
          f"distinct providers: {sorted(providers)}")
    print(json.dumps({k: {kk: (vv if not isinstance(vv, list) else len(vv))
                          for kk, vv in v.items()} for k, v in results.items()},
                     indent=2, default=str), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
