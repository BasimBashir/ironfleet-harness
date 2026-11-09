# scripts/accept_m8.py — M8 acceptance: the §6 self-rep journey (steps 1–10) on harbour-freight
# then the 06 Phase 6 firm loop, in Chromium against a live serve on a scratch store, with one
# screenshot per step to data/eval/M8-JOURNEY-<date>/ and a REPORT.md beside them.
# The journey itself is tests/test_web_e2e.py::journey (loaded by FILE PATH — a site-packages
# `tests` package shadows the namespace one, so never `-m tests.x`).
#
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/accept_m8.py [--store NEW_DIR]
#   --store keeps the journey's store (a fresh, empty dir) so `scripts/dev_m8.py --store NEW_DIR`
#   can serve the walked-through case afterwards — the D-5 sessions' prepared case (doc 13);
#   sign in as operator / e2e-operator-pass.
# Exit 0 = journey passed, 1 = an assertion failed, 2 = prerequisite missing (named).
from __future__ import annotations

import importlib.util
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", help="keep the store here (a new or empty directory)")
    args = ap.parse_args(argv)
    if args.store and Path(args.store).exists() and any(Path(args.store).iterdir()):
        print(f"accept_m8: --store {args.store} is not empty (the journey seeds a fresh operator)")
        return 2
    spec = importlib.util.spec_from_file_location("m8_e2e", CORE / "tests" / "test_web_e2e.py")
    e2e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2e)
    reason = e2e.skip_reason()
    if reason:
        print(f"accept_m8: PREREQUISITE MISSING - {reason}")
        return 2
    out = CORE / "data" / "eval" / f"M8-JOURNEY-{date.today().isoformat()}"
    out.mkdir(parents=True, exist_ok=True)
    shots: list[str] = []
    root = Path(args.store) if args.store else Path(tempfile.mkdtemp(prefix="accept_m8_"))
    root.mkdir(parents=True, exist_ok=True)
    live = e2e.Live(root)
    from playwright.sync_api import sync_playwright
    failure = None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1366, "height": 900})

            def shot(name):
                pg.screenshot(path=str(out / f"{name}.png"), full_page=True)
                shots.append(name)
                print(f"  ok: {name}")
            try:
                ids = e2e.journey(live, pg, shot)
            except Exception:
                failure = traceback.format_exc()
                pg.screenshot(path=str(out / "FAILED.png"), full_page=True)
            b.close()
    finally:
        live.stop()

    verdict = "FAIL" if failure else "PASS"
    lines = [f"# M8 journey acceptance — {date.today().isoformat()}: {verdict}", "",
             "Self-rep §6 steps 1–10 on harbour-freight, then the 06 Phase 6 firm loop, in "
             "headless Chromium against `create_app(worker=\"demo\")` on a scratch store. The user "
             "acts only in the browser; the orchestrator's writes (stage moves, plan versions, "
             "predictions, outcomes, deadlines) are a labelled stand-in (tests/test_web_e2e.py).",
             "", "## Screens", ""] + [f"- `{s}.png`" for s in shots]
    if failure:
        lines += ["", "## Failure", "", "```text", failure.strip(), "```"]
    else:
        lines += ["", f"Matters: self-rep `{ids['self_rep_matter']}`, firm `{ids['firm_matter']}`."]
    lines += ["", "## Known gaps (not built in M8)", "",
              "- Lawyer-now is a UI block only — no server-side gate on a flagged self-rep matter.",
              "- ReviewRequired → Completed needs a human sign-off with no API route; the firm loop "
              "ends at Review required → Archived.",
              "- No assessment screen: step 2 shows the stage, not the win-assessment content.",
              "- Mock hearing starts a run; the text rehearsal Q&A resource is not in the API."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\naccept_m8: {verdict} ({len(shots)} screenshots) -> {out}")
    if failure:
        print(failure)
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
