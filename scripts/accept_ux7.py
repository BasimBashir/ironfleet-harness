# scripts/accept_ux7.py — UX-7 acceptance driver (NEXT_STEPS §9B.7): the primary journey in
# Chromium on a seeded SYNTHETIC scratch store, then the principal screens at 1440 × 900 in both
# themes and the Chambers token check, into data/eval/UX-7-<date>/ with a REPORT-driver.md.
# The journey, seed and capture live in tests/test_web_ux7_acceptance.py (loaded by FILE PATH —
# a site-packages `tests` package shadows ours, so never `-m tests.x`).
#
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/accept_ux7.py
# Exit 0 = journey + token check passed, 1 = an assertion failed, 2 = prerequisite missing (named).
from __future__ import annotations

import importlib.util
import sys
import tempfile
import traceback
from datetime import date
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))


def main() -> int:
    spec = importlib.util.spec_from_file_location("ux7_accept", CORE / "tests" / "test_web_ux7_acceptance.py")
    ux7 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ux7)
    reason = ux7.e2e.skip_reason()
    if reason:
        print(f"accept_ux7: PREREQUISITE MISSING - {reason}")
        return 2
    out = CORE / "data" / "eval" / f"UX-7-{date.today().isoformat()}"
    out.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="accept_ux7_")) / "store"
    root.mkdir()
    live, con, ids = ux7.build_world(root)
    shots: list[str] = []
    failure, drift = None, []
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_context(viewport={"width": 1440, "height": 900}).new_page()

            def shot(name):
                pg.screenshot(path=str(out / f"{name}.png"), full_page=True)
                shots.append(name)
                print(f"  ok: {name}")
            try:
                ux7.journey(live, ids, pg, shot)
                ux7.capture(live, ids, pg, shot)
                drift = ux7.token_drift(pg)
            except Exception:
                failure = traceback.format_exc()
                pg.screenshot(path=str(out / "FAILED.png"), full_page=True)
            b.close()
    finally:
        con.close()
        live.stop()
    verdict = "FAIL" if failure or drift else "PASS"
    lines = [f"# UX-7 acceptance driver — {date.today().isoformat()}: {verdict}", "",
             "Primary journey (sign in → matter → next action → run → progress → agent → stage events → "
             "cited passage → back to run and matter) in headless Chromium against `create_app` (no worker) "
             "on a seeded synthetic scratch store, then the principal screens at 1440 × 900, light and dark.",
             "", f"Matter `{ids['m1']}`, waiting run `{ids['runs']['main']}`, document `{ids['doc']}`.",
             "", "## Chambers token check", "",
             "Every `--token` in design/system/tokens.css resolves unchanged on the app, both themes: "
             + ("PASS." if not drift else "DRIFT:\n\n" + "\n".join(f"- {d}" for d in drift)),
             "", "## Screens", ""] + [f"- `{s}.png`" for s in shots]
    if failure:
        lines += ["", "## Failure", "", "```text", failure.strip(), "```"]
    (out / "REPORT-driver.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\naccept_ux7: {verdict} ({len(shots)} screenshots) -> {out}")
    if failure:
        print(failure)
    return 1 if failure or drift else 0


if __name__ == "__main__":
    sys.exit(main())
