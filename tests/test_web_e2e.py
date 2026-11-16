"""M8 T8 journey acceptance (plan §2 T8): the NEXT_STEPS §6 self-rep journey, steps
1–10, on harbour-freight in Chromium against a live serve, then the 06 Phase 6 firm loop
(create → upload → dispatch → approve → collect → complete → archive).

Two actors, kept apart on purpose:
- the USER acts only in the browser — every click/answer/upload is a UI action;
- `System` stands in for the orchestrator (no live model in M8 — the live opencode leg
  is optional, plan §3): stage moves through POST /lifecycle, and the registers that
  have no write route (strategy, predictions, outcomes, proposals, deadlines) through
  the same M5 kernels `scripts/accept_m5.py` drives. The demo worker runs dispatched
  executions (real moot pre-pass, real filing-approval guard).

Fixtures are read by path from ironfleet-legal/dummy-case-harbour-freight/ (never copied,
never ingested). Skips with a named reason when web/dist, the fixture, Playwright or its
Chromium is missing. `scripts/accept_m8.py` runs `journey()` with screenshots."""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request
from datetime import date
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1]
DIST = CORE / "web" / "dist"
CASE = CORE.parent / "ironfleet-legal" / "dummy-case-harbour-freight"
DOCS = sorted((CASE / "docs").glob("*")) if (CASE / "docs").is_dir() else []
PASSWORD = "e2e-operator-pass"

# §6 step 1 answers, true to the fixture (invoices.txt: $42,000 + $84,000 principal outstanding)
INTAKE = {
    "summary": "Harbour Freight Solutions has not paid three freight statements under our supply "
               "agreement. After a $22,000 part payment on 3 August 2026, $126,000 principal is unpaid.",
    "other_party": "Harbour Freight Solutions Ltd",
    "claim_amount": "126000",
    "key_date": "20 December 2024",
    "criminal": "no", "children_involved": "no", "insolvent": "no",
}
# the two minute fixtures' ground truths (same values accept_m5 grades)
ROUND1 = {"date": "2026-11-05",
          "judge_said": "judgment entered for the plaintiff in $126,000; immediate enforcement "
                        "refused; time to pay: 20 working days",
          "orders": "judgment for the plaintiff in the sum of $126,000; payment within 20 working "
                    "days of the date of this minute; costs reserved"}
ROUND2 = {"date": "2026-12-08",
          "judge_said": "part payment $100,000 received 27 November 2026 within the window; balance "
                        "$26,000 outstanding; leave to enforce granted",
          "orders": "leave to enforce granted for the outstanding balance of $26,000; costs $1,500 "
                    "to the plaintiff within 10 working days",
          "next_date": "2027-02-10"}


def skip_reason() -> str | None:
    if not (DIST / "index.html").is_file():
        return "web/dist missing — run `npm run build` in web/"
    if len(DOCS) != 5 or not (CASE / "court-rounds" / "minute-round-2.md").is_file():
        return "harbour-freight fixture missing (ironfleet-legal/dummy-case-harbour-freight)"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright not installed (harness-core dev extra)"
    with sync_playwright() as p:
        if not Path(p.chromium.executable_path).is_file():
            return "Chromium not downloaded — run `playwright install chromium`"
    return None


class Live:
    """create_app(worker='demo') under uvicorn on a free loopback port, in a thread."""

    def __init__(self, root: Path, worker: str | None = "demo"):
        import uvicorn

        from harness.api.app import create_app
        from harness.service import auth, system
        con = system.open_db(root)
        auth.create_user(con, "operator", PASSWORD, role_id="admin")
        con.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        self.root, self.base, self.token = root, f"http://127.0.0.1:{port}", None
        self.server = uvicorn.Server(uvicorn.Config(
            create_app(root, web_dist=DIST, worker=worker, worker_poll_s=0.2, sse_poll_s=0.2),
            host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.1)
        assert self.server.started, "uvicorn did not start"
        self.token = self.api("POST", "/auth/login",
                              {"username": "operator", "password": PASSWORD})["token"]

    def api(self, method: str, path: str, body=None):
        h = {"Content-Type": "application/json", "Idempotency-Key": os.urandom(8).hex()}
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + "/api/v1" + path, method=method, headers=h,
                                     data=None if body is None else json.dumps(body).encode())
        return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"null")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(10)


