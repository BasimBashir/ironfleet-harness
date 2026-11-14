"""M8 T9 D-6 accessibility audit (plan §2 T9; NEXT_STEPS §9A D-6; 08 §17; WCAG 2.2 AA).

Against a live serve whose data comes from the T8 journey (tests/test_web_e2e.py, loaded by
file path), every M8 screen is audited in BOTH themes in the browser:
- forms: every input/textarea/select has an accessible name (labels, aria-label/-labelledby);
- every button and link has a name; no duplicate ids; aria-labelledby/-describedby resolve;
- status is word + icon: every chip/state element carries a word, not only a glyph or colour;
- rendered contrast: every visible text node vs its effective background, 4.5:1 (3:1 large);
  inactive controls (aria-disabled / disabled) are exempt per WCAG 1.4.3.
Then the keyboard-only walks D-6 and 08 §17 name: ⌘K palette, the approval flows (approve +
answer a request), intake (focus stays on the active question; the lawyer-now banner is
role=alert, comes first and takes focus once), debrief (submit disabled-with-reason yet
focusable, the whole card operable by Tab/typing/Enter)."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "m8_e2e_for_a11y", Path(__file__).resolve().parent / "test_web_e2e.py")
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)

AUDIT_JS = r"""() => {
  const out = [];
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const where = (el) => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  const hidden = (el) => !!el.closest('[aria-hidden="true"]');
  const name = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) return lb.split(/\s+/).map((i) => document.getElementById(i)?.textContent || '').join(' ').trim();
    if (el.labels && el.labels.length) return [...el.labels].map((l) => l.textContent).join(' ').trim();
    return (el.textContent || el.getAttribute('title') || '').trim();
  };
  for (const el of document.querySelectorAll('input:not([type=hidden]), textarea, select'))
    if (!hidden(el) && !name(el)) out.push(['unlabelled-field', where(el)]);
  for (const el of document.querySelectorAll('button, a[href], [role=button], [role=option]'))
    if (!hidden(el) && vis(el) && !name(el)) out.push(['unnamed-control', where(el)]);
  const ids = {};
  for (const el of document.querySelectorAll('[id]')) ids[el.id] = (ids[el.id] || 0) + 1;
  for (const [id, n] of Object.entries(ids)) if (n > 1) out.push(['duplicate-id', id]);
  for (const a of ['aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-activedescendant'])
    for (const el of document.querySelectorAll(`[${a}]`))
      for (const id of el.getAttribute(a).split(/\s+/))
        if (id && !document.getElementById(id)) out.push(['dangling-' + a, where(el) + ' -> ' + id]);
  for (const el of document.querySelectorAll('button, [role=button], input[type=checkbox], input[type=radio]')) {
    const r = el.getBoundingClientRect();  // WCAG 2.5.8 target size (minimum) 24x24
    if (!hidden(el) && vis(el) && (r.width < 24 || r.height < 24))
      out.push(['target-size', `${where(el)} ${Math.round(r.width)}x${Math.round(r.height)}`]);
  }
  for (const el of document.querySelectorAll('.chip, .st, [data-state], .approval__kind, .health'))
    if (vis(el) && !/[A-Za-z]{2,}/.test(el.textContent || '')) out.push(['status-without-word', where(el)]);
  // contrast
  const rgba = (c) => { const m = c.match(/[\d.]+/g) || [0, 0, 0, 0]; return m.length < 4 ? [...m.map(Number), 1] : m.map(Number); };
  const over = (top, bot) => { const a = top[3]; return [0, 1, 2].map((i) => top[i] * a + bot[i] * (1 - a)).concat(1); };
  const bgOf = (el) => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none') return null;
      const c = rgba(s.backgroundColor);
      if (c[3] > 0) { stack.push(c); if (c[3] >= 1) break; }
    }
    let base = [255, 255, 255, 1];
    for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base);
    return base;
  };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!el || seen.has(el) || !n.textContent.trim() || hidden(el) || !vis(el)) continue;
    seen.add(el);
    if (el.closest('[aria-disabled="true"], :disabled, .sr-only')) continue;
    const s = getComputedStyle(el);
    if (Number(s.opacity) < 1) continue;
    const bg = bgOf(el); if (!bg) continue;
    const fg = over(rgba(s.color), bg);
    const size = parseFloat(s.fontSize), bold = Number(s.fontWeight) >= 700;
    const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5;
    const r = ratio(fg, bg);
    if (r < need) out.push(['contrast', `${where(el)} "${n.textContent.trim().slice(0, 30)}" ${r.toFixed(2)} < ${need}`]);
  }
  return out;
}"""


def screens(ids: dict) -> list[tuple[str, str, str]]:
    """(label, mode, hash) for every built M8 screen; ids from the journey + seeding."""
    sm, fm, rid = ids["self_rep_matter"], ids["firm_matter"], ids["run"]
    firm = [("board", "#/board"), ("new matter", "#/new"), ("approvals", "#/approvals"),
            ("run page", f"#/runs/{rid}"), ("not found", "#/no-such-page")] + [
        (f"workspace {t}", f"#/m/{fm}/{t}") for t in
        ("overview", "documents", "evidence", "workplan", "agents", "drafts", "decisions",
         "activity", "audit")]
    selfrep = [(f"N {v}", f"#/case/{sm}/{v}") for v in
               ("home", "intake", "timeline", "plan", "testing", "dates", "hearing", "debrief")]
    return [(n, "firm", h) for n, h in firm] + [(n, "self-rep", h) for n, h in selfrep]


def set_prefs(pg, mode: str, theme: str):
    pg.evaluate("([m, t]) => { localStorage.setItem('ironfleet.mode', m);"
                " localStorage.setItem('ironfleet.theme', t); }", [mode, theme])


def audit_screens(live, pg, ids) -> dict[str, list]:
    found: dict[str, list] = {}
    for theme in ("light", "dark"):
        for label, mode, h in screens(ids):
            set_prefs(pg, mode, theme)
            pg.goto(f"{live.base}/{h}")
            pg.reload()
            pg.wait_for_selector("main > *", timeout=15000)
            pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')", timeout=15000)
            time.sleep(0.2)
            assert pg.evaluate("document.documentElement.dataset.theme") == theme
            h1s = pg.locator("main h1").count()
            extra = [] if h1s == 1 else [("heading", f"main has {h1s} h1 (want exactly 1)")]
            for kind, where in extra + pg.evaluate(AUDIT_JS):
                found.setdefault(f"{theme} · {label}", []).append(f"{kind}: {where}")
    return found


def reflow_checks(live, pg, ids) -> list[str]:
    """UX-6: at the supported laptop/tablet widths the document never scrolls sideways (wide tables
    scroll inside themselves) and the top bar's search stays one line. Phones (320) are not claimed."""
    fails = []
    set_prefs(pg, "firm", "light")
    for w in (1024, 768):
        pg.set_viewport_size({"width": w, "height": 900})
        for label, mode, h in screens(ids):
            if mode != "firm":
                continue
            pg.goto(f"{live.base}/{h}")
            pg.wait_for_selector("main > *", timeout=15000)
            pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')", timeout=15000)
            time.sleep(0.2)
            sw, cw, sh = pg.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth,"
                                     " document.querySelector('.search')?.getBoundingClientRect().height || 0]")
            if sw > cw:
                fails.append(f"reflow {w}px · {label}: page scrolls sideways ({sw} > {cw})")
            if sh > 40:
                fails.append(f"reflow {w}px · {label}: search wraps to {sh:.0f}px")
    pg.set_viewport_size({"width": 1366, "height": 900})
    return fails


