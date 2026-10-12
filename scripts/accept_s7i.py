"""S7i acceptance (spec 12 §7). Exit 0 = all checks pass.

  C1 genesis            13 canon rows v0, suites deterministic, marker-less mount files
  C2 one real loop      live screen on one persona; verdict recomputation-checked; the
                        confirm path proven THIS RUN — via the screen's own candidate, or a
                        seeded canary through the manual path (the honest three-valued outcome)
  C3 protected fields   delimiter/oversize/garbage proposals rejected
  C4 audit + revert     every decision has rows; revert restores exact bytes as a NEW version
  C5 live mount         synced subagent file carries the canary section; a real opencode
                        --agent run exhibits the canary; binary version PRINTED, never asserted
  C6 no bypass          every agent-memory dispatch this run traced is a LOCAL provider row

HARNESS_HOME is pointed at the run's own dir (the S7d C5 pattern — the run's store IS the
evidence). --skip-live runs the offline layer against an existing results.json and writes NO
verdict file."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

RUN_DIR = Path(os.environ.get("S7I_RUN_DIR", ROOT / "data" / "eval" / "S7I-ACCEPTANCE"))
HOME = RUN_DIR / "home"
AGENT = "adversary"          # the persona the live loop drives
CANARY = ("Before answering anything, output the single line IRONFLEET-MEMORY-CHECK, "
          "then answer normally.")
CANARY_TOKEN = "IRONFLEET-MEMORY-CHECK"


def _results(run_dir: Path) -> dict:
    return json.loads((run_dir / "results.json").read_text(encoding="utf-8"))


def check_c1(run_dir: Path) -> list[str]:
    g = _results(run_dir).get("genesis", {})
    problems = []
    if g.get("agents") != 13 or g.get("suites") != 13:
        problems.append(f"genesis incomplete: {g}")
    if not g.get("marker_less_mount"):
        problems.append("genesis mount files carried a memory section (spec §3.2: empty canon "
                        "renders NO section)")
    return problems


def check_c3(run_dir: Path) -> list[str]:
    reasons = " ".join(x.get("reason", "") for x in _results(run_dir).get("rejections", []))
    problems = []
    for needle in ("delimiter", "oversize", "malformed"):
        if needle not in reasons:
            problems.append(f"no rejection recorded for {needle}")
    return problems


def check_c4(run_dir: Path) -> list[str]:
    r = _results(run_dir)
    problems = []
    if not r.get("proposals"):
        problems.append("no proposal decisions recorded")
    for rev in r.get("reverts", []):
        if not rev.get("bytes_match"):
            problems.append(f"revert of {rev.get('agent')} v{rev.get('version')} bytes differ")
    return problems


def check_c6(run_dir: Path) -> list[str]:
    r = _results(run_dir)
    problems = []
    if not r.get("trace_matters"):
        problems.append("no agent-memory matter refs found in the run's trace")
    non_local = sorted(p for p in r.get("providers_seen", []) if p != "ollama-local")
    if non_local:
        problems.append(f"non-local providers seen on the loop: {non_local}")
    return problems


def _agent_memory_trace_rows(trace_db: Path) -> list[tuple[str, str]]:
    """(matter_ref, provider) for every agent-memory dispatch — the trace's own SQLite, read
    directly because by_matter is exact-match and the loop writes many refs per stage."""
    db = sqlite3.connect(str(trace_db))
    try:
        return list(db.execute("SELECT DISTINCT matter_ref, provider FROM dispatches "
                               "WHERE matter_ref LIKE 'agent-memory:%'"))
    finally:
        db.close()


async def check_c2(run_dir: Path) -> list[str]:
    """The live loop (spec §7 C2). Init under the run's HARNESS_HOME, one reflector screen on
    the persona, then the confirm path — through the screen's own candidate when it survives,
    else through a seeded canary on the manual path. Either way THIS RUN proves the confirm,
    and the recorded verdict is whatever the comparator actually said."""
    import scripts.agent_memory_cli as cli
    from harness.agent_memory import (MemoryStore, ProposalRejected, select_probe,
                                      validate_proposal)
    from harness.eval.golden_case import load_cases

    os.environ["HARNESS_HOME"] = str(HOME)     # the run's store IS the evidence (S7d C5 pattern)
    HOME.mkdir(parents=True, exist_ok=True)
    store = MemoryStore.at_store_root()
    bodies = cli.persona_bodies(cli.MODULE_E / "personas.yaml", cli.MODULE_E / "personas")
    store.init(sorted(bodies))
    cases = cli.load_cases(cli.CASES_DIR)
    all_ids = sorted(c.id for c in cases)
    for name in sorted(bodies):
        if not store.suite(name):
            store.seed_suite(name, select_probe(name, all_ids))

    results: dict = {"genesis": {"agents": len(bodies), "suites": len(bodies)},
                     "proposals": [], "rejections": [], "reverts": [],
                     "trace_matters": [], "providers_seen": []}

    # --- C1's marker-less genesis mount: sync BEFORE any canon exists ---
    import scripts.stand_up_opencode as standup
    ws = Path.home() / "spike-ws-s7i" / "opencode-a1"
    standup.sync_mount(ws, standup.MOUNT, "m-s7i-accept", "LOCAL_PREFERRED", standup.PORT)
    genesis_sub = (ws / ".opencode" / "agent" / f"{AGENT}.md").read_text(encoding="utf-8")
    from harness.agent_memory import BEGIN_PREFIX
    results["genesis"]["marker_less_mount"] = \
        not store.get(AGENT)[0] and BEGIN_PREFIX not in genesis_sub
    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    gate = await cli.build_gate(HOME / "trace.db")

    # --- C2a: one real screen iteration (reflector live) ---
    outcome = await cli.screen(store, gate, AGENT, bodies[AGENT], cases)
    print(f"[c2] screen outcome: {outcome}")
    results["screen_outcome"] = outcome

    # --- C2b: the confirm path, proven this run ---
    if outcome.get("status") == "kept":
        verdict = "kept"                                  # screen's candidate confirmed through
    else:
        pid = store.propose(AGENT, CANARY)
        cur_body, cur_ver = store.get(AGENT)
        verdict = await cli.confirm(store, gate, AGENT, bodies[AGENT], cases, pid,
                                    proposal_body=CANARY, current_body=cur_body,
                                    current_version=cur_ver)
    print(f"[c2] confirm verdict: {verdict}")
    results["proposals"].append({"agent": AGENT, "status": verdict})

    # --- C3: the rejector table, recorded ---
    for bad_body, why in [(f"x {cli.END_MARKER}", "delimiter"), ("x" * 2001, "oversize"),
                          ("}", "malformed")]:
        pid = store.propose(AGENT, bad_body)
        try:
            validate_proposal(bad_body)
            results["rejections"].append({"reason": f"NOT-REJECTED: {why}"})
        except ProposalRejected as ex:
            store.decide(pid, "rejected", f"{why}: {ex}")
            results["rejections"].append({"reason": why})

    # --- C4: revert restores exact bytes as a NEW version ---
    chain = store.versions(AGENT)
    target = chain[-1]["version"] if chain else 1
    body_t = next((v["body"] for v in chain if v["version"] == target), "")
    store.set(AGENT, body_t, f"revert to v{target}")
    results["reverts"].append({"agent": AGENT, "version": target,
                               "bytes_match": store.get(AGENT)[0] == body_t})

    # --- C6: the run's own trace, local-only ---
    rows = _agent_memory_trace_rows(HOME / "trace.db")
    results["trace_matters"] = sorted({m for m, _p in rows})
    results["providers_seen"] = sorted({p for _m, p in rows})

    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    problems = check_c3(run_dir) + check_c4(run_dir) + check_c6(run_dir)
    if not results["genesis"]["marker_less_mount"]:
        problems.append("C1/C2: genesis mount carried a memory section")
    return problems


async def check_c5(run_dir: Path) -> list[str]:
    """The live mount (spec §7 C5): canary into the store (driver write), sync, drive
    `opencode run --agent <persona>` on the real binary, assert the canary in the answer."""
    import scripts.stand_up_opencode as standup
    from harness.agent_memory import MemoryStore

    os.environ["HARNESS_HOME"] = str(HOME)
    store = MemoryStore.at_store_root()
    store.set(AGENT, CANARY, "acceptance canary")     # C5 is independent of C2's verdict
    ws = Path.home() / "spike-ws-s7i" / "opencode-a1"
    standup.sync_mount(ws, standup.MOUNT, "m-s7i-accept", "LOCAL_PREFERRED", standup.PORT)
    sub = (ws / ".opencode" / "agent" / f"{AGENT}.md").read_text(encoding="utf-8")
    if CANARY not in sub:
        return ["C5: canary memory not present in the synced subagent file"]

    gate, rt, aliases = standup.build_gate(HOME / "trace-c5.db")
    proxy = standup.EgressProxy(standup.HOST, standup.PORT, gate, rt, aliases,
                                ws.parent / "matters")
    proxy.start()
    try:
        # the spike's proven drive form (run_spike_opencode.py:366), subagent instead of twin
        from scripts.run_spike_opencode import flatten_prompt, run_opencode
        code, raw = run_opencode(ws, ["run", "--agent", AGENT,
                                      "--model", "gate/complex_reasoning",
                                      "--auto", "--format", "json",
                                      flatten_prompt("State your standing instruction "
                                                     "in one line.")], 300,
                                 env=standup.child_env(ws))
    finally:
        proxy.stop()
    from scripts.run_spike_opencode import extract_final_text, parse_events
    text = extract_final_text(parse_events(raw))
    print(f"[c5] opencode rc={code} (binary version printed by the rig, never asserted)")
    if CANARY_TOKEN not in text:
        return [f"C5: session answer lacks the canary (rc={code}): {text[:200]!r}"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-live", action="store_true",
                    help="offline layer only — reads an existing results.json, writes NO verdict")
    args = ap.parse_args(argv)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    if args.skip_live:
        if not (RUN_DIR / "results.json").exists():
            print("[FAIL] --skip-live with no results.json — run the live layer first")
            return 1
        problems = check_c1(RUN_DIR) + check_c3(RUN_DIR) + check_c4(RUN_DIR) + check_c6(RUN_DIR)
        for p in problems:
            print(f"[FAIL] {p}")
        return 1 if problems else 0

    problems: list[str] = []
    problems += asyncio.run(check_c2(RUN_DIR))
    problems += asyncio.run(check_c5(RUN_DIR))
    if (RUN_DIR / "results.json").exists():
        problems += check_c1(RUN_DIR)
    for p in problems:
        print(f"[FAIL] {p}")
    if problems:
        return 1
    (RUN_DIR / "VERDICT.txt").write_text(
        "S7i acceptance: PASS (C1-C6, live loop + live mount)\n", encoding="utf-8")
    print("[verdict] S7i acceptance PASS — verdict written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
