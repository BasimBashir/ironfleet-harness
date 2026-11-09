# 13 — Usability test script + findings template (gate D-5)

**Gate:** NEXT_STEPS §9A D-5 — firm mode with **2–3 lawyers**; self-represented mode with **5+
non-lawyers** on the §6 journey (a Release B requirement, §7). Findings are fixed **in the spec**
(05 / 08) first, then in the screens. **Run by the owner** — this document is the kit; D-5 stays
open until the sessions are held and the findings are triaged.

## 1. What the sessions must answer

1. Can a non-lawyer get from "I have a problem" to "I know what to do next and by when" without help?
2. Do non-lawyers understand the **stop banner** (lawyer-now) — that advice stops, the case stays
   open, and where free help is — and do they act on it?
3. Do they read "what we predicted / what the court said" correctly, and trust the plan less or more?
4. Can a lawyer triage the board, approve with an understanding of the consequence, and audit who
   did what — faster than the TUI?
5. Where does plain language fail (words, numbers, dates, legal terms left in)?

## 2. Ethics and consent (read before recruiting)

- Everything is **synthetic**: the harbour-freight case and the small-claim scenario below are
  fictional; participants never enter a real matter, real names or real documents.
- Nothing in the session is legal advice; say so at the start and the end.
- Written consent to take part and to record screen + audio; recordings kept for the analysis
  only, deleted after the findings are triaged; participant ids (P1…), never names, in findings.
- Participants may stop at any time; a stop is not a failed task.
- Self-rep participants: avoid anyone currently in a dispute (the content can distress).

## 3. Participants

| Group | n | Mix to aim for |
|---|---|---|
| Lawyers (firm mode) | 2–3 | litigation / debt recovery in NZ; at least one who used the TUI |
| Non-lawyers (self-rep) | 5+ | ages 18–70+; low and high digital confidence; ≥ 1 English as a second language; ≥ 1 keyboard-only or screen-reader user (NVDA / VoiceOver) |

Device: laptop or desktop, browser window ≥ 1280 px wide. **Phones/tablets are out**: the layout
does not reflow at 320 px yet (D-6 open item, doc 12).

## 4. Setup (facilitator, before each day)

Build the client and walk the journey into a kept store — this gives the **walkthrough case**
(Southern Haulage v Harbour Freight: intake done, plan v1→v3, two debriefs, dates, hearing pack)
and an archived firm matter:

```bash
cd web && npm run build && cd ..
```

```bash
.venv/Scripts/python.exe scripts/accept_m8.py --store "$TEMP/d5-day1"
```

```bash
.venv/Scripts/python.exe scripts/dev_m8.py --store "$TEMP/d5-day1" --port 8765
```

Sign in at `http://127.0.0.1:8765` as **operator / e2e-operator-pass**. Use a new `--store` dir
per day (or per participant for clean boards). Set the mode with the header toggle before the
participant sits down (firm for lawyers, **Self-rep mode** for non-lawyers).

The facilitator **plays the system** in a second window (firm mode → the matter's workspace →
Overview): "Move to …" advances the stage when a task needs it. Plan versions, predictions and
deadlines have no UI — the walkthrough case already carries them.

Prepare two synthetic files for the upload task (e.g. a typed "invoice INV-0042 Fleetwood
Plumbing $4,850" and a short "email from Fleetwood"), and print the **minute card** (§7).

Known limits to state if asked: the crew runs a labelled demo body (no real analysis);
"I have a lawyer now" is not available yet; the harbour-freight claim is over the self-help limit,
so its case shows the stop banner on every screen — that is intended.

## 5. Session script (say this)

> "Thanks for helping. We're testing the software, not you — if something is hard, that's what
> we need to know. Please think aloud: say what you're looking for, what you expect, what
> surprises you. The case is invented; nothing here is legal advice. I can't help during a task,
> but you can stop any time. Ready?"

After each task: the **SEQ** question — "Overall, how easy or hard was that? 1 (very hard) to 7
(very easy)" — then "What did you expect to happen?" At the end: **SUS** (10 items, standard
wording) and "What one thing would you change?"

## 6. Tasks — self-represented (≈ 60 min)

Scenario card for P: *"You fixed a burst pipe for Fleetwood Plumbing Ltd in March 2026. They owe
you $4,850 and have stopped answering. You want to get paid."*