NO_FOCUS_RING: set[str] = set()
FOCUS_RING_JS = r"""() => {
  const e = document.activeElement;
  if (!e || e === document.body) return '';
  const s = getComputedStyle(e);
  const ring = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none';
  return ring ? '' : e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + ' "' + (e.textContent || '').trim().slice(0, 25) + '"';
}"""


def tab_to(pg, selector: str, limit: int = 120) -> bool:
    """Press Tab until document.activeElement matches `selector` (keyboard-only reachability)."""
    target = pg.locator(selector).first.element_handle(timeout=15000)  # Playwright selectors ok
    seen = []
    for _ in range(limit):
        pg.keyboard.press("Tab")
        no_ring = pg.evaluate(FOCUS_RING_JS)  # WCAG 2.4.7: every stop the walk lands on shows focus
        if no_ring:
            NO_FOCUS_RING.add(no_ring)
        if pg.evaluate("(t) => document.activeElement === t", target):
            return True
        seen.append(pg.evaluate("() => { const e = document.activeElement;"
                                " return e.tagName + '#' + e.id + ' ' + (e.textContent || '').trim().slice(0, 20); }"))
    print(f"tab_to({selector!r}) failed; target connected="
          f"{pg.evaluate('(t) => t.isConnected', target)}; visited: {seen[:40]}")
    return False


