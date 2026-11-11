# scripts/check_ab_browser.py — A+B (2026-11-11) browser check, visual_qa_m10 pattern.
# B: fresh store, admin/admin forced change, public signup → admin approves/rejects →
#    approved signs in as reader, rejected can't, reader is gated off user.admin.
# A: run drawer — only the current stage open by default; Expand all / Collapse all.
# Usage (from harness-core):  .venv/Scripts/python.exe scripts/check_ab_browser.py
# Exit 0 = check passed, 2 = prerequisite missing (named).
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE / "src"))

PW_ADMIN = "stag-secure-9"      # what admin changes the default to
PW_NEW = "pw-newguy-1"


def _wait(fn, what, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise AssertionError(f"never saw {what}")


def main() -> int:
    import importlib.util
    spec = importlib.util.spec_from_file_location("e2e", CORE / "tests" / "test_web_e2e.py")
    e2e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2e)
    reason = e2e.skip_reason()
    if reason:
        print(f"check_ab_browser: PREREQUISITE MISSING - {reason}")
        return 2

    from harness.service import auth
    auth._ITER = 1000                       # pbkdf2 speed, checks only
    root = Path(tempfile.mkdtemp(prefix="check_ab_")) / "store"
    root.mkdir()
    from harness.service import system
    con = system.open_db(root)              # B: the fresh-store seed is admin/admin, forced change
    auth.create_user(con, "admin", "admin", role_id="admin", must_change_password=True)
    con.close()
    live = e2e.Live(root)
    from playwright.sync_api import sync_playwright
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1366, "height": 900})
                pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errors.append(str(e)))
                tasks_status: list[str] = []
                pg.on("response", lambda r: tasks_status.append(f"{r.status} {r.url.split('/api/v1')[-1]}")
                      if "/tasks" in r.url else None)
                B = live.base

                def sign_in(u, pw_):
                    pg.goto(f"{B}/#/")     # same-URL goto is same-document: no reload
                    if pg.locator("button:has-text('Back to sign in')").count():
                        pg.click("button:has-text('Back to sign in')")
                    pg.fill("#u", u)
                    pg.fill("#p", pw_)
                    pg.click("button:has-text('Sign in')")

                # --- B: public signup -------------------------------------------------
                pg.goto(f"{B}/#/")
                pg.click("button:has-text('Request an account')")
                pg.fill("#u", "newguy")
                pg.fill("#p", PW_NEW)
                pg.click("button:has-text('Send request')")
                pg.wait_for_selector("text=An administrator must approve it")
                pg.click("button:has-text('Back to sign in')")
                pg.click("button:has-text('Request an account')")
                pg.fill("#u", "ghost")
                pg.fill("#p", PW_NEW)
                pg.click("button:has-text('Send request')")
                pg.wait_for_selector("text=An administrator must approve it")

                # --- B: default admin/admin forces a password change -------------------
                sign_in("admin", "admin")
                pg.wait_for_selector("text=Set a new password")
                pg.fill("#cp1", PW_ADMIN)
                pg.fill("#cp2", PW_ADMIN)
                pg.click("button:has-text('Save and continue')")
                pg.wait_for_selector("button:has-text('Sign out')")

                # --- B: admin approves newguy, rejects ghost ----------------------------
                pg.goto(f"{B}/#/users")
                row_new = pg.locator("tr", has_text="newguy")
                _wait(lambda: row_new.inner_text().find("Pending") >= 0, "newguy Pending")
                row_new.locator("button:has-text('Approve')").click()
                _wait(lambda: row_new.inner_text().find("Active") >= 0, "newguy Active")
                row_ghost = pg.locator("tr", has_text="ghost")
                row_ghost.locator("button:has-text('Reject')").click()
                _wait(lambda: row_ghost.inner_text().find("Rejected") >= 0, "ghost Rejected")

                # --- B: approved signs in as reader; reader gated off user.admin -------
                pg.click("button:has-text('Sign out')")
                sign_in("newguy", PW_NEW)
                pg.wait_for_selector("button:has-text('Sign out')")
                pg.goto(f"{B}/#/users")
                pg.wait_for_selector("text=requires the user.admin permission")

                # --- B: rejected can't sign in -----------------------------------------
                pg.click("button:has-text('Sign out')")
                sign_in("ghost", PW_NEW)
                pg.wait_for_selector("[role=alert]")

                # --- A: the run drawer (a follow-up run parks at the moot approval) ---
                ids = e2e.journey(live, pg)      # signs in as operator, drives §6 + firm loop
                fm = ids["firm_matter"]
                cid = live.api("POST", f"/matters/{fm}/conversations",
                               {"title": "Drawer check"})["conversation_id"]
                live.api("POST", f"/conversations/{cid}/messages",
                         {"text": "follow-up: check the enforcement steps"})
                _wait(lambda: (rs := live.api("GET", f"/matters/{fm}/runs")) and
                      rs[0]["state"] == "waiting_human", "the follow-up run to park", 60)
                rid = live.api("GET", f"/matters/{fm}/runs")[0]["execution_id"]
                # the drawer is the self-rep run page (firm mode renders the swarm lanes instead)
                pg.evaluate("localStorage.setItem('ironfleet.mode', 'self-rep')")
                pg.goto(f"{B}/#/runs/{rid}")
                pg.reload()      # usePref reads localStorage only at boot
                drawer = pg.locator(f"aside[aria-label='Run {rid}']")
                try:
                    _wait(lambda: drawer.locator("details").count() > 0, "stages to render")
                except AssertionError:
                    shot = CORE / "data" / "eval" / "check_ab_debug.png"
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    pg.screenshot(path=str(shot))
                    print(f"DEBUG rid={rid} asides={pg.locator('aside').count()} "
                          f"mode={pg.evaluate('localStorage.getItem(\"ironfleet.mode\")')} "
                          f"hash={pg.evaluate('location.hash')} "
                          f"tasks_status={tasks_status[-6:]} shot={shot.name}")
                    for i in range(pg.locator("aside").count()):
                        print(f"  aside[{i}]: {pg.locator('aside').nth(i).get_attribute('aria-label')}")
                    raise
                total = drawer.locator("details").count()
                opened = lambda: drawer.locator("details[open]").count()
                _wait(lambda: opened() == 1, "exactly one stage open by default")
                pg.click("button:has-text('Expand all')")
                _wait(lambda: opened() == total, f"Expand all opens all {total}")
                pg.click("button:has-text('Collapse all')")
                _wait(lambda: opened() == 0, "Collapse all closes all")
                state = live.api("GET", f"/executions/{rid}")["state"]
                print(f"check_ab_browser: PASS — B signup/approve/reject/forced-change + "
                      f"A drawer ({total} stages, run {state}, 1 open by default)")
            finally:
                b.close()
    finally:
        live.stop()
    if errors:
        print("console/page errors:")
        for e in errors[:10]:
            print("  " + e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
