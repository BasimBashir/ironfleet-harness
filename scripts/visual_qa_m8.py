# scripts/visual_qa_m8.py — M8 gate D-7: every built screen captured next to the picked mockup
# (design/mockups/b-chambers.html, direction B + C's meters) or, where B has no panel, next to the
# design-system gallery. Output: data/eval/M8-VISUAL-QA/{*.png, index.html}; the deltas are read by
# eye and recorded in that folder's REPORT.md (written by hand, not by this script).
# Data: the T8 harbour-freight journey + the D-6 audit's seeding (tests/*.py, loaded by file path).
#
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/visual_qa_m8.py
# Exit 0 = captured, 2 = prerequisite missing (named).
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))
OUT = CORE / "data" / "eval" / "M8-VISUAL-QA"
MOCK = (CORE / "design" / "mockups" / "b-chambers.html").as_uri()
GALLERY = (CORE / "design" / "system" / "gallery.html").as_uri()


def _load(name):
    spec = importlib.util.spec_from_file_location(f"m8_{name}", CORE / "tests" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    a11y = _load("test_web_a11y")
    e2e = a11y.e2e
    reason = e2e.skip_reason()
    if reason:
        print(f"visual_qa_m8: PREREQUISITE MISSING - {reason}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    live = e2e.Live(Path(tempfile.mkdtemp(prefix="visual_qa_m8_")))
    from playwright.sync_api import sync_playwright
    pairs, solos = [], []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1366, "height": 900})
            ids = a11y.seed_and_journey(live, pg)
            sm = ids["self_rep_matter"]
            mock = b.new_page(viewport={"width": 1366, "height": 900})
            e2e.System(live, sm).next_action(  # so N2's next-action card is compared, not its empty state
                "Send the enforcement application for the $26,000 balance",
                "leave to enforce was granted at the last hearing")

            def ours(name, mode, theme, h):
                a11y.set_prefs(pg, mode, theme)
                pg.goto(f"{live.base}/{h}")
                pg.reload()
                pg.wait_for_selector("main h1", timeout=15000)
                pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')")
                pg.wait_for_timeout(300)
                pg.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

            # screens mockup B draws: (name, our mode, our hash, mockup panel, lawyer banner)
            for name, mode, h, panel, lawyer in (
                    ("board", "firm", "#/board", "s2", "off"),
                    ("case-home", "self-rep", f"#/case/{sm}/home", "n2", "on"),
                    ("debrief", "self-rep", f"#/case/{sm}/debrief", "n7", "off")):
                for theme in ("light", "dark"):
                    ours(f"{name}-{theme}-built", mode, theme, h)
                    mock.goto(f"{MOCK}#{panel}")
                    mock.reload()  # a hash-only goto keeps the old panel; the mockup reads the hash on load
                    mock.evaluate("([m, t, l]) => { const h = document.documentElement;"
                                  " h.dataset.mode = m; h.dataset.theme = t; h.dataset.lawyer = l; }",
                                  [mode, theme, lawyer])
                    mock.screenshot(path=str(OUT / f"{name}-{theme}-mockup.png"), full_page=True)
                    pairs.append((f"{name} · {theme}", f"{name}-{theme}-built.png",
                                  f"{name}-{theme}-mockup.png"))
            # screens B has no panel for: compared to the design-system gallery
            for label, mode, h in a11y.screens(ids):
                if label in ("board", "N home", "N debrief", "not found"):
                    continue
                name = label.replace(" ", "-")
                ours(f"{name}-light-built", mode, "light", h)
                solos.append((label, f"{name}-light-built.png"))
            mock.goto(GALLERY)
            mock.screenshot(path=str(OUT / "gallery-light.png"), full_page=True)
            b.close()
    finally:
        live.stop()

    fig = lambda cap, src: f'<figure><figcaption>{cap}</figcaption><img src="{src}" alt="{cap}"></figure>'  # noqa: E731
    html = ["<!doctype html><meta charset=utf-8><title>M8 visual QA (D-7)</title>",
            "<style>body{font:14px system-ui;margin:16px}.pair{display:grid;grid-template-columns:1fr 1fr;"
            "gap:12px;margin-bottom:28px}img{width:100%;border:1px solid #ccc}figure{margin:0}</style>",
            "<h1>M8 visual QA — built screen (left) vs mockup B (right)</h1><p>Deltas: REPORT.md.</p>"]
    for cap, built, mk in pairs:
        html.append(f'<h2>{cap}</h2><div class="pair">{fig("built", built)}{fig("mockup B", mk)}</div>')
    html.append("<h2>Screens mockup B has no panel for — vs the design-system gallery</h2>")
    for cap, built in solos:
        html.append(f'<div class="pair">{fig(cap, built)}{fig("design-system gallery", "gallery-light.png")}</div>')
    (OUT / "index.html").write_text("\n".join(html), encoding="utf-8")
    print(f"visual_qa_m8: {len(pairs)} mockup pairs + {len(solos)} gallery comparisons -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