def keyboard_walks(live, pg, ids) -> list[str]:
    fails: list[str] = []
    want = lambda ok, msg: ok or fails.append(msg)  # noqa: E731
    focus = lambda: pg.evaluate(  # noqa: E731
        "() => { const e = document.activeElement; return e ? e.tagName.toLowerCase() + '#' + e.id"
        " + '.' + (e.className || '') + '[' + (e.getAttribute('role') || '') + ']' : ''; }")

    # ⌘K palette: opens on the shortcut, focus inside, Tab stays in the modal, Esc closes and
    # returns focus to where it was; typing + Enter navigates
    set_prefs(pg, "firm", "light")
    pg.goto(f"{live.base}/#/board")
    pg.reload()
    pg.wait_for_selector("#board-h")
    want(tab_to(pg, "button.search"), "palette trigger not reachable by Tab")
    pg.keyboard.press("Control+k")
    pg.wait_for_selector("[role=dialog]")
    want(pg.evaluate("() => !!document.activeElement.closest('[role=dialog]')"), "⌘K: focus not in palette")
    pg.keyboard.press("Tab")
    want(pg.evaluate("() => !!document.activeElement.closest('[role=dialog]')"),
         f"⌘K: Tab escapes the aria-modal palette (focus on {focus()})")
    pg.focus("[role=dialog] input")  # keep walking even if the trap check failed
    pg.keyboard.press("Escape")
    pg.wait_for_selector("[role=dialog]", state="detached")
    want(pg.evaluate("() => document.activeElement.matches('button.search')"),
         f"⌘K: Esc does not return focus to the trigger (focus on {focus()})")
    pg.keyboard.press("Control+k")
    pg.wait_for_selector("[role=dialog]")
    pg.keyboard.type("Go to Approvals")
    pg.keyboard.press("Enter")
    pg.wait_for_selector("#ap-h", timeout=15000)
    # UX-6: a new screen names itself (2.4.2) and takes focus at its start (2.4.3)
    want("Approvals" in pg.title(), f"route change: title not updated ({pg.title()!r})")
    want(pg.evaluate("() => !!document.activeElement.closest('main')"),
         f"route change: focus not moved into the new screen (focus on {focus()})")

    # approvals: answer a request and approve a filing, keyboard only
    q = "article.approval:has-text('Keyboard audit question')"
    pg.wait_for_selector(q, timeout=15000)
    want(tab_to(pg, f"{q} textarea"), "approvals: request answer box not reachable by Tab")
    pg.keyboard.type("Answered from the keyboard.")
    want(tab_to(pg, f"{q} button.btn--primary"), "approvals: Provide not reachable by Tab")
    pg.keyboard.press("Enter")
    try:
        pg.wait_for_selector(q, state="detached", timeout=15000)
    except Exception:
        fails.append("approvals: Enter on Provide did not answer the request")
    card = f"article.approval:has(a:text('{ids['kbd_matter']}'))"
    pg.wait_for_selector(card, timeout=30000)
    want(tab_to(pg, f"{card} button.btn--primary"), "approvals: Approve not reachable by Tab")
    pg.keyboard.press("Enter")
    try:
        pg.wait_for_selector(card, state="detached", timeout=15000)
    except Exception:
        fails.append("approvals: Enter on Approve did not decide the approval")

    # intake: focus stays on the active question; the banner reads first and takes focus once
    set_prefs(pg, "self-rep", "light")
    pg.goto(f"{live.base}/#/case/{ids['intake_matter']}/intake")
    pg.reload()
    pg.wait_for_selector("#q-a")
    for answer in ("A keyboard-only story.", "Someone Ltd", "4000", "1 March 2026", "yes"):
        prev = pg.inner_text("#q-h")
        want(pg.evaluate("() => document.activeElement.id === 'q-a'"),
             f"intake: focus not on the active question ({prev!r}; focus on {focus()})")
        pg.focus("#q-a")  # continue the walk even when the check above failed
        pg.keyboard.type(answer)
        pg.keyboard.press("Tab")
        want(pg.evaluate("() => document.activeElement.matches('.qcard button[type=submit]')"),
             f"intake: Tab from the answer does not reach Continue (focus on {focus()})")
        pg.keyboard.press("Enter")
        pg.wait_for_function("(p) => document.querySelector('#q-h')?.textContent !== p", arg=prev,
                             timeout=15000)
        time.sleep(0.3)
    pg.wait_for_selector(".banner--block[role=alert]", timeout=15000)
    time.sleep(0.5)
    want(pg.evaluate("() => document.activeElement.matches('.banner--block')"),
         f"lawyer-now: banner did not take focus (focus on {focus()})")
    want(pg.evaluate("() => { const b = document.querySelector('.banner--block'),"
                     " h = document.querySelector('main h1');"
                     " return !!(b.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING); }"),
         "lawyer-now: banner does not come before the screen heading")
    pg.evaluate("document.activeElement.blur()")  # views keep the banner mounted; start clean
    pg.goto(f"{live.base}/#/case/{ids['intake_matter']}/home")
    pg.wait_for_selector("#case-h")
    time.sleep(0.5)
    want(not pg.evaluate("() => document.activeElement.matches('.banner--block')"),
         "lawyer-now: banner re-takes focus on every screen (should be once)")

    # debrief: submit disabled-with-reason but focusable; the card is keyboard-complete
    pg.goto(f"{live.base}/#/case/{ids['intake_matter']}/debrief")
    pg.wait_for_selector("#db-date")
    want(tab_to(pg, "form button[type=submit]"),
         "debrief: Send is not focusable while disabled (disabled-with-reason must stay focusable)")
    why = pg.evaluate("() => { const b = document.querySelector('form button[type=submit]');"
                      " const d = b.getAttribute('aria-describedby');"
                      " return d ? document.getElementById(d)?.textContent : ''; }")
    want("date" in (why or ""), f"debrief: disabled Send does not name what is missing ({why!r})")
    pg.focus("#db-date")
    pg.keyboard.type("2026-11-09")
    for k in ("judge_said", "orders"):
        pg.keyboard.press("Tab")
        want(pg.evaluate(f"() => document.activeElement.id === 'db-{k}'"),
             f"debrief: Tab order skips #db-{k} (focus on {focus()})")
        pg.keyboard.type("keyboard audit")
    want(tab_to(pg, "form button[type=submit]"), "debrief: Send not reachable after the answers")
    pg.keyboard.press("Enter")
    try:
        pg.wait_for_selector("text=What we predicted, and what happened", timeout=15000)
    except Exception:
        fails.append("debrief: Enter on Send did not submit")
    return fails


