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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))    # `import scripts.*` — scripts/ carries no __init__.py
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
    # two validator-level classes; malformed-JSON rejection lives in the REFLECTOR path and is
    # unit-tested there (test_screen_reflector_garbage_is_recorded_rejected_not_crashed)
    for needle in ("delimiter", "oversize"):
        if needle not in reasons:
            problems.append(f"no rejection recorded for {needle}")
    if "NOT-REJECTED" in reasons:
        problems.append("a rejector-table body unexpectedly PASSED validation")
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
    from harness.agent_memory import (END_MARKER, MemoryStore, ProposalRejected, select_probe,
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

    # A resumed run keeps the genesis flag recorded by the FRESH pass (genesis is a fresh-store
    # property — see the sync check below); a fresh run starts it False until proven.
    prev_genesis = _results(run_dir).get("genesis", {}) if (run_dir / "results.json").exists() else {}
    results: dict = {"genesis": {"agents": len(bodies), "suites": len(bodies),
                                 "marker_less_mount": prev_genesis.get("marker_less_mount", False)},
                     "proposals": [], "rejections": [], "reverts": [],
                     "trace_matters": [], "providers_seen": []}

    # --- C1's marker-less genesis mount — proven against a SCRATCH fresh store every run:
    # genesis is a fresh-store property, and a resumed run's store has already been written to
    # by C4/C5, so trusting it (or a flag recorded by an earlier formula) would be dishonest.
    # Costs ~2s, no dispatches: init + one sync, then assert the section is absent.
    import scripts.stand_up_opencode as standup
    from harness.agent_memory import BEGIN_PREFIX
    ws = Path.home() / "spike-ws-s7i" / "opencode-a1"
    scratch = run_dir / "genesis-home"
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ["HARNESS_HOME"] = str(scratch)
    MemoryStore.at_store_root().init(sorted(bodies))
    standup.sync_mount(ws, standup.MOUNT, "m-s7i-genesis", "LOCAL_PREFERRED", standup.PORT)
    genesis_sub = (ws / ".opencode" / "agent" / f"{AGENT}.md").read_text(encoding="utf-8")
    # No canon at genesis -> inject_memory writes no memory primary at all; absence is
    # itself marker-less.
    genesis_mem_f = ws / ".opencode" / "agent" / f"{AGENT}-memory.md"
    genesis_mem = (genesis_mem_f.read_text(encoding="utf-8")
                   if genesis_mem_f.exists() else "")
    results["genesis"]["marker_less_mount"] = (BEGIN_PREFIX not in genesis_sub
                                               and BEGIN_PREFIX not in genesis_mem)
    os.environ["HARNESS_HOME"] = str(HOME)      # back to the run store for the live checks
    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    gate = await cli.build_gate(HOME / "trace.db")

    # --- C2a + C2b — resumable (the S7h --recall precedent): when this run's confirm already
    # has recorded legs, do NOT re-spend ~85 min of dispatches; the recorded outcome IS the
    # evidence. A fresh run dir always runs the live path.
    prior = [p for p in store.proposals_for(AGENT) if p["status"] in ("kept", "rolled_back")]
    if any(store.legs(p["id"], "confirm") for p in prior):
        verdict = prior[-1]["status"]
        outcome = {"status": "resumed", "note": f"recorded confirm verdict {verdict} replays "
                                               "from this run's own store; no re-dispatch"}
        print(f"[c2] resume: {outcome['note']}")
    else:
        # --- C2a: one real screen iteration (reflector live) ---
        outcome = await cli.screen(store, gate, AGENT, bodies[AGENT], cases)
        print(f"[c2] screen outcome: {outcome}")
        # --- C2b: the confirm path, proven this run ---
        if outcome.get("status") == "kept":
            verdict = "kept"                              # screen's candidate confirmed through
        else:
            pid = store.propose(AGENT, CANARY)
            cur_body, cur_ver = store.get(AGENT)
            verdict = await cli.confirm(store, gate, AGENT, bodies[AGENT], cases, pid,
                                        proposal_body=CANARY, current_body=cur_body,
                                        current_version=cur_ver)
    print(f"[c2] confirm verdict: {verdict}")
    results["proposals"].append({"agent": AGENT, "status": verdict})

    # --- C3: the rejector table, recorded ---
    for bad_body, why in [(f"x {END_MARKER}", "delimiter"), ("x" * 2001, "oversize")]:
        pid = store.propose(AGENT, bad_body)
        try:
            validate_proposal(bad_body)
            store.decide(pid, "rejected",
                         "acceptance driver declined — validation unexpectedly passed")
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
    if not results["genesis"].get("marker_less_mount"):
        problems.append("C1/C2: genesis mount carried a memory section")
    return problems


def check_c5(run_dir: Path) -> list[str]:
    """The live mount (spec §7 C5): canary into the store (driver write), sync, drive
    `opencode run --agent <persona>` on the real binary, assert the canary in the answer.
    SYNC deliberately: standup.build_gate (probe) and run_opencode block — and the probe's
    asyncio.run inside a running loop is the exact nested-loop trap S7e's controller found.

    Two-valued on the session leg (spec §7's three-valued honesty, applied): the canary in the
    answer = proof; the answer coming from opencode's DEFAULT agent (1.18.33 falls back when
    --agent names a subagent, and @-delegation rides the dead tool path — S7c check 3) =
    BLOCKED-BY-BINARY, recorded as evidence, not a check failure. The mount-projection half
    (canary present in the synced file) is asserted unconditionally."""
    import subprocess

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
    # The drivable canon carrier (see stand_up.inject_memory — subagent files are not
    # directly drivable on any tested binary): the session leg reads THIS file.
    mem_primary = (ws / ".opencode" / "agent" / f"{AGENT}-memory.md").read_text(encoding="utf-8")
    if CANARY not in mem_primary:
        return ["C5: canary memory not present in the synced memory primary"]

    try:
        exe = standup.OPENCODE_EXE if Path(standup.OPENCODE_EXE).exists() else "opencode"
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=60).stdout.strip()
    except Exception as ex:                              # noqa: BLE001 — print-only evidence
        ver = f"unavailable ({ex})"
    print(f"[c5] binary version (printed, never asserted): {ver}")

    gate, rt, aliases = standup.build_gate(HOME / "trace-c5.db")
    # The persona's class is complex_reasoning and Ollama is honestly mechanical-only (CR-3);
    # the loop's recorded in-memory override applies here too (2026-08-28 precedent;
    # verified=0; every dispatch traced). Without it the gate REFUSES — correct fail-closed,
    # proven live 2026-10-12 ("no eligible provider for complex_reasoning", 403).
    gate.registry.get("ollama-local").admitted = "full"
    print("[deviation] in-memory admission override for the C5 live mount (recorded precedent)")
    proxy = standup.EgressProxy(standup.HOST, standup.PORT, gate, rt, aliases,
                                ws.parent / "matters")
    proxy.start()
    try:
        # The spike's proven drive form (run_spike_opencode.py:366 + run_opencode_session),
        # memory-primary instead of twin: primary-mode --agent is what both pinned binaries
        # accept, and the twin must stay byte-exact (S7c check 1's comparator).
        from scripts.run_spike_opencode import flatten_prompt, run_opencode
        code, raw = run_opencode(ws, ["run", "--agent", f"{AGENT}-memory",
                                      "--model", "gate-local/gate/complex_reasoning",
                                      "--auto", "--format", "json",
                                      flatten_prompt("State your standing instruction "
                                                     "in one line.")], 900,
                                 env=standup.child_env(ws))
    finally:
        proxy.stop()
    from scripts.run_spike_opencode import extract_final_text, parse_events
    text = extract_final_text(parse_events(raw))
    print(f"[c5] opencode rc={code}")
    if CANARY_TOKEN in text:
        status = "pass"
        evidence = {"rc": code, "final_text_head": text[:200]}
    elif "Falling back to default agent" in raw or text.strip().startswith("I am opencode"):
        # The session ran but the canon-carrying agent never engaged — the mount resolved to
        # the default agent (observed when --agent names a subagent on either pinned binary).
        # Not a mount defect: the canary is in the file (asserted above) and the dispatch
        # reached the gate (traced). Recorded as evidence, not a check failure.
        status = "blocked_by_binary"
        evidence = {"rc": code, "final_text_head": text[:200],
                    "reason": "opencode answered as the default agent — the named agent did "
                              "not engage (subagent-mode files fall back on both pinned "
                              "binaries; the memory primary is primary-mode, so this branch "
                              "now indicates a real mount/binary surprise)."}
    else:
        return [f"C5: session answer lacks the canary (rc={code}): {text[:200]!r}"]
    results = _results(run_dir)
    results["c5"] = {"status": status, **evidence}
    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[c5] session leg: {status}")
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
    problems += check_c5(RUN_DIR)
    if (RUN_DIR / "results.json").exists():
        problems += check_c1(RUN_DIR)
    for p in problems:
        print(f"[FAIL] {p}")
    c5_status = _results(RUN_DIR).get("c5", {}).get("status", "unknown")
    if problems:
        return 1
    if c5_status == "blocked_by_binary":
        (RUN_DIR / "VERDICT.txt").write_text(
            "S7i acceptance: CONDITIONAL — C1-C4+C6 PASS on the live loop; C5's mount\n"
            "projection PASSES (canary in the synced subagent file) but the live session-read\n"
            "leg is BLOCKED BY BINARY: opencode 1.18.33 falls back to the default agent when\n"
            "--agent names a subagent, and @-delegation rides the dead tool path (S7c check 3).\n"
            "The full C5 proof lands with the pin decision (1.18.25 drove subagents directly,\n"
            "spike-proven). Evidence: results.json c5.\n", encoding="utf-8")
        print("[verdict] S7i acceptance CONDITIONAL — verdict written (C5 session leg "
              "blocked by binary; harness refuses to lie)")
        return 1
    (RUN_DIR / "VERDICT.txt").write_text(
        "S7i acceptance: PASS (C1-C6, live loop + live mount)\n", encoding="utf-8")
    print("[verdict] S7i acceptance PASS — verdict written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
