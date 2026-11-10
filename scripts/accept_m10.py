# scripts/accept_m10.py — M10 acceptance (plan T7), browser E2E on the accept_m8 pattern:
# admin dispatches a firm matter → the swarm shows the live multi-stage run, states progressing on
# screen → the inspection drawer shows the meters → counsel chat: instruction → 202 → pending →
# inline approval decided → the lead's reply lands in-thread → a reader is created and added to the
# matter through the admin UI → the reader sees only that matter, no dispatch / chat / user-admin
# controls, and a direct pause attempt with the reader's own token is refused 403 server-side.
# Headless Chromium against create_app(worker="demo") on a scratch store; screenshots + REPORT.md
# to data/eval/M10-JOURNEY-<date>/. Test helpers are loaded by FILE PATH (never `-m tests.x`).
#
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/accept_m10.py [--store NEW_DIR]
# Exit 0 = journey passed, 1 = an assertion failed, 2 = prerequisite missing (named).
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))
READER, READER_PW = "rita", "reader-pass-1"
DONE = r"(\d+) of (\d+) stages complete"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"m10_{name}", CORE / "tests" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call(base, method, path, token=None, body=None):
    """(status, json) — errors are answers here, not exceptions."""
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + "/api/v1" + path, method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def journey(e2e, live, pg, shot) -> dict:
    B, notes = live.base, []
    errors: list[str] = []
    pg.on("dialog", lambda d: d.accept())  # approve confirm, cancel confirm, redirect prompt
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    main = lambda: pg.inner_text("main")  # noqa: E731

    def login(user, pw):
        pg.goto(B + "/#/")
        pg.fill("#u", user)
        pg.fill("#p", pw)
        pg.click("button[type=submit]")
        pg.wait_for_selector(".top", timeout=15000)
        if pg.get_attribute("[data-mode]", "data-mode") != "firm":
            pg.click("button.toggle:text('Self-rep mode')")
        pg.wait_for_selector("[data-mode='firm']")

    def settle(h, ready="main h1"):
        pg.goto(f"{B}/{h}")
        pg.wait_for_selector(ready, timeout=15000)
        pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')", timeout=15000)

    def new_matter(title):
        settle("#/new", "#nm-title")
        pg.fill("#nm-title", title)
        pg.click("button[type=submit]")
        pg.wait_for_selector("#ws-h", timeout=15000)
        return pg.url.split("#/m/")[1].split("/")[0]

    def stages():
        m = re.search(DONE, pg.inner_text("aside[aria-label='Run context']"))
        return int(m[1]), int(m[2])

    # 1 — admin: a matter the reader will get, and one they must never see
    login("operator", e2e.PASSWORD)
    other = new_matter("Unrelated client — reader must not see")
    fmid = new_matter("Southern Haulage v Harbour Freight (M10)")
    pg.get_by_role("link", name="Documents", exact=True).click()
    pg.set_input_files("#doc-up", [str(p) for p in e2e.DOCS])
    pg.wait_for_function("() => document.querySelectorAll("
                         "'table[aria-label=Documents] tbody tr').length === 5", timeout=15000)
    pg.get_by_role("link", name="Overview", exact=True).click()
    pg.fill("#disp-t", "recover the unpaid freight statements from Harbour Freight")
    pg.get_by_role("button", name="Dispatch", exact=True).click()
    e2e.System(live, fmid).wait_approval()           # orchestrator stand-in: the demo worker parks
    rid = live.api("GET", f"/matters/{fmid}/runs")[0]["execution_id"]

    # 2 — the swarm: parked at the approval, then decided inline and progressing on screen
    settle(f"#/runs/{rid}", ".card.node")
    pg.wait_for_selector(".card.node:has-text('⏸')", timeout=15000)
    done0, total = stages()
    assert total >= 9 and 0 < done0 < total, f"not a live multi-stage run: {done0}/{total}"
    assert re.search(rf"stage \d+ of {total}", pg.inner_text("#swarm-h + .sub")), "swarm header"
    notes.append(f"run `{rid}`: parked with {done0} of {total} stages complete")
    shot("01-swarm-parked-at-approval")

    # 3 — inspection drawer: the parked node, its goal and token meter (honest when none recorded)
    pg.locator(".card.node", has_text="⏸").first.click()
    drawer = pg.locator("aside[aria-label='Agent inspection']")
    drawer.wait_for()
    meter = drawer.locator("dd.tokens").inner_text()
    assert re.search(r"\d.* · in .* · out .* · think |none recorded for this agent", meter), meter
    assert drawer.locator("h3").inner_text().endswith(f"of {total}")
    notes.append(f"drawer meter on the parked stage: “{meter}”")
    shot("02-inspection-drawer")

    pg.click(".bottom .appr button:text('Approve')")
    pg.wait_for_function(f"() => /{total} of {total} stages complete/.test("
                         "document.querySelector(\"aside[aria-label='Run context']\").innerText)",
                         timeout=30000)                  # same page, no reload: SSE moved the lanes
    assert stages() == (total, total)
    assert pg.locator(".card.node:has-text('⏸')").count() == 0
    notes.append(f"decided inline; the lanes advanced {done0} → {total} of {total} without a reload")
    shot("03-swarm-completed-live")

    # 4 — counsel chat: instruction → 202 → pending → inline approval → the lead's reply in-thread
    text = "Tighten the moot bundle to the two strongest grounds"
    pg.fill(f"#chat-{rid}", text)
    with pg.expect_response(lambda r: r.request.method == "POST"
                            and r.url.endswith("/messages")) as resp:
        pg.click(".comp button[type=submit]")
    assert resp.value.status == 202, f"chat POST answered {resp.value.status}"
    pg.wait_for_selector(".msg .pending[role=status]", timeout=15000)
    assert text in pg.inner_text(".msgs")
    shot("04-chat-pending")
    pg.wait_for_selector(".bottom .appr button:text('Approve')", timeout=30000)
    shot("05-chat-inline-approval")
    pg.click(".bottom .appr button:text('Approve')")
    pg.wait_for_selector(".msg.lead", timeout=30000)
    lead = pg.inner_text(".msg.lead")
    m = re.search(r"Run (\S+) completed\.", lead)
    assert m and m[1] != rid, f"lead reply not for the chat's run: {lead[:200]}"
    assert pg.locator(".msg .pending").count() == 0, "message still pending after the reply"
    notes.append(f"chat run `{m[1]}` completed; lead reply landed in-thread")
    shot("06-chat-lead-reply")

    # 5 — admin UI: create the reader, add them to the one matter as reader
    settle("#/users", "#nu-name")
    pg.fill("#nu-name", READER)
    pg.fill("#nu-pw", READER_PW)
    pg.select_option("#nu-role", "reader")
    pg.click("button:text('Create user')")
    row = pg.locator("table[aria-label=Users] tbody tr", has_text=READER)
    row.wait_for(timeout=15000)
    uid = row.locator(".id").inner_text().strip()
    assert row.locator("select").input_value() == "reader"
    shot("07-users-reader-created")
    settle(f"#/m/{fmid}/overview", "#am-uid")
    pg.fill("#am-uid", uid)
    pg.select_option("#am-role", "reader")
    pg.click("button:text('Add member')")
    pg.locator("table[aria-label='Matter members'] tbody tr", has_text=READER).wait_for(timeout=15000)
    shot("08-matter-member-added")

    # 6 — the reader: only their matter, read-only everywhere, the reason visible
    pg.click("button:text('Sign out')")
    login(READER, READER_PW)
    settle("#/")
    pg.wait_for_selector(f"main :text('{fmid}'), main :text('Southern Haulage')", timeout=15000)
    assert "Unrelated client" not in main() and other not in main(), "reader sees a foreign matter"
    assert pg.locator("nav a:text('Users & roles')").count() == 0, "user-admin nav shown to reader"
    shot("09-reader-board")
    settle(f"#/m/{fmid}/overview", "#ws-h")
    for sel in ("#disp-t", "#am-uid", "button:text('Archive matter')"):
        assert pg.locator(sel).count() == 0, f"reader sees mutation control {sel}"
    shot("10-reader-workspace")
    settle(f"#/runs/{rid}", ".card.node")
    for sel in (f"#chat-{rid}", f"#inj-{rid}", "button:text('Pause')", "button:text('Cancel')",
                "button:text('Redirect')"):
        assert pg.locator(sel).count() == 0, f"reader sees run control {sel}"
    assert "Lead counsel" in pg.inner_text(".msgs"), "reader cannot read the thread"
    shot("11-reader-run-read-only")
    settle("#/users", "#users-h")
    assert "requires the user.admin permission" in main()
    for sel in ("#nu-name", "table[aria-label=Users]"):
        assert pg.locator(sel).count() == 0, f"reader sees user admin {sel}"
    shot("12-reader-users-locked")

    # 7 — server side: the reader's own token is refused, not just the buttons hidden
    st, tok = _call(B, "POST", "/auth/login", body={"username": READER, "password": READER_PW})
    assert st == 200, tok
    rt = tok["token"]
    checks = [("POST", f"/executions/{rid}/pause", 403, "permission_denied"),
              ("POST", f"/runs/{rid}/cancel", 403, "permission_denied"),
              ("GET", "/users", 403, "permission_denied"),
              ("GET", f"/matters/{other}", 404, "matter_not_found")]
    for method, path, want, code in checks:
        st, body = _call(B, method, path, rt, {} if method == "POST" else None)
        got = (body or {}).get("error", {}).get("code") if isinstance(body, dict) else None
        assert (st, got) == (want, code), f"reader {method} {path}: {st} {body}"
        notes.append(f"reader `{method} {path}` → {st} {code}")
    js = [e for e in errors if "status of 40" not in e]   # refused fetches are expected on read-only
    assert not js, f"console errors: {js[:3]}"
    return {"firm_matter": fmid, "other_matter": other, "run": rid, "reader": uid, "notes": notes}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", help="keep the store here (a new or empty directory)")
    args = ap.parse_args(argv)
    if args.store and Path(args.store).exists() and any(Path(args.store).iterdir()):
        print(f"accept_m10: --store {args.store} is not empty (the journey seeds a fresh operator)")
        return 2
    e2e = _load("test_web_e2e")
    reason = e2e.skip_reason()
    if reason:
        print(f"accept_m10: PREREQUISITE MISSING - {reason}")
        return 2
    out = CORE / "data" / "eval" / f"M10-JOURNEY-{date.today().isoformat()}"
    out.mkdir(parents=True, exist_ok=True)
    shots: list[str] = []
    root = Path(args.store) if args.store else Path(tempfile.mkdtemp(prefix="accept_m10_"))
    root.mkdir(parents=True, exist_ok=True)
    live = e2e.Live(root)
    from playwright.sync_api import sync_playwright
    failure, ids = None, {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1366, "height": 900})

            def shot(name):
                pg.screenshot(path=str(out / f"{name}.png"), full_page=True)
                shots.append(name)
                print(f"  ok: {name}")
            try:
                ids = journey(e2e, live, pg, shot)
            except Exception:
                failure = traceback.format_exc()
                pg.screenshot(path=str(out / "FAILED.png"), full_page=True)
            b.close()
    finally:
        live.stop()

    verdict = "FAIL" if failure else "PASS"
    lines = [f"# M10 acceptance — {date.today().isoformat()}: {verdict}", "",
             "Swarm + inspection, counsel chat, users/roles/membership and permission-dependent UI, "
             "in headless Chromium against `create_app(worker=\"demo\")` on a scratch store. Every "
             "user act is in the browser; waiting for the demo worker to park at its approval is the "
             "labelled orchestrator stand-in (tests/test_web_e2e.py `System`). The final 403/404 "
             "checks use the reader's own token over plain HTTP — the server refusal, not the UI.",
             "", "## Screens", ""] + [f"- `{s}.png`" for s in shots]
    if failure:
        lines += ["", "## Failure", "", "```text", failure.strip(), "```"]
    else:
        lines += ["", "## Evidence", ""] + [f"- {n}" for n in ids["notes"]]
        lines += ["", f"Matters: firm `{ids['firm_matter']}`, unrelated `{ids['other_matter']}`; "
                  f"reader `{ids['reader']}`."]
    lines += ["", "## Known gaps", "",
              "- The demo worker's pipeline has 10 stages, not 9; the swarm renders what is real.",
              "- Token meters read the real ledger; demo runs record none, shown as honest zeros.",
              "- Pause / Redirect are exercised in tests, not here: a demo run parks at its approval "
              "before a pause could land, and only an executing run pauses."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\naccept_m10: {verdict} ({len(shots)} screenshots) -> {out}")
    if failure:
        print(failure)
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
