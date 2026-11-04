# 08 — Guided Journey UX Specification (N1–N12)

**Date:** 2026-11-04 · **Status:** specification — this document fixes content, states, copy
rules and API reads. **No screen may be built until the owner picks the mockups** (gate D-3,
NEXT_STEPS §9A.3; 05 §14). As in 05, the ASCII sketches are layout contracts, not visual design.
**Companions:** [04-api-and-events.md](04-api-and-events.md) (endpoint/error/SSE conventions —
§16 inherits them verbatim) · [05-product-and-ux-specification.md](05-product-and-ux-specification.md)
(workspace shell, firm-mode spec, shared state and permission rules) · NEXT_STEPS §3 (lifecycle),
§3.4 (safety rails), §6 (journey) · doc 09 (moot-gate, M6) will own the flaw-ledger schema N5 renders.

## 0. What this document is

05 specifies the firm workspace. This document specifies the **guided journey**: the twelve
screens (§9A.2, N1–N12) that carry a person with no legal background through a matter end to
end (NEXT_STEPS §6), plus the shared surfaces both modes use. Self-rep mode is the primary
spec; **firm mode is stated as a delta on each screen**, never a second design. S-screens are
consumed, not re-specified: S1 (shell, ⌘K), S7 (Approval Center), S8 (documents/evidence),
S9 (activity), S10 (shared loading/error/empty/permission behaviour).

Rules that bind every screen here:

- The §1 promise (NEXT_STEPS): process, not outcome. No screen ever promises a court will
  accept anything or that a case is won (§1 below turns this into copy rules).
- §3.4 safety rails are screens, not settings: the lawyer-now detector renders as N10 and
  blocks; the deadline sentinel renders in N8 and N2; the assumption register renders in N4.
- One case engine, two front doors (D-P1): every screen reads the same dossier the plugin and
  the firm workspace read. Nothing here is a separate data path.