| # | Task (read aloud) | Screen | Success = | Watch for |
|---|---|---|---|---|
| S1 | "Start a case about this and answer the questions." | New case → N1 | all questions answered, no help | one-question-at-a-time understood; money and date formats; "Section x of y" |
| S2 | "Add the papers you have." (two synthetic files) | N1 upload | both listed as read | finds the button; trusts "read and ingested" |
| S3 | Facilitator: "Imagine the police had mentioned this to you." P answers the police question **yes** on a new case | N10 banner | P says, unprompted, that the app stops advising and names a free-help option | panic vs clarity; whether "your case stays open" lands; reads banner first (screen reader) |
| S4 | Open the walkthrough case. "Where are you in your case, and what comes after this?" | N2 strip · N3 journey | names the current stage and the next one | plain stage names; the loops (wait → reply) |
| S5 | "What changed in your plan after the second hearing, and why?" | N4 plan | states v2→v3 change + reason in own words | finds "See what changed"; reads the failed prediction pair |
| S6 | "When is your next date, and what happens if you miss it?" | N8 dates | date + consequence correct | "in N days" vs date; status words |
| S7 | "One of the dates looks wrong to you. Tell us." | N8 "Something looks wrong?" | request sent | does P look for an edit control; trusts "we will answer" |
| S8 | "Get ready for the hearing — practise it." | N6 | starts a practice hearing | expectation of a real rehearsal (not built: note the reaction) |
| S9 | Hand over the **minute card**. "You've just been to court. Tell us what happened." | N7 debrief | submitted; P restates "we predicted … the court said …" correctly | date field; groups; "answers save as you type" believed; neutral wording read as neutral |
| S10 | "Is anything in the case worrying you right now?" | any | P mentions the stop banner and the open risk | — |

## 7. Minute card (print)

> *Hearing 9 November 2026, Disputes Tribunal (fictional). The referee said the work was done and
> the invoice is owed. Order: Fleetwood Plumbing Ltd must pay $4,850 within 14 days. No next date.*

## 8. Tasks — firm mode, lawyers (≈ 45 min)

| # | Task | Screen | Success = | Watch for |
|---|---|---|---|---|
| F1 | "Which matter needs you first, and why?" | S2 board | picks the Needs-you matter, says why | chips, state words, risk column wording, j/k |
| F2 | "Open a new matter, add these documents, and get the crew started on recovering the debt." | new · Documents · Overview | uploaded + dispatched | dispatch wording; "Pending…" vs done |
| F3 | "Something is waiting for your approval. Decide it." | S7 approvals | approves after reading "What happens" | reads the consequence before the confirm; moot verdict visible enough? |
| F4 | "A client asked a question in the app. Answer it." | S7 info request | answered | finds it; "Provide" wording |
| F5 | "Show me what each stage of the last run did." | Work plan → run drawer / page | finds stages + summaries | drawer vs page; pause/cancel/redirect discoverability |
| F6 | "Who approved the filing, and when?" | Audit / Decisions | correct actor + time | trust in the audit chain view |
| F7 | "Move this case to the next stage." | Overview "Move to …" | moved | which stages are offered and why |
| F8 | "Jump to the approvals and back to a matter without the mouse." | ⌘K | done keyboard-only | palette discoverability |
| F9 | (TUI users) "What could you do in the TUI that you can't do here?" | — | — | feeds doc 14 |

## 9. Measures

- **Task outcome:** success unaided · success with one hint · fail/abandon. **Time on task.**
- **SEQ** per task (1–7); **SUS** per participant (target ≥ 68; report the mean and range).
- **Comprehension** (S3, S5, S6, S9): the participant's own-words restatement scored correct /
  partly / wrong against the screen's content.
- **Severity** of each problem: 0 not a problem · 1 cosmetic · 2 minor (slows) · 3 major (fails or
  misleads) · 4 critical (unsafe: misreads a deadline, ignores the stop banner, approves without
  understanding the consequence).

## 10. Findings template

One row per problem (merge duplicates; count how many participants hit it).

| ID | Group | Task | Screen | What happened (verbatim quote if any) | n / N | Severity 0–4 | Spec / WCAG ref | Proposed change (spec first) | Status |
|---|---|---|---|---|---|---|---|---|---|
| D5-01 | self-rep | S3 | N10 | | /5 | | 08 §2 | | open |
| D5-02 | | | | | | | | | |

Per-participant sheet (one each):

| P | Group | Device / AT | SUS | S/F tasks: outcome · time · SEQ | Notes |
|---|---|---|---|---|---|
| P1 | | | | | |

## 11. After the sessions

1. Triage: every severity 3–4 is fixed **in the spec** (08 for self-rep screens, 05 for firm)
   before any screen change; 1–2 are batched.
2. Record the outcome in NEXT_STEPS §9A D-5 with the date, n per group, SUS means and the finding
   ids; link the filled template.
3. The Release B decision (§7) needs the self-rep results: comprehension of S3 and S9 must be
   correct for every participant, or the copy changes and the affected tasks are re-tested.
