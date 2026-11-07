# scripts/accept_m5.py — M5 acceptance: harbour-freight through TWO court rounds
# on the PLATFORM lifecycle (harness.lifecycle over a temp platform.db), with the
# plugin grader's exact M5 assertions (ironfleet-legal/tests/grade_dummy_case.py).
# Fixtures are read by path from ironfleet-legal/dummy-case-harbour-freight/ —
# never copied, never ingested into any corpus.
#
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/accept_m5.py
# Exit 0 = every assertion passed, 1 = something failed.
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))

from harness.lifecycle import deadlines, debrief, dossier, restrategy, statemachine  # noqa: E402
from harness.module_e.vendored.court_calendar import court_filing_deadline  # noqa: E402
from harness.workflow.db import connect  # noqa: E402

PLUGIN = CORE.parent / "ironfleet-legal"
ROUNDS = PLUGIN / "dummy-case-harbour-freight" / "court-rounds"
MATTER = "harbour-freight"

failures: list[str] = []


def want(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)
        print(f"  FAIL: {msg}")
    else:
        print(f"  ok: {msg}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="accept_m5_"))
    con = connect(tmp / "platform.db")

    # the two synthetic minute fixtures carry the ground truths the loop is graded on
    m1 = (ROUNDS / "minute-round-1.md").read_text(encoding="utf-8")
    m2 = (ROUNDS / "minute-round-2.md").read_text(encoding="utf-8")
    want("20 working days" in m1, "fixture round 1 carries '20 working days'")
    want("$100,000" in m2 and "$26,000" in m2 and "10 February 2027" in m2,
         "fixture round 2 carries '$100,000' / '$26,000' / '10 February 2027'")

    # walk the state machine up to COURT, like the operator would
    statemachine.transition(con, MATTER, "INTAKE")
    for s in ("ASSESS", "STRATEGY", "PRE_ACTION", "DRAFT", "MOOT", "APPROVE",
              "FILE_SERVE", "AWAIT", "RESPOND", "HEARING_PREP", "COURT"):
        statemachine.transition(con, MATTER, s)

    # seed: opening strategy v1 + two predictions to be diffed against round 1
    dossier.append(con, MATTER, "strategy", {
        "version": 1, "file": "strategy-v1.md",
        "why_changed": "opening strategy after the statement of claim",
        "next_actions": ["prove the debt, seek summary judgment"]})
    dossier.append(con, MATTER, "predictions", {
        "prediction_id": "p1", "strategy_version": 1,
        "claim": "The court orders the judgment sum payable IMMEDIATELY on entry."})
    dossier.append(con, MATTER, "predictions", {
        "prediction_id": "p2", "strategy_version": 1,
        "claim": "Judgment is entered for the claimant (Powell Builders)."})

    # round 1 (2026-11-05): judgment yes, immediacy no
    d1 = debrief.ingest_court_event(con, MATTER, {
        "event_type": "minute", "date": "2026-11-05",
        "judge_said": "judgment entered for the plaintiff in $126,000; immediate "
                      "enforcement REFUSED; time to pay: 20 working days",
        "orders": ["judgment for the plaintiff in the sum of $126,000",
                   "payment within 20 working days of the date of this minute",
                   "costs reserved; memoranda within 10 working days if not agreed"],
        "source_file": "court-rounds/minute-round-1.md"})
    want(d1["open_count"] == 2, f"round-1 diff carries both seeded predictions "
                                f"(open_count={d1['open_count']})")
    want([e["prediction_id"] for e in d1["diff"]] == ["p1", "p2"],
         "round-1 diff ids are [p1, p2]")
    want(statemachine.state(con, MATTER) == "RE_STRATEGY",
         "after round 1 the case sits in RE_STRATEGY")

    # verdicts recorded as DATA (match is judgement, never computed)
    debrief.record_outcome(con, MATTER, "p1", match=False,
                           actual="payment within 20 working days, not immediately",
                           court_date="2026-11-05")
    debrief.record_outcome(con, MATTER, "p2", match=True,
                           actual="judgment entered for the plaintiff",
                           court_date="2026-11-05")

    # strategy v2 + one new prediction
    restrategy.cut_strategy(con, MATTER, "strategy-v2.md",
                            "court refused immediate enforcement; pivot to the "
                            "time-to-pay window and enforcement readiness",
                            ["watch the 20-working-day window",
                             "prepare leave-to-enforce papers"])
    dossier.append(con, MATTER, "predictions", {
        "prediction_id": "p3", "strategy_version": 2,
        "claim": "The defendant pays the full $126,000 within the 20-working-day window."})

    # deadlines kernel-computed only; a caller-supplied due is refused
    k1 = court_filing_deadline(date(2026, 11, 5), 20).isoformat()
    reg1 = deadlines.register(con, MATTER, "judgment sum payable", "2026-11-05",
                              days=20, missed_consequence="leave to enforce without "
                              "further hearing")
    want(reg1["due"] == k1, f"round-1 payment deadline equals the kernel ({k1}), "
                            f"got {reg1['due']}")
    try:
        deadlines.register(con, MATTER, "model-invented", "2026-11-05", due="2026-12-01")
        failures.append("deadlines.register ACCEPTED a caller-supplied 'due' — the "
                        "kernel-only rule is broken")
        print("  FAIL: caller-supplied 'due' was accepted")
    except RuntimeError:
        print("  ok: kernel-only refusal — caller-supplied 'due' refused")

    # round 2 (2026-12-08): part payment only — p3 pairs, and only p3. The case
    # is in RE_STRATEGY (no COURT edge from there), so the diff computes from
    # the current state, exactly as an operator re-entering a round would.
    d2 = debrief.ingest_court_event(con, MATTER, {
        "event_type": "minute", "date": "2026-12-08",
        "judge_said": "part payment $100,000 received 27 November 2026 within the "
                      "window; balance $26,000 outstanding; LEAVE TO ENFORCE granted",
        "orders": ["part payment of $100,000 recorded (received 2026-11-27)",
                   "leave to enforce granted for the outstanding balance of $26,000",
                   "costs $1,500 to the plaintiff within 10 working days",
                   "defendant evidence within 15 working days"],
        "next_date": "2027-02-10",
        "source_file": "court-rounds/minute-round-2.md"})
    want(d2["open_count"] == 1 and d2["diff"][0]["prediction_id"] == "p3",
         f"round-2 diff carries exactly p3 (got "
         f"{[e['prediction_id'] for e in d2['diff']]})")
    debrief.record_outcome(con, MATTER, "p3", match=False,
                           actual="part payment $100,000 only; $26,000 balance "
                                  "outstanding — leave to enforce granted",
                           court_date="2026-12-08")
    restrategy.cut_strategy(con, MATTER, "strategy-v3.md",
                            "defendant short-paid within the window; move to executing "
                            "the granted leave to enforce for the balance",
                            ["enforce the $26,000 balance",
                             "file evidence on the security registration"])

    # round-2 kernel deadlines (costs 10 wd, evidence 15 wd from the minute date)
    for what, days in (("costs $1,500 payable", 10),
                       ("defendant evidence filed and served", 15)):
        reg = deadlines.register(con, MATTER, what, "2026-12-08", days=days)
        want(reg["due"] == court_filing_deadline(date(2026, 12, 8), days).isoformat(),
             f"round-2 deadline '{what}' equals the kernel ({reg['due']})")

    # end-state assertions: the whole chain, one read each
    strat = dossier.read(con, MATTER, "strategy")
    want(strat["versions"] == [1, 2, 3], f"strategy chain [1,2,3] (got {strat['versions']})")
    preds = dossier.read(con, MATTER, "predictions")
    want(preds["unresolved"] == [], f"unresolved == [] (got {preds['unresolved']})")
    dl = dossier.read(con, MATTER, "deadlines")
    want(len(dl["deadlines"]) >= 3 and all(r["source"] == "kernel" for r in dl["deadlines"]),
         "every registered deadline is kernel-sourced")
    court = dossier.read(con, MATTER, "court_events")
    want(court["events"][-1]["payload"].get("next_date") == "2027-02-10",
         "minute-2 CMC date rides the last court event as next_date")
    for r in dl["deadlines"]:
        print(f"  deadline: {r['due']}  {r['what']}  [{r['source']}]")
    print(f"  state: {statemachine.state(con, MATTER)}")
    con.close()

    if failures:
        print(f"\n{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\naccept_m5: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