- Firm mode differences are global before they are per-screen: dense default layout,
  plain-language **optional** (N9), coaching copy replaced by work-plan language, lawyer-now
  renders as a **flag, not a block** (the supervising lawyer decides — D-P4: gates before
  reach; the blocking behaviour is the self-rep release's, per §7 Release B).
- Out of scope for v1 (named so they are not accidentally built): audio/video rehearsal,
  free-chat intake (v1 intake is structured Q&A), notification e-mail/SMS sending (reminders
  are in-product + .ics; delivery channels are M11), mobile-specific layouts (05 §11).

## 1. Plain-language standard (reading age ~12)

These rules are the contract for every user-facing string in self-rep mode. Firm mode copy may
stay dense, but the jargon rule still applies to anything a client will read.

1. **Sentences** ≤ 20 words, one idea each. Active voice; name the actor ("We check this
   deadline", never "This deadline will be checked").
2. **Voice:** second person "you"; the system says "we" when it acts, and "the court"/"the
   other side" when it doesn't.
3. **No unexplained legal terms.** A term that must appear renders as a chip: the term plus a
   one-line plain explanation inline (first use per screen, expandable later). The approved
   glossary ships with the jurisdiction pack (M9) — screens never invent definitions.
4. **Dates in both forms, always:** "14 November 2026 (in 10 days)". Filing cut-offs add the
   time and where. Money carries currency and tax status per the jurisdiction pack.
5. **Outcome neutrality.** Never "you will win", "this will succeed", "the court will accept".
   Strength claims carry their reason: "Your case looks strong because the contract is signed
   and the emails confirm the agreement." Confidence is shown as the measured prediction
   record (§7, N4) — never as a vibe.
6. **Verbs that say exactly what to do:** "Upload the signed contract", not "Provide
   documentation". Every primary action names its object.
7. **One primary action per screen** (self-rep). Secondary actions stay visible but visually
   secondary — nothing important is hidden behind a menu a non-lawyer will never open.
8. **Residual risk sits next to the action.** Every approve/send/file/choose button carries
   its risk line directly beneath (05 §7's discipline, self-rep wording).
9. **Calm about failure.** Missed-deadline and wrong-prediction copy is factual and gives the
   next step; never blames, never dramatises.
10. **Check the rules, not the vibes:** every string is drafted against 1–9 and re-read at
    D-5 usability testing with non-lawyers (§7 Release B requires that test) — no automated
    reading-age tooling is added for this.

## 2. "Get a lawyer now" — triggers, states, banner (N10)

Purpose: stop advising self-help the moment the matter exceeds what self-help can safely
carry (NEXT_STEPS §3.4). The detector is M5; the screens' contract is the flag read (§16) and
the rendering below.

**Triggers — any one activates the banner:**

| # | Trigger | Source |
|---|---|---|
| 1 | Criminal exposure — facts suggest the user faces or is near criminal investigation or charges | intake facts, uploads |
| 2 | Children / family safety — care of children, protection orders, family violence | intake facts, uploads |
| 3 | User insolvency — the user may need to declare bankruptcy or is in insolvency proceedings | intake facts |
| 4 | Above the self-help threshold — claim value exceeds the forum's self-rep limit | limitation/forum kernel; **the value comes from the jurisdiction pack, never hardcoded** |
| 5 | Missed limitation date — the kernel reports the claim period has lapsed | limitation kernel |
| 6 | Court order against the user — any ingested document is or contains an order binding the user | debrief/upload ingest |

**Detector states:** `clear` (no banner) → `flagged` (suspected: soft banner, "We need to
check something with you" + one question; the detector re-runs) → `active` (confirmed
trigger: blocking banner). Re-run on every dossier change: intake answer, upload ingest,
debrief, strategy change.

**Banner copy — exact strings (self-rep, active state):**

> **⛔ Stop — you need a lawyer for this**
>
> 1. "This may involve criminal charges. A lawyer must handle anything that could lead to criminal charges."
> 2. "This involves the safety or care of children. Family Court matters need a lawyer — and support services may be able to help you now."
> 3. "You may need to deal with serious debt or bankruptcy. A lawyer should guide this."
> 4. "This claim is worth more than {threshold}. At this amount, the {forum} expects cases to be run by lawyers, and the risk of losing money is higher."
> 5. "The time limit for this claim has passed. Only a lawyer can tell you if there is still a way forward."
> 6. "A court has made an order against you. Get legal advice before you do anything else."

Footer (always): "Your case stays open. You can keep uploading documents. We stop advising
you on this matter until a lawyer is involved." Help line: "Free help: {services from the
jurisdiction pack — NZ: Community Law Centre, Citizens Advice Bureau, local Duty Lawyer}."
Action: "I have a lawyer now" — records the answer, marks the matter lawyer-supervised, and
switches it to the firm-style approval flow (the change lands in the audit chain). Otherwise
the banner clears only when the underlying trigger clears in the dossier — never on a click.

**What it blocks (self-rep):** strategy, drafting-for-filing, approval and filing flows stop
advancing; uploads, debrief answers and closure stay available. **Firm mode:** the same
detector renders as a non-blocking flag on the workspace header and Board row with the
identical reason text; nothing gates (05 §2 risk-flag column).

**Placement & behaviour:** full-width, pinned above every screen in self-rep mode while
`active`; does not scroll away; primary content of the screen shifts below it. On activation
it takes focus once; `role="alert"`; icon **and** the word "Stop" (never colour alone);
screen readers read it as the first content on the page.

## 3. Journey map — entry and exit for every screen

The §6 journey steps are the spine; §3.1 states are what the backend knows. Every screen
names where the user comes from and where they go — no orphan screens.

| Screen | §6 step | Lifecycle states (§3.1) | Enters from | Exits to | Primary action |
|---|---|---|---|---|---|
| N1 Intake | 1 | INTAKE | S1 "New case"; re-entry from N2 card | ASSESS → N2 assessment card; or N10 on a trigger | "Continue" |
| N2 Case home | 2–12 (always) | all | sign-in (self-rep landing); "My case" | the screen the action needs | the one next action |
| N3 Timeline | — (persistent) | all | N2 rail; header strip | the stage's screen, or its explainer | none (navigation) |
| N4 Strategy versions | 3 | STRATEGY, RE-STRATEGY | approval request; "See what changed" | S7 approve/send-back → N2 | "Read what changed" |
| N5 Defensibility | 4–7 | MOOT (within DRAFT–APPROVE) | "Your {document} is ready" card | S7 approval → N2 | "See what we fixed" |
| N6 Hearing pack | 7 | HEARING-PREP | hearing date confirmed; N2 card | hearing-day card → N7 | "Start rehearsal" |
| N7 Debrief | 8–9 | DEBRIEF | hearing-day card; N2 card on the day | re-strategy → N4 (vN+1 approval) | "Tell us what happened" |
| N8 Deadlines | 4–10 | all post-INTAKE | N2 rail; tab | the task the deadline belongs to | "Add to my calendar" |
| N9 Plain toggle | — | all | S1 header control; per-output toggle | — | none (setting) |
| N10 Lawyer-now | — | any | detector (§2) | lawyer handoff / supervised mode | "I have a lawyer now" |
| N11 Judgment etc. | 11 | JUDGMENT → ENFORCE/APPEAL/SETTLE | judgment ingested; N2 card | choice via S7 → N12 path | "Choose what to do next" |
| N12 Closure | 12 | CLOSED | closure eligibility; N2 card | archived (read-only) | "Close my case" |

Settlement and discontinuance can branch out of any state after PRE-ACTION (§3.1): they
render as an always-visible secondary action on N2 ("Ask about settling instead") once
PRE-ACTION is reached — choosing one is an approval-card act (04 §5.6), never a side link.

## 4. N1 — Intake interview

**Purpose.** Turn "describe the problem in your own words" into a complete facts register,
collect the documents, and run the safety checks (conflict, limitation, forum, lawyer-now
triggers) — §3.2 Intake.

**Entry / exit.** S1 "New case"; re-entry when the facts register reports missing items (N2
card). Exit: register complete enough → ASSESS runs → N2 shows the assessment card; or a
lawyer-now trigger → N10 takes over with answers preserved.

**Content blocks.**

- Progress header: "Setting up your case — step 2 of 6". The step count comes from the
  interview sections the facts register defines — never a fabricated total.
- Free-text first: "Tell us what happened, in your own words. Dates, names and amounts help."
- Interview queue: **one question at a time** (self-rep). Each question ≤ 20 words, one ask,
  with an example where format matters ("For example: 14 March 2026").
- Upload zone: "Upload every paper, email or photo about this problem. You can add more
  later." Accepted types listed; each upload confirms what it was read as (S8 viewer link).
- "What we still need" list: live; each item says how to get it ("Ask your employer for your
  employment agreement — you can request it by email").
- Checks line: conflict / limitation / forum results as plain chips as they return:
  "Time limit: OK — you have until 12 March 2027" · "Time limit: urgent — 9 days left" ·
  any trigger → N10.

**States.**

- Loading: skeleton for the current question + saved answers. Answers persist per question —
  a refresh or crash never loses work (durable dossier, 02 §4).
- Empty (fresh matter): the free-text box is the whole screen; nothing else.
- Error: answer save fails → inline "We couldn't save your last answer. Try again — nothing
  is lost." (client retries; on failure the answer is kept locally and re-synced).
- Permission: self-rep user edits their own matter only. The supervising lawyer (pilot, M12)
  sees the same screen dense and may edit — edits are audit-logged. Read-only roles: fields
  disabled-with-reason (05 §12), never hidden.
- Special — interview interrupted by a lawyer-now trigger: N10 takes over; answers preserved;
  the interview resumes only if the matter returns to self-rep guidance.

**API reads and commands.** `POST /api/v1/matters` (create; self-rep mode flag — 04 §5.2) ·
`GET /api/v1/matters/{mid}/intake/questions` → server-driven next question + remaining
estimate (§16) · `POST /api/v1/matters/{mid}/intake/answers {question_id, answer, doc_ids?}`
→ 202 (§16) · `GET /api/v1/matters/{mid}/dossier/facts` → facts register; "what we still
need" is the missing-field projection (§16) · `POST /api/v1/matters/{mid}/documents` (04 §5.3)
· `GET /api/v1/matters/{mid}/lawyer-now` (§16) · SSE `intake.progress`, `lawyer_now.changed`
on `channels=matter:{mid}` (04 §5.7).

**Firm vs self-rep.** Firm: all questions on one dense form; the intake-interviewer agent's
draft facts register is visible and editable; plain-language copy is the client-facing export,
not the working view.

**Copy rules.** One ask per question; never two questions in one sentence; every "why we ask"
line ≤ 12 words.

**Accessibility.** Each question a labelled `fieldset`; check results announced
`aria-live="polite"`; upload zone is a real button (not drag-only) with a visible file list;
progress announced ("Step 2 of 6"); errors tied to their input (`aria-describedby`); focus
stays on the active question.

## 5. N2 — Case home + next-action card

**Purpose.** Answer "what do I do now?" in one read: the one thing to do, why, by when, and
what happens if it is missed — the product's core screen (§9A.2).

**Entry / exit.** Self-rep sign-in lands here (not the Board — that is firm's S2). Exit goes
wherever the action lives (N1, S7, N6, N7…).

**Content blocks.**

```text
┌ Harriet v Fleetwood Plumbing ──────────────────────── You are here: Waiting ┐
│                                                                            │
│  DO THIS NOW                                                               │
│  Send the pre-action letter to Fleetwood Plumbing                          │
│  Why: it starts the formal process and often leads to payment without court│
│  By: 14 November 2026 (in 10 days)                                         │
│  If you miss it: we may have to re-plan; fixing that later can cost more    │
│  [ Send it the way the instructions say ]   ← single primary action         │
│  Residual risk: the other side may deny the debt; our answer is prepared    │
├────────────────────────────────────────────────────────────────────────────┤
│  Also waiting on you (2)   ⚑ approve the strategy · ⚑ upload the invoice   │
│  Last update: reply received from the other side — read it (2 days ago)    │
└────────────────────────────────────────────────────────────────────────────┘
```

- Next-action card: action (verb phrase), why (one sentence), deadline + miss-consequence
  line (deadline sentinel, §3.4), primary button, residual-risk line (§1.8).
- "Also waiting on you": compact rows for the other pending items; the count is the server's
  count (05 §2 discipline — a database fact, never inferred client-side).
- Mini status: one line of the journey (N3) — "You are here: Waiting for the other side's
  reply. Next date: 20 November 2026."
- Last update: most recent dossier event, linked to N3/S9.

**States.** Loading: skeleton card, same layout. Empty (no open action): "Nothing needs you
right now. We will tell you when something does." + the next date if one exists. Error: data
stale marker + retry (05 §10). Permission: firm viewer gets the dense variant without coaching
copy; approval/complete buttons follow 05 §12 (disabled-with-reason). **Special — ordering:**
lawyer-now > deadline < 48 h > approval > everything else; the card shows one, the list
carries the rest. An overdue deadline replaces the card ("A deadline was missed" → re-strategy
path, §3.4).

**API reads and commands.** `GET /api/v1/matters/{mid}/next-actions` → ordered cards (§16) ·
`POST /api/v1/matters/{mid}/next-actions/{aid}/complete {note?}` → 202 (§16) ·
`GET /api/v1/matters/{mid}/lifecycle` (mini status) · `GET /api/v1/matters/{mid}/lawyer-now`
(§2) · SSE `next_action.changed`, `lifecycle.stage_changed`, `deadline.state_changed`.

**Firm vs self-rep.** Firm lands on S2 Board; the card's content exists there as the
Work Plan's next task, not as coaching copy.

**Copy rules.** Card title = the action as a verb phrase ("Send the pre-action letter"). The
miss line is factual and calm: "If you miss this date, your claim may be struck out. We will
remind you 7, 3 and 1 day before."

**Accessibility.** The card is one labelled region (`aria-labelledby`); deadline as text +
icon; the consequence line is the button's accessible description; exactly one primary
tab-stop on the card.

## 6. N3 — Journey timeline

**Purpose.** Show where the case is in the §3.1 path — done, now, next — and set the honest
expectation that a case repeats and takes months (§3.1's ↺ loops are visible, not hidden).

**Entry / exit.** N2 rail; collapsed strip on every self-rep screen's header. Exit: select a
stage → its screen, or a one-line explainer of what happens there.

**Content blocks.** The §3.1 states rendered as a **plain-named path**; narrow widths render
it as a list (the list is the canonical, accessible form — the graphic is decoration):

Setting up · Checking your case · Planning · Letters before court · Writing documents ·
Testing our work · Your approval · Lodging at court · Waiting · Getting ready for the hearing ·
Your hearing day · Telling us what happened · New plan · The decision · Getting results ·
Finished.

- Each node: plain name + the date it happened + one-line "what happens here" (revealed on
  focus/expand, not hover-only).
- Loops rendered as annotation, not graph cycles: after "Waiting" a note "This can repeat:
  we wait → they reply → we respond → we wait"; after "Telling us what happened" a note
  "Each hearing adds a round: tell us → new plan".
- Side exits (settle / discontinue, any state after PRE-ACTION) shown as labelled exits.
- The "now" node is highlighted with word + icon; future nodes carry their plain name, greyed
  but readable — a self-rep user should see the whole road ahead; that is the product's honesty.

**States.** Loading skeleton; error → stale marker (05 §10); permission: it is a read —
nothing to disable at any role.

**API reads and commands.** `GET /api/v1/matters/{mid}/lifecycle` → current stage, history
(each with `entered_at`), allowed next (§16) · SSE `lifecycle.stage_changed`.

**Firm vs self-rep.** Firm: the dense state ribbon in the workspace header (05 §3) with real
state names; the plain-name mapping lives in tooltips.

**Copy rules.** Plain names are fixed strings from this section; the legal term rides as a
glossary chip on demand ("Lodging at court (filing)").

**Accessibility.** The path is an ordered list (`ol`) in DOM order; current step announced
("You are here: Waiting"); every node keyboard-focusable with its explanation; motion ≤ 150 ms
and suppressed under `prefers-reduced-motion` (05 §0).

## 7. N4 — Strategy versions

**Purpose.** Show the plan and every change to it — what changed, why, and which prediction
failed (§3.2 Strategy / Re-strategy; §3.3 dossier discipline).

**Entry / exit.** An approval request for a new version; "See what changed" from N2; the
timeline node. Exit: approve / send back **on the S7 approval card** (the same
`POST /approvals` as everywhere — one decision surface); this screen never carries a second
approve button.

**Content blocks.**

- Current plan, one page: what we will do, the steps, the dates (§6 step 3).
- Version list v1…vN; select two to diff. Diff rows: what changed · why (the re-strategy
  reason, in plain words) · which prediction failed (from the outcome log).
- Assumption register (§3.4): every assumption the plan rests on, each with its last-checked
  date; an assumption found false is flagged with what it affected.
- Prediction record: "We predicted payment within 30 days. The court ordered payment in 14
  days." — the running prediction-vs-outcome list (§3.3 outcome log).

**States.** Loading skeleton; empty: "Your plan appears after we finish checking your case."
Error: stale marker. Diff computing: inline "Comparing versions…" row, not a page spinner.
Permission: approve actions require `approval.decide` → disabled-with-reason (05 §12); every
matter member can read.

**API reads and commands.** `GET /api/v1/matters/{mid}/strategy?cursor=` → StrategyVersion[]
· `GET /api/v1/matters/{mid}/strategy/{v}/diff?against={w}` → changes + reasons + failed
predictions (§16) · `GET /api/v1/matters/{mid}/predictions` (§16) · approvals via 04 §5.6.

**Firm vs self-rep.** Firm: clause-level diff with anchors, assumption register as its own
tab, predictions as a raw table. Self-rep: the diff is the three-column plain version above.

**Copy rules.** Version header: "Plan version 3 — made 2 November 2026, after the hearing on
31 October." Change row: "What changed: we added a claim for interest. Why: the judge asked
about unpaid interest at the last hearing."

**Accessibility.** Diff changes labelled with word + icon (added / changed / removed), never
colour-only; versions are a list with headings; the predictions table has header cells.

## 8. N5 — Defensibility report

**Purpose.** Show what the moot gate found and fixed, what risks remain, and hand over
"their arguments & your answers" — the sheet the user takes into court (NEXT_STEPS §4.5).

**Entry / exit.** A document finishes a moot round; "Your {document} is ready" on N2; the
"Testing our work" timeline node. Exit: S7 approval (approve the document or send it back).

**Content blocks.**

- Verdict line, one of: passed · passed with open flaws · round cap reached (§4.4 — the cap
  state is **never silent**: open flaws are listed in full).
- Flaw ledger summary: found / fixed / remaining, grouped by class; each flaw: severity
  (critical / material / minor — word + icon), what it was, how it was fixed, or the open-flaw
  note. Full ledger expandable (schema: doc 09, M6).
- Deterministic checks: citations verified · quotes exact · deadlines kernel-checked · forms
  valid — each a pass/fail chip with what was checked.
- Residual risks: the plain-language list the approval card also carries (§1.8).
- "Their arguments & your answers" sheet: preview + download (an Artifact, 04 §5.3).

**States.** Loading: "Testing your document — round 2" (live round state, not a bare
spinner). Empty: "Nothing is being tested right now." Error (gate failed to run): "We
couldn't finish testing. We will not send anything out until testing passes. Try again." —
and the document stays unapproved. Permission: all matter members read; the per-attacker
breakdown is the firm delta below. Cap-reached: the open-flaws block is the loudest element
and the primary action becomes "Read the risks, then decide" linking to S7.

**API reads and commands.** `GET /api/v1/matters/{mid}/flaws?state=&severity=&cursor=` (§16;
schema per doc 09) · the report and the answers sheet are Artifacts via 04 §5.3 ·
SSE `flaw_ledger.updated`.

**Firm vs self-rep.** Firm: round-by-round ledger, per-attacker sections (opposing counsel ·
bench · procedural · evidence · citator), keep-if-better decision records. Self-rep: the
summary above; the full ledger is expandable but the summary is the screen.

**Copy rules.** Severity words first: "Critical — this would have sunk the letter." Fixed
flaws are past tense, open flaws present.

**Accessibility.** Verdict as a text heading; the ledger a definition list; expandable
sections keyboard-operable; severity never colour-only.

## 9. N6 — Hearing pack + mock hearing

**Purpose.** Get the user ready for the hearing: what to bring, the script, the questions
they will face — then rehearse (§3.2 Hearing prep; §6 steps 7–8).

**Entry / exit.** The hearing date confirms (deadline register) → HEARING-PREP; the N2 card
"Prepare for your hearing". Exit: hearing-day card (pack ready, rehearsed) → COURT (physical)
→ N7.

**Content blocks.**

- Checklist: what to bring (each item tickable — tick state stored on the pack), how many
  copies, when to arrive, what to wear.
- Etiquette: how to address the judge, where to stand, when to speak — from the jurisdiction
  pack (M9), never invented.
- Opening script in the user's own words, speakable: "When you stand up, say: 'Good morning,
  my name is …, I am the claimant.'"
- Likely bench questions with the prepared answers; what the other side will say with the
  answers (from N5's sheet); cross-examination plan; objection cheat-sheet; "if you are
  surprised" fallback line.
- Rehearsal (mock hearing): guided text run — the simulated bench asks, the user answers in
  a text box, feedback comes back per answer. Transcript saved to the dossier. v1 is
  text-only.

**States.** Loading skeleton; empty: "Your hearing pack appears once the hearing date is
set." Error: stale marker. Permission: pack read for all matter members; rehearsal runs are
the user's own (a lawyer can read them — pilot supervision). Rehearsal mid-state: one
question, one answer box, "next" — the same one-thing-at-a-time rule as N1.

**API reads and commands.** `GET /api/v1/matters/{mid}/hearing-pack` → sections + checklist
state + `rehearsals[]` (§16) · `POST /api/v1/matters/{mid}/mock-hearing` → 202 {rehearsal_id}
(§16) · answers post to the rehearsal resource.

**Firm vs self-rep.** Firm: the pack sections are a briefing checklist; bench questions carry
authority refs; rehearsal optional. Self-rep: rehearsal is the primary action until done.

**Copy rules.** Scripts are first-person and speakable; physical instructions ("where to
stand", "when to stand") come from the jurisdiction pack — this spec never invents courtroom
procedure.

**Accessibility.** Real checkboxes with labels; scripts as selectable text with a copy
button (the TUI copy-anywhere carry-over, 05 §13); rehearsal answers in labelled textareas;
no timed anything — the user paces the rehearsal.

## 10. N7 — Debrief card

**Purpose.** Same-day capture of what happened at court; ingest the orders; show the
prediction-vs-outcome diff honestly (§3.2 Debrief; the step that makes the product a loop).

**Entry / exit.** The hearing-day card; N2 card that day. Exit: court event logged →
re-strategy runs → N4 approval of vN+1.

**Content blocks.**

- Guided questions (debrief questionnaire), dynamic per the current strategy: "What did the
  judge say about {issue}?" · "Were any orders made? What exactly do they say?" · "What is
  the next date, if one was given?" · "Did you hand over the documents we listed?"
- Upload: the minute / order / anything received at court — "Photograph them if you have no
  scanner" (ingest via 04 §5.3; the extracted orders and new deadlines come back as chips).
- After submit, the diff shown back, always including misses: "We predicted the judge would
  order payment immediately. The court ordered payment within 14 days. Your plan changes in
  these ways: …" (the honesty §11 requires — simulation is not a court).

**States.** Loading skeleton; not-yet state: the card exists only once a hearing date exists
(otherwise the timeline node is greyed). Error on submit: answers preserved client-side +
retry; nothing lost (N1's rule). Permission: the pilot supervising lawyer may complete the
card for the user — same endpoint, the actor is recorded. Partial answers draft-save
automatically.

**API reads and commands.** `GET /api/v1/matters/{mid}/debrief/questions` (§16) ·
`POST /api/v1/matters/{mid}/debrief {answers, doc_ids?}` → 202 {court_event} (§16; M5 owns
the re-strategy dispatch that follows — SSE `debrief.completed` is the UI's confirmation) ·
`GET /api/v1/matters/{mid}/predictions` (the diff source).

**Firm vs self-rep.** Firm: the lawyer fills it; raw minute text visible alongside; the diff
renders numeric. Self-rep: the guided questions + the plain diff paragraph.

**Copy rules.** Neutral about being wrong — state what was predicted, what happened, what
changes; never "unfortunately" or "sadly".

**Accessibility.** Questions grouped by topic as labelled fields; upload keyboard-operable;
the diff reads as text pairs ("We predicted … The court ordered …"), not a graphic; submit
disabled-with-reason until required answers exist (which ones are named).

## 11. N8 — Deadline calendar

**Purpose.** Every kernel-computed deadline with its reminder ladder and its "what happens if
missed" line — the deadline sentinel made visible (§3.4).

**Entry / exit.** N2 rail; a tab; any deadline row → the task it belongs to.

**Content blocks.** **List is primary** (05 density), month view supplementary. Each row:

```text
⏱ File the statement of claim          20 November 2026 (in 16 days)   District Court   OK
   Reminders: 7, 3 and 1 day before — and on the morning
   If missed: the other side can ask the court to strike out your claim   [details]
```

- Status word + icon: OK · Due soon · Overdue ⚠ (never colour alone).
- Every deadline is kernel-computed (D-P5); the row's details reveal which rule produced it
  ("how we worked this out" — the defensibility discipline, plain-worded).
- Export: "Add to my calendar" (.ics, local file — no cloud; M9 for the export build).
- Reminder ladder text is per-row (7/3/1 default; the pack can vary it).
- "Something looks wrong?" on every row → an info request to the case-manager (04 §5.6
  requests): the user never edits a computed date — they question it, and the system loop answers.

**States.** Loading skeleton; empty: "No deadlines yet. They appear when your plan is
approved." Error: kernel recompute failed → stale marker + "Last checked {time}". Permission:
read for all matter members; there is no date-editing affordance at any self-rep role.
Overdue: the row flags ⚠ and N2 takes over with the re-strategy path (§3.4 — a missed
deadline triggers re-strategy immediately).

**API reads and commands.** `GET /api/v1/matters/{mid}/deadlines?cursor=` (§16) ·
`GET /api/v1/matters/{mid}/deadlines.ics` (M9) · `POST /api/v1/matters/{mid}/requests
{kind:"info", question}` (04 §5.6) · SSE `deadline.added`, `deadline.state_changed`.

**Firm vs self-rep.** Firm: kernel provenance per row is the default view; bulk export of the
register; fee/form columns appear when the jurisdiction pack supplies them.

**Copy rules.** Miss lines are factual, not frightening: "If you miss this date, the other
side can ask the court to strike out your claim."

**Accessibility.** Dates in text (the list is the accessible form; the month view is
supplementary); status word + icon; rows keyboard-focusable with details expandable; the
.ics action is a real button announcing its result.

## 12. N9 — Plain-language toggle

**Purpose.** Every output also available in plain English; ON by default in self-rep (§9A.1).

**Entry / exit.** The S1 header control (whole-session default); a per-output toggle on the
long documents (N4 plan, N5 report, N7 diff, N11 judgment explainer).

**Content / behaviour.** The plain version and the legal version are **two stored fields of
the artifact**, produced at generation time (the plain-language-explainer agent, §5) and put
through the same gate. The toggle is a render choice between stored fields — never a live
translation call (that would put un-reviewed text in front of a non-lawyer). Self-rep default:
plain primary, legal secondary behind "Show the legal version". Firm default: legal primary.

**States.** Missing plain version (older artifact): "Plain version not available for this
document" + the legal version shown; regeneration is part of artifact production (M5), not a
UI affordance.

**API reads and commands.** None — render layer (§9A.2). The artifact schema carries both
fields; that schema note belongs to doc 07 (M5).

**Firm vs self-rep.** The direction of the default is the whole difference; both texts exist
in both modes.

**Accessibility.** Toggle labelled "Reading level: Plain / Legal"; switching preserves focus
position; the visible version is the one in the accessibility tree.

## 13. N10 — "Get a lawyer now" banner

Specified in §2 (triggers, detector states, exact copy, blocking semantics, firm flag).
Screen-level additions: the banner is component N10 and appears on **every** self-rep screen
while `active` (pinned, non-scrolling, §2); `flagged` renders as a soft banner that can be
dismissed for the session but reappears on navigation. In firm mode the flag renders on the
workspace header and the Board row (05 §2 risk-flag column) with the identical reason text
from §2. The "I have a lawyer now" action and the trigger-clearing rule are §2 — the only two
exits.

## 14. N11 — Judgment, enforce, appeal, settle (M9)

**Purpose.** After judgment: explain it plainly, show the real options with their deadlines,
and carry the user through enforcement, appeal or settlement (§3.2; §6 step 11).

**Entry / exit.** Judgment ingested → JUDGMENT; the N2 card "The decision is in". Exit: the
chosen option runs through an S7 approval card (enforcement pack / appeal pack / settlement
deed are irreversible-class acts) → the chosen path → N12.

**Content blocks.**

- Judgment explainer (N9 pair): what the court decided · what it means for you · what you
  must do now. Any order binding on the user re-checks the N10 triggers (trigger 6).
- Options, each a labelled radio option with its description — **"Do nothing" is a listed
  option with its consequence stated** (a win left unenforced stays unpaid; the appeal window
  lapses on its date):
  - **Enforce** — "You won. You are owed {amount}. You are not paid yet. Getting paid usually
    needs another step." Enforcement options from the jurisdiction pack (wage deduction,
    attachment order…), each with cost/time/risk.
  - **Appeal** — the kernel-computed window in both date forms, and the merits summary ("what
    we would argue, how strong it looks, and why").
  - **Settle** — terms list with per-term status and payment tracking (each payment ticked
    when received and reconciled — by the system, not by hand).
- Appeal-window-lapsed state: the option renders disabled-with-reason — "The appeal deadline
  passed on {date}" — never hidden.

**States.** Loading skeleton; pre-judgment: the screen is not reachable (the timeline node
"Getting results" is greyed until JUDGMENT); error: stale marker; permission: choosing is
`approval.decide`-gated in both modes (05 §12).

**API reads and commands.** **M9** (recorded as proposed in §16; shapes indicative now):
`GET /api/v1/matters/{mid}/judgment-analysis` · `GET /api/v1/matters/{mid}/post-judgment` →
{options, appeal_window, enforcement, settlement} · the choice itself posts to the approval
machine (04 §5.6) — no separate decision endpoint.

**Firm vs self-rep.** Firm: full judgment text with analysis anchors and authority refs;
costs schedules dense. Self-rep: the explainer + the radio options above.

**Copy rules.** Honesty in both directions: winning copy says "not paid yet"; losing copy
states the window and what lapses when it closes.

**Accessibility.** Options as a real radio group, each with its description read; the window
countdown as text (not a ticking widget); settlement terms as a table with headers.

## 15. N12 — Closure checklist

**Purpose.** Confirm nothing is left open before the case archives, and start the retention
clock (§3.2 Closed).

**Entry / exit.** Closure eligibility (appeal window lapsed · payment received ·
discontinuance filed — §3.2); the N2 card. Exit: archived (read-only), retention clock set.

**Content blocks.**

- Checklist: appeal window lapsed (or the date it lapses) · all orders complied with ·
  payment received and reconciled · no open approvals · documents exported if wanted · what
  happens after closure (read-only archive; retention period from the jurisdiction pack; how
  to get a copy later).
- System-checked items are ticked by the system and **disabled** — the user cannot tick a
  system check; user-checked items are the user's own attestations, logged as such.
- Closing summary: generated on confirm (the plugin's closing-summary seed, ported); shown on
  screen and downloadable.
- Confirm → an S7 approval card naming the consequence ("After closure the case becomes
  read-only") — closure is irreversible-class, so it rides the approval machine (05 §7).

**States.** Loading skeleton; not-eligible: "You can close your case when:" + the remaining
items with what produces each; error: stale marker; permission: confirm requires
`approval.decide` in both modes; post-closure the screen becomes the read-only closing
summary; reopen is a matter state transition (04 §5.2) permission-gated — self-rep sees it
disabled-with-reason.

**API reads and commands.** `GET /api/v1/matters/{mid}/closure-checklist` (§16) ·
`POST /api/v1/matters/{mid}/close {note?}` → 202 {approval} (§16 — closure creates the
approval; the archived state lands via 04 §5.2 `POST /matters/{mid}/state`) ·
SSE `lifecycle.stage_changed`.

**Firm vs self-rep.** Firm: adds the retention/licence review step; the lawyer confirms.
Self-rep: the checklist above, plain copy throughout.

**Copy rules.** Data honesty, stated once, plainly: "Keep your downloaded copies. After
{retention end date} we cannot recover them."

**Accessibility.** Checklist items are real checkboxes; system items disabled with a reason
string; the confirm button carries the consequence text as its accessible description.

## 16. Proposed lifecycle API (M7)

**Conventions inherit 04 §4 verbatim:** base `/api/v1`; JSON; ISO-8601; text ids; the shared
error envelope (`{error: {code, message, details, trace_id}}`); cursor pagination on
collections; long-running commands return **202 + a resource**, never block; every read is
matter-scoped after authz. Schemas below are representative shapes; entity fields (CaseEvent,
StrategyVersion, Proposal, Prediction, Deadline, Flaw) are **M5's doc-07 addendum** (NEXT_STEPS
§3.3) — where this catalogue and doc 07 disagree at build time, doc 07 wins and this section
is corrected.

```
GET   /api/v1/matters/{mid}/lifecycle            → {stage, entered_at, history[], next_allowed[]}
GET   /api/v1/matters/{mid}/next-actions         → paged NextAction[]
POST  /api/v1/matters/{mid}/next-actions/{aid}/complete {note?} → 202 {NextAction}
GET   /api/v1/matters/{mid}/dossier/facts        → FactsRegister (+ missing-field projection)
POST  /api/v1/matters/{mid}/dossier/facts        {field updates} → 202
GET   /api/v1/matters/{mid}/intake/questions     → {current, sections_done, sections_total}
POST  /api/v1/matters/{mid}/intake/answers       {question_id, answer, doc_ids?} → 202
GET   /api/v1/matters/{mid}/strategy             → paged StrategyVersion[]
GET   /api/v1/matters/{mid}/strategy/{v}/diff    ?against={w} → {changes[], reasons[], failed_predictions[]}
GET   /api/v1/matters/{mid}/predictions          → paged Prediction[]
GET   /api/v1/matters/{mid}/flaws                ?state=&severity=&cursor= → paged Flaw[]
GET   /api/v1/matters/{mid}/hearing-pack         → {sections, checklist, rehearsals[]}
POST  /api/v1/matters/{mid}/mock-hearing         → 202 {rehearsal_id}
GET   /api/v1/matters/{mid}/debrief/questions    → [DebriefQuestion]
POST  /api/v1/matters/{mid}/debrief              {answers, doc_ids?} → 202 {court_event}
GET   /api/v1/matters/{mid}/deadlines            → paged Deadline[]
GET   /api/v1/matters/{mid}/deadlines.ics        → text/calendar            # M9
GET   /api/v1/matters/{mid}/lawyer-now           → {state: clear|flagged|active, triggers[], help[]}
      # the detector itself is M5 (§3.4); this is the thin read the screens consume
GET   /api/v1/matters/{mid}/closure-checklist    → {items[], eligible}
POST  /api/v1/matters/{mid}/close                {note?} → 202 {approval}
```

M9 additions (recorded now so N11/N12 have their reads named; shapes indicative):

```
GET   /api/v1/matters/{mid}/judgment-analysis    → JudgmentMemo (plain + legal pair)
GET   /api/v1/matters/{mid}/post-judgment        → {options[], appeal_window, enforcement[], settlement[]}
```

**SSE** — new event types on the existing `channels=matter:{mid}` (04 §5.7 envelope,
`Last-Event-ID` replay, 15 s heartbeat): `intake.progress` · `lifecycle.stage_changed` ·
`next_action.changed` · `flaw_ledger.updated` · `debrief.completed` · `deadline.added` ·
`deadline.state_changed` · `lawyer_now.changed`.

**What this catalogue deliberately omits** (matching 04 §6's discipline): no client-write to
kernel outputs (deadlines, limitation dates — corrections go through the info-request flow,
04 §5.6); no direct flaw-ledger edits (the ledger is agent-written, keep-if-better governed);
no chat-with-the-case endpoint (counsel chat is S6's, 04 §5.8).

## 17. Accessibility (feeds gate D-6)

Standard: **WCAG 2.2 AA**, audited before Release A (§9A.3 D-6). Rolled up from the
per-screen notes:

- **Keyboard-complete:** intake, rehearsal, debrief and every approval flow fully operable
  without a mouse; exactly one primary tab-stop per card (N2).
- **Status is word + icon, never colour alone** (05 §0): deadlines, flaw severities, journey
  stages, check chips.
- **Screen-reader structure:** the journey timeline is an ordered list; every status chip and
  state is labelled; the lawyer-now banner is `role="alert"`, takes focus once, reads first.
- **Focus:** stays on the active question (N1, N6 rehearsal, N7); preserved across the N9
  toggle; the debrief diff reads as text pairs, not a graphic.
- **Forms:** every input labelled; errors tied via `aria-describedby`; submit
  disabled-with-reason naming what is missing (N7), never silently dead.
- **Motion:** ≤ 150 ms everywhere; `prefers-reduced-motion` suppresses the rest (05 §0).
- **Contrast:** checked in both themes at D-6.
- **Print:** hearing pack, "their arguments & your answers" sheet, deadline list and the
  closing summary print cleanly (05 §11 — paper still travels to court).