class System:
    """The orchestrator stand-in (see module docstring) — never a UI action."""

    def __init__(self, live: Live, mid: str):
        self.live, self.mid = live, mid

    def move(self, *states):
        for s in states:
            self.live.api("POST", f"/matters/{self.mid}/lifecycle",
                          {"to": s, "note": "orchestrator stand-in"})

    def kernel(self, fn):
        from harness.service import system
        con = system.open_db(self.live.root)
        try:
            return fn(con)
        finally:
            con.close()

    def append(self, entity, event):
        from harness.lifecycle import dossier
        return self.kernel(lambda con: dossier.append(con, self.mid, entity, event,
                                                      actor="orchestrator"))

    def next_action(self, what, why):
        self.append("proposals", {"proposal_id": f"na-{os.urandom(4).hex()}", "what": what,
                                  "why": why, "asked_at_ts": date.today().isoformat()})

    def wait_approval(self, mid=None, timeout=30):
        for _ in range(int(timeout / 0.25)):
            rows = self.live.api("GET", f"/matters/{mid or self.mid}/approvals?state=pending")
            if rows:
                return rows
            time.sleep(0.25)
        raise AssertionError("no pending approval appeared")


def journey(live: Live, pg, shot=lambda name: None) -> dict:
    """§6 steps 1–10 (self-rep) then the Phase 6 firm loop. Asserts as it goes."""
    from harness.lifecycle import debrief, deadlines, restrategy
    B = live.base
    errors: list[str] = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("dialog", lambda d: d.accept())  # the user confirms the named consequence
    main =lambda: pg.inner_text("main")  # noqa: E731

    def view(mid, v, ready):
        pg.goto(f"{B}/#/case/{mid}/{v}")
        pg.wait_for_selector(ready, timeout=15000)

    pg.goto(B + "/#/")
    pg.fill("#u", "operator")
    pg.fill("#p", PASSWORD)
    pg.click("button[type=submit]")
    pg.wait_for_selector(".top", timeout=15000)
    pg.click("button.toggle:text('Self-rep mode')")
    pg.wait_for_selector("[data-mode='self-rep']")

    # 1 — start a case: describe it, answer one question at a time, upload every document
    pg.click("a[href='#/new']")
    pg.fill("#nm-title", "Southern Haulage v Harbour Freight")
    pg.click("button[type=submit]")
    pg.wait_for_selector("#q-a", timeout=15000)
    mid = pg.url.split("#/case/")[1].split("/")[0]
    sysm = System(live, mid)
    for _ in INTAKE:
        q = pg.inner_text("#q-h").lower()
        key = next(k for k, words in (("summary", "what happened"), ("other_party", "other side"),
                                      ("claim_amount", "money"), ("key_date", "start"),
                                      ("criminal", "police"), ("children_involved", "children"),
                                      ("insolvent", "debts")) if words in q)
        pg.fill("#q-a", INTAKE[key])
        pg.click(".qcard button.btn--primary")
        pg.wait_for_function("(prev) => { const h = document.querySelector('#q-h');"
                             " return !h || h.textContent.toLowerCase() !== prev; }",
                             arg=q, timeout=15000)
    pg.wait_for_selector("text=All questions answered", timeout=15000)
    assert "What we still need" not in main(), "facts register still incomplete after intake"
    # the fixture claim ($126,000) is above the self-help limit — the stop banner MUST show (08 §2)
    pg.wait_for_selector(".banner--block[role=alert]", timeout=15000)
    banner = pg.inner_text(".banner--block")
    assert "This claim is worth more than the self-help limit." in banner
    assert "Your case stays open" in banner
    pg.set_input_files("#intake-up", [str(p) for p in DOCS])
    for p in DOCS:
        pg.wait_for_selector(f"text={p.name}", timeout=15000)
    shot("01-intake-done")

    # 2 — read the assessment: the crew runs (demo body), the case is in "Checking your case"
    sysm.move("INTAKE", "ASSESS")
    live.api("POST", f"/matters/{mid}/executions",
             {"task_text": "recover the unpaid freight statements from Harbour Freight"})
    view(mid, "home", "text=You are here:")
    pg.wait_for_selector("text=Checking your case", timeout=15000)
    shot("02-assess")

    # 3 — approve the strategy: v1 on the Plan screen; approval on the S7 card (one decision surface)
    sysm.move("STRATEGY")
    sysm.append("strategy", {"version": 1, "file": "strategy-v1.md",
                             "why_changed": "opening strategy after the statement of claim",
                             "next_actions": ["prove the debt, seek summary judgment"]})
    sysm.append("predictions", {"prediction_id": "p1", "strategy_version": 1,
                                "claim": "The court orders the judgment sum payable IMMEDIATELY on entry."})
    sysm.append("predictions", {"prediction_id": "p2", "strategy_version": 1,
                                "claim": "Judgment is entered for the claimant."})
    sysm.wait_approval()
    view(mid, "plan", "text=/^Plan version 1 —/")
    assert "prove the debt, seek summary judgment" in main()
    assert pg.query_selector("main button:text('Approve')") is None, \
        "N4 must not carry a second approve button"
    view(mid, "home", "text=Also waiting on you (1)")
    shot("03-approve")
    pg.click("article.approval button:text('Approve')")
    pg.wait_for_selector("text=Also waiting on you", state="detached", timeout=15000)

    # 4 — pre-action letter: do it, click done; the response deadline lands on the calendar
    sysm.move("PRE_ACTION")
    sysm.next_action("Send the letter before action to Harbour Freight by email and post",
                     "a formal demand comes first — often it settles here")
    sysm.kernel(lambda con: deadlines.register(
        con, mid, "Harbour Freight's reply to the letter before action",
        date.today().isoformat(), days=10,
        missed_consequence="we can file the claim without waiting any longer"))
    view(mid, "home", "text=DO THIS NOW")
    assert "Send the letter before action" in main()
    pg.click("button:text('Mark done')")
    pg.wait_for_selector("text=Nothing needs you right now", timeout=15000)
    view(mid, "dates", "text=Harbour Freight's reply to the letter before action")
    assert "If you miss this date: we can file the claim" in main()
    pg.click("summary:text('Something looks wrong?')")
    pg.fill("textarea[id^='dq-']", "Does the 10 days count weekends?")
    pg.click("button:text('Ask the case manager')")
    pg.wait_for_selector("text=Sent — we will check it and answer.", timeout=15000)
    shot("04-pre-action")

    # 5 — file: the filing step, done; upload the sealed copy
    sysm.move("DRAFT", "MOOT", "APPROVE", "FILE_SERVE")
    sysm.next_action("File the statement of claim, serve Harbour Freight, then upload the sealed copy",
                     "the court needs the claim filed and served before it can act")
    view(mid, "home", "text=DO THIS NOW")
    pg.click("button:text('Mark done')")
    pg.wait_for_selector("text=Nothing needs you right now", timeout=15000)
    sealed = live.root / "sealed-statement-of-claim.txt"
    sealed.write_text("SYNTHETIC — sealed statement of claim (E2E stand-in for the court's stamp)\n",
                      encoding="utf-8")
    view(mid, "intake", "#intake-h")
    pg.set_input_files("#intake-up", str(sealed))
    pg.wait_for_selector("text=sealed-statement-of-claim.txt", timeout=15000)
    shot("05-filed")

    # 6 — wait / respond: it watches; the reply is a next action
    sysm.move("AWAIT", "RESPOND")
    sysm.next_action("Read Harbour Freight's defence and approve our reply",
                     "the other side has answered; our reply is drafted")
    view(mid, "home", "text=DO THIS NOW")
    pg.click("button:text('Mark done')")
    pg.wait_for_selector("text=Nothing needs you right now", timeout=15000)
    view(mid, "timeline", "li[aria-current='step']")
    assert "Replying" in pg.inner_text("li[aria-current='step']")
    shot("06-respond")

    # 7 — hearing pack + start a mock hearing
    sysm.move("HEARING_PREP")
    view(mid, "hearing", "text=Checklist")
    assert "✓ Done — no open blocking flaws" in main()
    pg.click("button:text('Start a practice hearing')")
    pg.wait_for_selector("text=Practice hearing started", timeout=15000)
    rehearsals = live.api("GET", f"/matters/{mid}/hearing-pack")["rehearsals"]
    assert len(rehearsals) == 1, rehearsals
    shot("07-hearing-pack")

    # 8 — go to court (doc 07: the operator enters COURT)
    sysm.move("COURT")
    view(mid, "home", "text=Your hearing day")

    def debrief_round(r):
        view(mid, "debrief", "#db-date")
        for k, v in r.items():
            pg.fill(f"#db-{k}", v)
        pg.click("form button[type=submit]")
        pg.wait_for_selector("text=What we predicted, and what happened", timeout=15000)
        return main()

    # 9 — debrief round 1 (minute-round-1): both predictions come back as text pairs
    t = debrief_round(ROUND1)
    assert "We predicted: The court orders the judgment sum payable IMMEDIATELY on entry." in t
    assert "We predicted: Judgment is entered for the claimant." in t
    assert live.api("GET", f"/matters/{mid}/lifecycle")["stage"] == "RE_STRATEGY"
    shot("09-debrief-1")
    sysm.kernel(lambda con: (
        debrief.record_outcome(con, mid, "p1", False,
                               "payment within 20 working days, not immediately", "2026-11-05"),
        debrief.record_outcome(con, mid, "p2", True, "judgment entered for the plaintiff",
                               "2026-11-05"),
        restrategy.cut_strategy(con, mid, "strategy-v2.md",
                                "court refused immediate enforcement; pivot to the time-to-pay window",
                                ["watch the 20-working-day window", "prepare leave-to-enforce papers"]),
        deadlines.register(con, mid, "judgment sum payable", "2026-11-05", days=20,
                           missed_consequence="leave to enforce without further hearing")))
    sysm.append("predictions", {"prediction_id": "p3", "strategy_version": 2,
                                "claim": "The defendant pays the full $126,000 within the "
                                         "20-working-day window."})
    view(mid, "plan", "text=/^Plan version 2 —/")
    pg.click("button:text('See what changed from version 1')")
    pg.wait_for_selector("text=What changed from version 1 to 2", timeout=15000)
    t = main()
    assert "＋ Added: watch the 20-working-day window" in t
    assert "The court said: payment within 20 working days, not immediately." in t

    # 10 — repeat: debrief round 2 (minute-round-2) → v3
    t = debrief_round(ROUND2)
    assert "We predicted: The defendant pays the full $126,000 within the 20-working-day window." in t
    sysm.kernel(lambda con: (
        debrief.record_outcome(con, mid, "p3", False, "part payment $100,000 only; $26,000 balance "
                               "outstanding — leave to enforce granted", "2026-12-08"),
        restrategy.cut_strategy(con, mid, "strategy-v3.md",
                                "defendant short-paid within the window; enforce the granted leave",
                                ["enforce the $26,000 balance"])))
    view(mid, "plan", "text=/^Plan version 3 —/")
    t = main()
    assert all(f"Version {v}" in t for v in (1, 2, 3)), "strategy v1→v3 not all visible"
    assert "waiting for the court" not in t, "a prediction is still unresolved"
    pg.click("button:text('See what changed from version 2')")
    pg.wait_for_selector("text=What changed from version 2 to 3", timeout=15000)
    assert "defendant short-paid within the window" in main()
    shot("10-strategy-v3")

    # firm loop (06 Phase 6): create → upload → dispatch → approve → collect → complete → archive
    pg.click("button.toggle:text('Self-rep mode')")
    pg.wait_for_selector("[data-mode='firm']")
    pg.goto(B + "/#/new")
    pg.fill("#nm-title", "Southern Haulage v Harbour Freight (firm)")
    pg.click("button[type=submit]")
    pg.wait_for_selector("#ws-h", timeout=15000)
    fmid = pg.url.split("#/m/")[1].split("/")[0]
    pg.get_by_role("link", name="Documents", exact=True).click()
    pg.set_input_files("#doc-up", [str(p) for p in DOCS])
    pg.wait_for_function("() => document.querySelectorAll("
                         "'table[aria-label=Documents] tbody tr').length === 5", timeout=15000)
    pg.get_by_role("link", name="Overview", exact=True).click()
    pg.fill("#disp-t", "recover the unpaid freight statements from Harbour Freight")
    pg.get_by_role("button", name="Dispatch", exact=True).click()
    sysm.wait_approval(fmid)
    pg.goto(B + "/#/approvals")
    card = f"article.approval:has(a:text('{fmid}'))"
    pg.wait_for_selector(card, timeout=15000)
    shot("11-firm-approvals")
    pg.click(f"{card} button:text('Approve')")
    pg.wait_for_selector(card, state="detached", timeout=15000)
    # the self-rep "Something looks wrong?" question reaches the approval centre; answer it
    q = "article.approval:has-text('Does the 10 days count weekends?')"
    pg.fill(f"{q} textarea", "Working days only — weekends and court holidays are excluded.")
    pg.click(f"{q} button:text('Provide')")
    pg.wait_for_selector(q, state="detached", timeout=15000)
    pg.goto(f"{B}/#/m/{fmid}")
    # 02 §4: a finished run leaves the matter "Review required"; ReviewRequired → Completed needs a
    # human sign-off that has no API route yet (matter_state never derives `completed`) — reported gap
    pg.wait_for_selector(".hdr .act :text('Review required')", timeout=30000)
    assert live.api("GET", f"/matters/{fmid}/runs")[0]["state"] == "completed"
    pg.get_by_role("link", name="Drafts", exact=True).click()
    pg.get_by_role("link", name="Audit", exact=True).click()
    pg.wait_for_selector("table[aria-label='Audit chain'] tbody tr", timeout=15000)
    shot("12-firm-review-required")
    pg.get_by_role("link", name="Overview", exact=True).click()
    pg.click("button:text('Archive matter')")
    pg.wait_for_selector(".hdr .act :text('Archived')", timeout=15000)
    board = [m["matter_id"] for m in live.api("GET", "/matters")["items"]]
    assert fmid not in board, "archived matter still on the board"
    shot("13-firm-archived")
    assert not errors, f"console errors: {errors[:3]}"
    return {"self_rep_matter": mid, "firm_matter": fmid}


@pytest.fixture()
def live(tmp_path, monkeypatch):
    reason = skip_reason()
    if reason:
        pytest.skip(reason)
    from harness.service import auth
    monkeypatch.setattr(auth, "_ITER", 1000)
    root = tmp_path / "store"
    root.mkdir()
    srv = Live(root)
    yield srv
    srv.stop()


def test_self_rep_journey_then_firm_loop(live):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            out = journey(live, b.new_page(viewport={"width": 1366, "height": 900}))
        finally:
            b.close()
    assert out["self_rep_matter"] != out["firm_matter"]
