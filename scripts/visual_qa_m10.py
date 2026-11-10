# scripts/visual_qa_m10.py — M10 T6: the built swarm + chat dock, users & roles and matter
# members, captured next to the picked mockups (design/mockups/m10-chat-c.html = the D-pick
# "C ops dock + A's rail cards"; b-chambers.html S4 = the swarm lanes) or, where neither has a
# panel, next to the design-system gallery. Output: data/eval/M10-VISUAL-QA/{*.png, index.html};
# deltas are read by eye. Data: the M8 journey + a11y seeding (tests/*.py, loaded by file path),
# then one chat message on the firm matter so the dock has a thread, a parked run and an approval.
#
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/visual_qa_m10.py
# Exit 0 = captured, 2 = prerequisite missing (named).
from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))
OUT = CORE / "data" / "eval" / "M10-VISUAL-QA"
DOCK = (CORE / "design" / "mockups" / "m10-chat-c.html").as_uri()
LANES = (CORE / "design" / "mockups" / "b-chambers.html").as_uri()
GALLERY = (CORE / "design" / "system" / "gallery.html").as_uri()


def _load(name):
    spec = importlib.util.spec_from_file_location(f"m10_{name}", CORE / "tests" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_state(live, rid, want, timeout=30):
    for _ in range(int(timeout / 0.25)):
        if live.api("GET", f"/executions/{rid}")["state"] == want:
            return
        time.sleep(0.25)
    raise AssertionError(f"run {rid} never reached {want}")


def main() -> int:
    a11y = _load("test_web_a11y")
    e2e = a11y.e2e
    reason = e2e.skip_reason()
    if reason:
        print(f"visual_qa_m10: PREREQUISITE MISSING - {reason}")
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    live = e2e.Live(Path(tempfile.mkdtemp(prefix="visual_qa_m10_")))
    from playwright.sync_api import sync_playwright
    pairs, solos = [], []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1366, "height": 900})
            ids = a11y.seed_and_journey(live, pg)
            fm = ids["firm_matter"]
            # a chat turn: the thread, its execution (parks at the moot approval) and the inline card
            cid = live.api("POST", f"/matters/{fm}/conversations", {"title": "Supervision"})["conversation_id"]
            rid = live.api("POST", f"/conversations/{cid}/messages",
                           {"text": "Tighten the moot bundle to the two strongest grounds"})["execution"]["execution_id"]
            apid = e2e.System(live, fm).wait_approval()[0]["approval_id"]
            _run_state(live, rid, "waiting_human")
            mock = b.new_page(viewport={"width": 1366, "height": 900})

            def ours(name, mode, theme, h, then=None):
                a11y.set_prefs(pg, mode, theme)
                pg.goto(f"{live.base}/{h}")
                pg.reload()
                pg.wait_for_selector("main h1", timeout=15000)
                pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')")
                if then:
                    then()
                pg.wait_for_timeout(300)
                pg.screenshot(path=str(OUT / f"{name}.png"), full_page=True)

            def drawer():  # open the inspection drawer on the parked stage, as the mockup shows it
                pg.locator(".card.node", has_text="⏸").first.click()
                pg.wait_for_selector("aside[aria-label='Agent inspection']")

            for theme in ("light", "dark"):
                ours(f"swarm-parked-{theme}-built", "firm", theme, f"#/runs/{rid}", drawer)
                mock.goto(DOCK)
                mock.reload()
                mock.evaluate("t => { document.body.dataset.theme = t; }", theme)  # this mockup reads body
                mock.screenshot(path=str(OUT / f"swarm-parked-{theme}-dock-mockup.png"), full_page=True)
                mock.goto(f"{LANES}#s4")
                mock.reload()  # the mockup reads the hash on load
                mock.evaluate("t => { const h = document.documentElement; h.dataset.mode = 'firm';"
                              " h.dataset.theme = t; h.dataset.lawyer = 'off'; }", theme)
                mock.screenshot(path=str(OUT / f"swarm-parked-{theme}-lanes-mockup.png"), full_page=True)
                pairs.append((f"swarm + chat dock, parked at approval · {theme}",
                              f"swarm-parked-{theme}-built.png",
                              [("mockup C dock (picked)", f"swarm-parked-{theme}-dock-mockup.png"),
                               ("mockup B S4 lanes", f"swarm-parked-{theme}-lanes-mockup.png")]))
            # decided: the run finishes and the lead's reply lands in the thread
            live.api("POST", f"/approvals/{apid}/approve", {})
            _run_state(live, rid, "completed")
            ours("swarm-completed-light-built", "firm", "light", f"#/runs/{rid}")
            pairs.append(("swarm + chat dock, completed · light", "swarm-completed-light-built.png",
                          [("mockup C dock (picked)", "swarm-parked-light-dock-mockup.png")]))
            # screens neither mockup draws: compared to the design-system gallery
            for label, mode, h in (("users & roles", "firm", "#/users"),
                                   ("workspace members", "firm", f"#/m/{fm}/overview"),
                                   ("self-rep run inspection", "self-rep", f"#/runs/{ids['run']}")):
                name = label.replace(" & ", "-").replace(" ", "-")
                ours(f"{name}-light-built", mode, "light", h)
                solos.append((label, f"{name}-light-built.png"))
            mock.goto(GALLERY)
            mock.screenshot(path=str(OUT / "gallery-light.png"), full_page=True)
            b.close()
    finally:
        live.stop()

    fig = lambda cap, src: f'<figure><figcaption>{cap}</figcaption><img src="{src}" alt="{cap}"></figure>'  # noqa: E731
    html = ["<!doctype html><meta charset=utf-8><title>M10 visual QA (T6)</title>",
            "<style>body{font:14px system-ui;margin:16px}.pair{display:grid;grid-template-columns:1fr 1fr;"
            "gap:12px;margin-bottom:28px}img{width:100%;border:1px solid #ccc}figure{margin:0}</style>",
            "<h1>M10 visual QA — built screen (left) vs the picked mockups (right)</h1>"]
    for cap, built, mocks in pairs:
        right = "".join(fig(c, s) for c, s in mocks)
        html.append(f'<h2>{cap}</h2><div class="pair">{fig("built", built)}<div>{right}</div></div>')
    html.append("<h2>Screens the mockups have no panel for — vs the design-system gallery</h2>")
    for cap, built in solos:
        html.append(f'<div class="pair">{fig(cap, built)}{fig("design-system gallery", "gallery-light.png")}</div>')
    (OUT / "index.html").write_text("\n".join(html), encoding="utf-8")
    print(f"visual_qa_m10: {len(pairs)} mockup pairs + {len(solos)} gallery comparisons -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
