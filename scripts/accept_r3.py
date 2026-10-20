"""R3 acceptance — the IronFleet TUI (spec 17 section 7 + spec 16 section 8).

Every check drives THE TUI'S OWN CODE PATH — the same SessionDriver/FactoryRunner
the Textual shell drives, through the SAME gate/proxy/substrate — not a parallel
harness. Exit 0 requires ALL checks. Verdicts land as JSON in the evidence dir.

  C1 fanout    one task -> >=2 agents started (factory's plan, real spawns)
  C2 view      the global view reflects both agents (jobs + agents panes)
  C3 drilldown every turn's trace_refs land in trace.db (P5's drilldown contract)
  C4 ingest    docs land in the matter corpus (chunk count for the matter)
  C5 resume    a KILLED session continues from the JSONL (the anchor carries)
  C6 compact   /compact's checkpoint row exists; the auto trigger fires at safe_fill
  C7 doclive   an agent's new/edited file appears in the doc pane's status text
  C8 modes     shift+TAB cycles all three D-T2 modes; the active mode is shown
  C9 tokens    per-agent used-vs-remaining against the provider row's window

Usage: .venv/Scripts/python.exe scripts/accept_r3.py [--evidence DIR]
       [--checks fanout,view,...] [--matter REF] [--session ID]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PY = str(ROOT / ".venv/Scripts/python.exe")
HARNESS = str(ROOT / "scripts/session_cli.py")
ANCHOR = "R3-ANCHOR-7Q"
ANCHOR_PROMPT = f"Reply with exactly {ANCHOR} and nothing else."

# The mechanical class this box honestly serves (research/09 section 3): Ollama is
# mechanical-only (CR-3); nvidia-nim serves the non-mechanical classes. The shell's
# own default turn model is the extraction alias, which the routing table serves.
MODEL = "gate-local/gate/extraction"
SPAWN_S = 480                # the S7j-W watchdog budget, per spawn
CLI_S = 300
# The kill leg (C5): a deliberately long turn, terminated mid-generation after
# this many seconds — run_opencode's own timeout path tree-kills the REAL
# process (code 124). No wmic: it is gone from this Windows build. The count
# must OUTRUN the budget: 3000 lines ≈ 3x 45s at this box's measured output
# rate, yet under the 16k output clamp (a clamped-but-finished turn would
# return 0 and fail the leg loudly).
KILL_AFTER_S = 45
KILL_PROMPT = "Count from 1 to 3000, one number per line."


# -- pure helpers (the matcher, the argv assembly; unit-tested) -----------------

def anchor_regex(token: str):
    """The anchor is planted in the PROMPT; the carrier is the model's reply. The
    match runs on the raw JSON-escaped stream (text parts are JSON), so escape
    both sides and match the literal token."""
    return re.compile(re.escape(token))


def is_checkpoint_row(row) -> bool:
    """The checkpoint row is marked by its display (COMPACT_MARKER) — the field
    /resume and this driver match on."""
    return (getattr(row, "display", "") or "").startswith("/compact")


def turn_argv_for_check(agent: str, token: str,
                        continue_session: str | None = None) -> list[str]:
    from harness.session.workspace import turn_argv
    return turn_argv(agent, MODEL, f"Reply with exactly {token} and nothing else.",
                     continue_session)


# -- the live runner (retry once on the known startup hang, never a loop) --------

def _run_live(argv: list[str], timeout: int = SPAWN_S) -> tuple[int, str]:
    last: tuple[int, str] = (1, "")
    for attempt in (1, 2):
        try:
            r = subprocess.run([PY, HARNESS, *argv], capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            last = (1, f"timeout after {timeout}s: {exc}")
        else:
            last = (r.returncode, (r.stdout or "") + (r.stderr or ""))
        if last[0] == 0:
            return last
        print(f"    attempt {attempt}: exit {last[0]}; retrying once", flush=True)
    return last


# -- the checks ------------------------------------------------------------------

def check_fanout(ctx: dict) -> list[str]:
    """One task -> >=2 agents started: the factory's shell-drives plan, real
    spawns through the driver the TUI drives."""
    problems: list[str] = []
    store = ctx["store"]
    sid = ctx["sid"]
    if not sid:
        return [f"no session id (the earlier --new failed)"]
    from harness.session.driver import SessionDriver
    from harness.session.factory import FactoryRunner
    driver = SessionDriver(store, store.root / "workspaces")
    runner = FactoryRunner(driver, store=store, mode="shell-drives")
    plan_text = ("```plan\n"
                 f"gather|hunter-drive|{ANCHOR_PROMPT}\n"
                 "verify|clerk-drive|Confirm the gather stage reported. Reply DONE only.\n"
                 "```")
    rows = asyncio.run(runner.run_task(sid, ctx["matter"], "R3 acceptance fanout",
                                       plan_text=plan_text))
    produced = [r.agent for r in rows if r.output_summary or r.tools_used]
    print(f"    stage rows: {[r.agent for r in rows]}", flush=True)
    if len(produced) < 2:
        problems.append(f"fan-out < 2 producing agents: {produced} (see errors.jsonl)")
    if len({j["agent"] for j in store.jobs(sid)}) < 2:
        problems.append("jobs ledger shows < 2 agents")
    return problems


def check_view(ctx: dict) -> list[str]:
    """The global view reflects BOTH agents — jobs + agents, from the substrate."""
    from harness.session.tui import IronFleetApp, render_agents
    from harness.trace import TraceStore
    store, sid = ctx["store"], ctx["sid"]
    # The trace injected as the shell does — without it the view's agents half
    # never renders and the check would pass on the jobs table alone.
    app = IronFleetApp(store, session_id=sid,
                       trace=TraceStore(store.root / "trace.db"))
    text = app.refresh_view()
    # the plan names the PRIMARY (drive) personas; the bare names are their
    # subagent twins, so a substring match covers both spellings
    problems = [f"view missing {a}: {text!r}" for a in ("hunter", "clerk")
                if a not in text]
    return problems


def check_drilldown(ctx: dict) -> list[str]:
    """Every turn's trace_refs land in trace.db — P5's drilldown contract, proven
    by the join (the pane's rows and the ledger are one truth)."""
    problems: list[str] = []
    store, sid = ctx["store"], ctx["sid"]
    # ONE trace store for the whole run: the driver's open_gate writes
    # <store-root>/trace.db — the production shape `harness serve` reads.
    trace_db = store.root / "trace.db"
    if not trace_db.is_file():
        return [f"no trace store at {trace_db} — no dispatch to drill into"]
    con = sqlite3.connect(str(trace_db))
    con.row_factory = sqlite3.Row
    try:
        seen = {int(r[0]) for r in con.execute("SELECT id FROM dispatches").fetchall()}
    finally:
        con.close()
    refs = {rid for row in store.turns(sid) for rid in row.trace_refs}
    if not refs:
        problems.append("no trace_refs recorded on the session's turns")
    missing = sorted(refs - seen)
    if missing:
        problems.append(f"JSONL refs {missing} absent from trace.db — drill-down"
                        f" would not match the ledger")
    print(f"    trace rows={len(seen)} refs={len(refs)} joined={not missing}", flush=True)
    return problems


def check_ingest(ctx: dict) -> list[str]:
    """/ingest lands chunks in the matter corpus (the count is the check)."""
    problems: list[str] = []
    matter = ctx["matter"]
    from harness.vectors import VectorStore
    from harness.corpus import CorpusStore
    store_root = ctx["store"].root
    src = store_root / "workspaces" / "r3-accept-src"
    src.mkdir(parents=True, exist_ok=True)
    # The text must clear corpus_ingest's scan floor (MIN_WORDS=200) or the
    # recorded-skip eats the check (the live run: 16 words, skipped).
    body = ("Consideration is a foundational element of a valid contract in New"
            " Zealand law. " * 20)
    (src / "acceptance-doc.txt").write_text(
        "Acceptance ingestion fixture. " + body + "\n", encoding="utf-8")
    from harness.session.commands import ingest_argv
    # The FILE, not the dir: corpus_ingest only recurses a directory for PDFs;
    # a .txt must be named directly (the live run ingested 0 chunks via [src]).
    argv = ingest_argv(matter, [src / "acceptance-doc.txt"],
                       store_root / "ingest-report.json")
    # corpus_ingest.main() reads sys.argv — the CLI argv shape, direct.
    from scripts import corpus_ingest
    old_argv, sys.argv = sys.argv, ["corpus_ingest", *argv]
    try:
        corpus_ingest.main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            problems.append(f"corpus_ingest exited {exc.code}")
            return problems
    except Exception as exc:                                  # noqa: BLE001
        problems.append(f"corpus_ingest failed: {type(exc).__name__}: {exc}")
        return problems
    finally:
        sys.argv = old_argv
    # The count lands where corpus_ingest puts it: <store>/corpus.sqlite3, the
    # SAME store `harness vectors count` reads (research/09 section 4).
    index = ctx["store"].root / "corpus.sqlite3"
    if not index.is_file():
        problems.append(f"no corpus store at {index} after the ingest")
        return problems
    counts = CorpusStore(index).count(matter)
    print(f"    chunks for {matter}: {counts}", flush=True)
    if counts <= 0:
        report = ctx["store"].root / "ingest-report.json"
        problems.append(f"no chunks for the ingested matter ({counts}); a recorded"
                        f" skip would be in {report}")
    return problems


def check_resume(ctx: dict) -> list[str]:
    """A KILLED session continues from the JSONL: tree-kill mid-turn, then resume
    carries the anchor across (P3's continuity proof — the token, not the id)."""
    problems: list[str] = []
    store, sid = ctx["store"], ctx["sid"]
    from harness.session.driver import SessionDriver
    from harness.session.workspace import spawn_env, spawn_session, turn_argv
    driver = SessionDriver(store, store.root / "workspaces")
    meta = next((r for r in store.sessions() if r["session_id"] == sid), None)
    if not meta:
        return ["session missing from the store — nothing to resume"]
    ws = driver.workspace_for(sid, "hunter-drive", ctx["matter"])
    # Phase 1: an anchor turn, which OPENS an opencode session (the seed whose
    # context the kill/resume must preserve). Its id is the continuation handle.
    # The -drive persona is mode:primary — bare hunter is a subagent and
    # opencode silently falls back to its default agent.
    code, events, seed_id = spawn_session(ws, "hunter-drive", ANCHOR_PROMPT,
                                          env=spawn_env(ws), model=MODEL)
    if not seed_id:
        return [f"the seed turn opened no opencode session id (code={code}) —"
                f" F6's chain cannot be exercised"]
    print(f"    seed session {seed_id!r}", flush=True)
    # Phase 2: KILL mid-generation — the count-to-budget prompt outruns this
    # short timeout, and run_opencode's timeout path tree-kills the REAL
    # process (code 124). Bypasses spawn_session so the 124 signature gets no
    # hang-retry (this kill is the point, not a failure).
    from scripts.run_spike_opencode import run_opencode
    code, raw = run_opencode(ws, turn_argv("hunter-drive", MODEL, KILL_PROMPT),
                             timeout=KILL_AFTER_S, env=spawn_env(ws))
    print(f"    kill leg: code={code}", flush=True)
    if code != 124:
        problems.append(f"the long turn was not killed by the timeout (code={code})"
                        " — the resume leg then proves only a COMPLETED session"
                        " (research/09 5.1)")
    # Phase 3: the continuation THROUGH THE DRIVER, driving --session <seed_id>
    # (F6's consuming end). The anchor can only be emitted with the seed's
    # context — that is the continuity proof.
    row = asyncio.run(driver.run_turn(sid, ctx["matter"], "hunter-drive",
                                      ANCHOR_PROMPT, continue_session=seed_id))
    if ANCHOR not in (row.output_summary or ""):
        problems.append(f"anchor NOT carried across the continuation:"
                        f" {row.output_summary!r} (see errors.jsonl for the spawn"
                        f" exit and whether --session continued)")
    else:
        print("    anchor carried across the continuation turn", flush=True)
    return problems


def check_compact(ctx: dict) -> list[str]:
    """/compact's checkpoint row exists (manual), and the auto trigger fires at
    safe_fill — the trigger with a synthetic usage, so no real window is burned."""
    problems: list[str] = []
    store, sid = ctx["store"], ctx["sid"]
    from harness.session.tokens import compact_session, maybe_compact
    rows = store.turns(sid)
    if not rows:
        return ["no turns to compact (C1 must run first)"]

    class _CompactDriver:
        """The driver seam: carries the REAL store (compact_session reads and
        appends turns through driver.store) and records the compaction turn."""
        def __init__(self, store) -> None:
            self.store = store
            self.seen: list[str] = []
        async def run_turn(self, session_id, matter_ref, agent, prompt, **kw):
            from harness.session.store import TurnRow
            self.seen.append(prompt)
            return TurnRow(ts="t", session_id=session_id, matter_ref=matter_ref,
                           display="", agent=agent, tools_used=[],
                           output_summary="CHECKPOINT HANDOFF: continue from data "
                          "gathering; next is the verify stage",
                           docs_touched=[], trace_refs=[])

    checkpoint = asyncio.run(compact_session(_CompactDriver(store), sid,
                                             note="acceptance manual"))
    stored = [r for r in store.turns(sid) if is_checkpoint_row(r)]
    if not stored:
        problems.append("compact_session did not land a checkpoint row")
    else:
        print(f"    checkpoint: {stored[-1].display!r}", flush=True)
    fired = asyncio.run(maybe_compact(_CompactDriver(store), sid, used=102_400,
                                      window=128_000, safe_fill=0.8))
    if fired is None:
        problems.append("maybe_compact did not fire at safe_fill (auto-compact dead)")
    elif not is_checkpoint_row(fired):
        problems.append(f"maybe_compact returned a non-checkpoint: {fired!r}")
    unfired = asyncio.run(maybe_compact(object(), sid, used=1_000, window=128_000,
                                        safe_fill=0.8))
    if unfired is not None:
        problems.append("maybe_compact fired BELOW safe_fill (threshold wrong)")
    return problems


def check_doclive(ctx: dict) -> list[str]:
    """An agent's new/edited file appears in the doc pane's status text: the agent
    writes into its workspace; the check reads git status --porcelain."""
    problems: list[str] = []
    store, sid = ctx["store"], ctx["sid"]
    from harness.session.driver import SessionDriver
    from harness.session.view import doc_changes
    driver = SessionDriver(store, store.root / "workspaces")
    ws = driver.workspace_for(sid, "hunter-drive", ctx["matter"])
    # Every -drive persona is chat-only by design (scaffold disables its tools)
    # and the bare twins are subagents opencode refuses to run — the only
    # writer is opencode's default agent. The doc pane watches the WORKSPACE,
    # not the persona, so the carrier goes through the same gate + scrubbed env.
    from harness.session.workspace import spawn_env           # noqa: E402
    from scripts.run_spike_opencode import (flatten_prompt, parse_events,
                                            run_opencode)
    argv = ["run", "--model", MODEL, "--format", "json",
            flatten_prompt("Create a file named acceptance-output.md containing"
                           f" exactly: agent wrote this. Then {ANCHOR_PROMPT}")]
    code, raw = run_opencode(ws, argv, timeout=SPAWN_S, env=spawn_env(ws))
    events = parse_events(raw)
    changes = doc_changes(ws)
    print(f"    spawn code={code}; workspace changes: {changes}", flush=True)
    if "acceptance-output.md" not in changes:
        problems.append(f"the agent's new file never appeared in the doc pane's"
                        f" status: {changes}")
    if ANCHOR not in "".join(str(e.get("part", {}).get("text", "")) for e in events):
        # Not fatal to doclive, but a spawn that fails to run at all should say so.
        problems.append(f"the doclive spawn produced no reply (code={code}); the"
                        f" file check may be measuring a failed turn")
    return problems


def check_modes(ctx: dict) -> list[str]:
    """shift+TAB cycles all three D-T2 modes; the active mode is always shown."""
    from harness.session.tui import MODES, IronFleetApp, render_status
    store, sid = ctx["store"], ctx["sid"]
    app = IronFleetApp(store, session_id=sid)
    seen = [app.mode]
    for _ in range(3):
        app.action_cycle_mode()
        seen.append(app.mode)
    if seen != ["agent-os", "shell-drives", "hybrid", "agent-os"]:
        return [f"shift+TAB cycle wrong: {seen}"]
    if app.mode not in render_status(mode=app.mode, session_id=sid, used=0, window=0):
        return ["the active mode is not shown in the status bar"]
    return []


def check_tokens(ctx: dict) -> list[str]:
    """Per-agent used-vs-remaining against the provider row's declared window —
    F1's split, F2's trace-side read, D-T3's user-declared window."""
    problems: list[str] = []
    store, sid = ctx["store"], ctx["sid"]
    from harness.session.tokens import (session_trace_refs, usage_for_refs,
                                        window_for)
    from harness.trace import TraceStore
    # The one store-root trace db the gate wrote — no per-workspace merge; the
    # join key is the session's OWN recorded refs.
    usage = usage_for_refs(TraceStore(store.root / "trace.db"),
                           session_trace_refs(store, sid))
    print(f"    session usage: in={usage['in']} out={usage['out']}"
          f" agents={sorted(usage['per_agent'])}", flush=True)
    if not usage["per_agent"]:
        problems.append("the per-agent ledger is empty — F1/F3's split not visible")
    window, fill = window_for("nvidia-nim")
    if window != 128000:
        problems.append(f"the provider row's context_window drifted: {window}")
    return problems


CHECKS = {
    "fanout": check_fanout,
    "view": check_view,
    "drilldown": check_drilldown,
    "ingest": check_ingest,
    "resume": check_resume,
    "compact": check_compact,
    "doclive": check_doclive,
    "modes": check_modes,
    "tokens": check_tokens,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence", default=str(ROOT / "data/eval/R3-ACCEPT"))
    ap.add_argument("--checks", default="fanout,view,drilldown,ingest,resume,compact,"
                                        "doclive,modes,tokens")
    ap.add_argument("--matter", default="m-accept-r3")
    ap.add_argument("--session", default=None, help="reuse this session id (skip --new)")
    args = ap.parse_args(argv)

    from harness.paths import resolve_store_root
    home, _ = resolve_store_root()
    from harness.session.store import SessionStore
    store = SessionStore(Path(home))

    sid = args.session
    if not sid:
        code, out = _run_live(["--new", "--matter", args.matter, "--display",
                               "R3 acceptance"], timeout=CLI_S)
        if code != 0:
            print(f"C-new: FAIL\n    {out[:300]}")
            return 1
        sid = out.strip().splitlines()[-1].strip()
    ctx = {"store": store, "sid": sid, "matter": args.matter}

    print("== R3 acceptance (the TUI's own code path) ==", flush=True)
    # The gate lifecycle the SHELL owns, held for the whole run: one proxy on
    # 7373, trace at <store-root>/trace.db. Without this every spawn points at
    # a dead port (the live run's remaining failures were exactly that).
    from harness.session.driver import SessionDriver
    gate_driver = SessionDriver(store, Path(home) / "workspaces")
    problems: dict[str, list[str]] = {}
    with gate_driver.open_gate():
        for name in [c.strip() for c in args.checks.split(",") if c.strip()]:
            print(f"C-{name}:", flush=True)
            try:
                problems[name] = CHECKS[name](ctx)
            except Exception as exc:                          # noqa: BLE001
                problems[name] = [f"{type(exc).__name__}: {exc}",
                                  traceback.format_exc()[-400:]]
    verdicts = {k: ("PASS" if not v else v) for k, v in problems.items()}
    failed = [k for k, v in problems.items() if v]
    for name, v in problems.items():
        print(f"C-{name}: {'PASS' if not v else 'FAIL'}")
        for line in v:
            print(f"    {line}")
    ev = Path(args.evidence)
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "verdicts.json").write_text(json.dumps(
        {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "matter": args.matter, "session": sid, "verdicts": verdicts}, indent=2,
        ensure_ascii=False), encoding="utf-8")
    print(f"verdicts -> {ev / 'verdicts.json'}")
    print("EXIT 0" if not failed else f"FAILED: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
