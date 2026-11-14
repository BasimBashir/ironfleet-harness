# 12 — Accessibility audit, M8 web client (gate D-6)

**Date:** 2026-11-09 · **Standard:** WCAG 2.2 AA (NEXT_STEPS §9A D-6; 08 §17; 05 §0, §12)
**Verdict:** automated audit **0 findings** after fixes (24 screen states × 2 themes + 4 keyboard
walks); **one open AA gap** (1.4.10 Reflow, below) and the manual checks listed under "Not
covered" are still owed before Release A.

## Method

`tests/test_web_a11y.py` (runs in the normal suite; skips with a named reason without
`web/dist`, Playwright or Chromium). It drives a live `create_app(worker="demo")` whose data is
the T8 harbour-freight journey (`tests/test_web_e2e.py`), so every screen is audited with real
content, not empty states.

**Screens (each in light and dark):** firm — board, new matter, approvals, run page, not-found,
workspace × 9 tabs (overview, documents, evidence, work plan, agents, drafts, decisions,
activity, audit); self-rep — case home (N2), intake (N1), journey (N3), plan (N4), testing (N5),
dates (N8), hearing (N6), after court (N7).

**Per-screen checks (in-page script `AUDIT_JS`):**

| Check | WCAG |
|---|---|
| exactly one `h1` in `main` | 1.3.1, 2.4.6 |
| every input/textarea/select has an accessible name | 1.3.1, 3.3.2, 4.1.2 |
| every button/link/option has a name | 2.4.4, 4.1.2 |
| no duplicate ids; every `aria-labelledby/-describedby/-controls/-activedescendant` resolves | 4.1.2 |
| status is word + icon: every chip / state / approval kind / health carries a word | 1.4.1 |
| rendered contrast of every visible text node vs its effective (alpha-composited) background — 4.5:1, 3:1 for large text; inactive controls exempt | 1.4.3 |
| buttons ≥ 24 × 24 CSS px | 2.5.8 |

The token-level gate (`tests/test_design_contrast.py`, 63 pairs × 2 themes) stays at 0 failing;
this audit adds the rendered check, which catches colours composed at runtime (alpha layers,
inherited backgrounds) that a token table cannot.

**Keyboard-only walks (Tab / typing / Enter / Esc / ⌘K, no mouse):**

1. **⌘K palette** — trigger reachable by Tab; ⌘K opens with focus inside; Tab stays inside the
   `aria-modal` dialog; Esc closes and returns focus to the trigger; type + Enter navigates.
2. **Approvals** — answer an info request (Tab to the answer box, type, Tab to Provide, Enter) and
   approve a filing (Tab to Approve, Enter, confirm) — both cards leave the list.
3. **Intake (N1)** — five answers typed; after each, focus is on the active question and Tab
   reaches Continue; the "criminal" answer raises the lawyer-now banner, which is `role="alert"`,
   precedes the screen heading, takes focus **once** and does not re-take it on other views.
4. **Debrief (N7)** — Send is focusable while disabled and names what is missing ("add the
   hearing date first"); fields are in Tab order; Enter on Send submits and the diff reads back.

Every Tab stop the walks land on is checked for a visible focus indicator (2.4.7).

## Findings and fixes

| # | Finding (first run) | WCAG | Fix |
|---|---|---|---|
| 1 | Guided views (7 of 8): outer `section aria-labelledby="case-h"` pointed at an id only case home has | 4.1.2 | outer wrapper is a plain `div`; each view's own section is labelled (`CaseScreens.jsx`) |
| 2 | Run page had no `h1` (the page reused the drawer's `h2`) | 1.3.1 | `RunPage` wraps the drawer in a section with `h1` "Run inspection" |
| 3 | Not-found page had no heading | 1.3.1 | `h1` "Page not found" (`App.jsx`) |
| 4 | ⌘K: Tab left the `aria-modal` palette; once out, Esc could not close it | 2.1.2, 2.4.3 | Tab is held on the palette's single stop (`App.jsx` Palette) |
| 5 | ⌘K: closing left focus on `body` | 2.4.3 | palette restores focus to the element that opened it |
| 6 | ⌘K: Enter on a command re-opened the palette (the same key's keypress landed on the restored trigger) | 2.1.1 | `preventDefault()` on the picking Enter |
| 7 | Intake: after each answer focus fell to `body` (Continue is disabled while saving) | 2.4.3, 08 §17 | focus moves to the new question when it lands (`Intake`) |
| 8 | Lawyer-now banner never took focus | 08 §17 | banner focuses once per matter + trigger set (sessionStorage), never again on other views |
| 9 | Disabled-with-reason buttons were really `disabled` — out of the Tab order, so the reason was unreachable (debrief Send, any permission-gated button) | 2.1.1, 05 §12 | `Btn` keeps `aria-disabled` + `aria-describedby` and drops `disabled` when a reason is shown (`ui.jsx`) |

| 10 | Debrief questions were one ungrouped list (08 §17 asks for topic groups) | 1.3.1 | `fieldset` + `legend` per topic (found in the D-7 pass) |
| 11 | Lawyer-now "I have a lawyer now" was an enabled button that did nothing | 05 §12, 3.2.2 | disabled-with-reason until an API exists (D-7 pass) |

Found in passing by the same browser runs (T8), fixed: the approval centre's "Provide" posted
`{answer}` while the API takes `{text}`, so no info request could be answered at all.

## Open — not fixed in M8

- **1.4.10 Reflow (AA) fails at 320 CSS px.** The shell (header + rail) does not collapse:
  `document.scrollWidth` is ~600 px on approvals and the new-case form, 1217 px on the board (the
  board's table is an allowed two-dimensional exception; the shell is not). Needs a responsive
  shell — a layout design change, so mockups first (owner rule), and plan §3 already defers the
  tablet layout to after D-5. **Blocks a clean D-6 sign-off for Release B (self-rep on phones).**
  *UX-6 (2026-11-14):* the shell now reflows at the supported laptop/tablet widths — no page-level
  horizontal scroll on any firm screen at 1024 or 768 (tables scroll inside themselves; guarded by
  `reflow_checks` in `test_web_a11y.py`). A 320px measurement of six screens showed no page-level
  scroll either, but phone use is still not claimed (no AT/zoom/touch pass) — this item stays open for Release B.
- ~~**Route changes do not move focus**~~ — fixed in UX-6: a new screen focuses `main` and sets
  its own `document.title` (2.4.2); asserted in the ⌘K keyboard walk. See `data/eval/UX-6/REPORT.md`.

## Not covered by this audit (owed, manual)

- Real screen readers (NVDA + Chrome on Windows, VoiceOver + Safari on macOS) on the §6 journey —
  the audit checks names, roles and order, not how they are announced.
- 200 % zoom / 1.4.4 text resize, 1.4.12 text spacing, Windows high-contrast mode.
- Print of the hearing pack, deadline list and closing summary (08 §17; N6 checklist ticks and
  the arguments sheet are not built yet).
- N6 rehearsal (not built: no API resource) — its keyboard walk is pending with it.
- `prefers-reduced-motion`: verified by inspection only — every transition in `app.css` and
  `components.css` uses `var(--dur)`, which `tokens.css` sets to 0 ms under reduce.

## Re-run

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_web_a11y.py
```