def seed_and_journey(live, pg) -> dict:
    ids = e2e.journey(live, pg)
    sm = ids["self_rep_matter"]
    sysm = e2e.System(live, sm)
    sysm.append("flaws", {"flaw_id": "f1", "class": "citation", "severity": "critical", "doc": "letter",
                          "status": "fixed", "detector": "citator", "detail": "a case name was misspelt"})
    sysm.append("flaws", {"flaw_id": "f2", "class": "evidence", "severity": "minor", "doc": "letter",
                          "status": "open", "detector": "evidence", "detail": "an invoice copy is blurred"})
    ids["run"] = live.api("GET", f"/matters/{ids['firm_matter']}/runs")[0]["execution_id"]
    k = live.api("POST", "/matters", {"title": "Keyboard audit v Harbour Freight"})["matter_id"]
    live.api("POST", f"/matters/{k}/executions", {"task_text": "recover the debt"})
    live.api("POST", f"/matters/{k}/requests", {"kind": "info", "question": "Keyboard audit question"})
    ids["kbd_matter"] = k
    ids["intake_matter"] = live.api("POST", "/matters", {"title": "Intake keyboard audit"})["matter_id"]
    return ids


@pytest.fixture()
def live(tmp_path, monkeypatch):
    reason = e2e.skip_reason()
    if reason:
        pytest.skip(reason)
    from harness.service import auth
    monkeypatch.setattr(auth, "_ITER", 1000)
    root = tmp_path / "store"
    root.mkdir()
    srv = e2e.Live(root)
    yield srv
    srv.stop()


def test_d6_every_screen_both_themes_and_keyboard_walks(live):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        try:
            pg = b.new_page(viewport={"width": 1366, "height": 900})
            ids = seed_and_journey(live, pg)
            found = audit_screens(live, pg, ids)
            walks = keyboard_walks(live, pg, ids)
            walks += reflow_checks(live, pg, ids)
        finally:
            b.close()
    walks += [f"focus-visible: no focus indicator on {w}" for w in sorted(NO_FOCUS_RING)]
    report = [f"{k}\n  " + "\n  ".join(v) for k, v in found.items()] + walks
    assert not report, (f"{sum(map(len, found.values()))} screen findings, {len(walks)} keyboard "
                        f"findings:\n" + "\n".join(report))
