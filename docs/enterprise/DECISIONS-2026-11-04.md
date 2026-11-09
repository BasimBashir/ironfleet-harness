# DECISIONS — 2026-11-04 — Owner ruling sheet

**Status: OPEN.** Every entry below ends in an empty `Ruling:` line — fill in the option
letter/word and date it. Nothing here is code; this sheet only consolidates what the owner
must decide. It covers [NEXT_STEPS.md §10](../../../NEXT_STEPS.md) rulings **R-1..R-5** plus the
enterprise [00 §H](00-executive-summary.md) decisions **1–8** (R-2). NEXT_STEPS M2 closes when
every `Ruling:` line on this sheet is filled; until then M2 stays open.

Framing rule that binds every entry: the product's claim is **maximum defensibility**, never
"courts will accept this output". Law sources are operator-supplied (W2 ruling); NZLII ingest
is NO-GO.

---

## R-1 · Regulatory posture for self-rep mode *(blocks Release B)*

**Question:** Under the Lawyers and Conveyancers Act 2006 ("LCA"), does IronFleet's self-rep
mode fall within the lawyers' reserved areas of work, and what posture does the product adopt
as a result?

**Options (from NEXT_STEPS §10):**
- **(a)** Legal-information + document-preparation tool where the *user* decides — the tool
  never advises on the conduct of the user's proceeding; the user reviews, edits and files.
- **(b)** Lawyer-in-the-loop sign-off — every court-bound output is reviewed by a lawyer
  before filing.
- **(c)** Operate under a law firm — the product becomes a firm's internal tool or the firm
  is the regulated front end.

**Recommendation:** adopt **(a)** as the design posture now, and obtain the lawyer advice
below to confirm the boundary before Release B; keep (b) as the supervised-pilot path (it is
already a Release B requirement, §7). Reason: (a) is the only posture that scales without a
firm; the LCA text as verified points to the user-directed drafting + self-representation
exceptions (s 27(1)(a)) as the defensible lane, but the s 26 "drafts … for or on behalf of" +
"for gain or reward" question about a *paid tool* is precisely what needs professional
confirmation. Framing follows the courts' own guidance: a chatbot "cannot give tailored legal
advice" and the user "should not rely on it as [their] sole or main source of legal
information" — the product states the same limits, never more.

**What it blocks:** Release B (supervised pilot, plain-language user testing); shapes self-rep
product scope and all user-facing claims (§11: "decided before Release B, not after").

### Questions for the NZ regulatory lawyer (ask verbatim)

1. Does user-directed drafting of court/tribunal documents by a paid software tool, where the
   user reviews, edits and files the result themselves, fall within the reserved area at
   **s 6(a)** LCA ("giving legal advice … in relation to the direction [or] management of
   proceedings") — and if not, what language must the product use to stay outside it?
2. **s 26** ("drafting court documents") bans, for gain or reward, a person who is not an
   authorised person drafting/settling/revising documents "for or on behalf of" a party. When
   software generates a draft *at the user's direction* and the operator charges for the tool,
   who is the "person" drafting — the operator, the user, or neither? Does any LCA guidance
   treat software as outside "a person"?
3. Where is the **legal-information vs legal-advice line** for output that identifies and
   explains laws/principles "that might be relevant to a situation"? (The courts' non-lawyer
   guidance explicitly contemplates GenAI doing this, inaccurately.)
4. If a line is crossed, who is exposed — operator, user, or both — under **ss 21–24**
   (including s 24(1)(b), where gain is *not* required), and what is the practical exposure
   under **s 46** (penalties $50,000 natural person / $150,000 body corporate)?
5. What **liability terms and insurance** fit posture (a) — does professional-indemnity-style
   cover exist for a software-vendor posture, or is E&O only available via (b)/(c)?
6. The courts' non-lawyer guidance (7 Dec 2023) requires **disclosure of GenAI use only if the
   court/tribunal asks**. Does that hold for outputs of a *paid* tool, and should the product
   disclose anyway for defensibility?
7. **Privacy Act 2020 IPP 12 / cross-border:** may the cloud model leg serve self-rep matters
   containing the user's dispute facts, or must privileged/sensitive matters stay on local
   models? (Feeds R-4 directly.)
8. What **product claims** are permitted under **s 23** LCA (which incorporates Fair Trading
   Act s 45 misleading-representation tests) — confirm the "maximum defensibility" claim set
   and what the product must never say.

### Official sources — verified 2026-11-04 from this box

| Source | Status | Link |
|---|---|---|
| Courts of NZ — *Guidelines for use of GenAI in Courts and Tribunals: Non-lawyers*, 7 Dec 2023 (owner: AI Advisory Group; approved by Heads of Bench Committee + Tribunals Aotearoa Executive; first issued AND last updated 7 Dec 2023; 6 pp; covers litigants in person, McKenzie friends, lay advocates, employment advocates; applies to all NZ courts, the Waitangi Tribunal and the listed tribunals) | **PDF downloaded and read in full** | [courtsofnz.govt.nz PDF](https://www.courtsofnz.govt.nz/assets/6-Going-to-Court/practice-directions/practice-guidelines/all-benches/20231207-GenAI-Guidelines-Non-Lawyers.pdf) |
| Same document, duties: (1) understand limitations — chatbots "cannot give … tailored legal advice", NZ training limited, "cannot generate documents that meet the requirements of New Zealand courts"; (2) confidentiality/suppression/privacy — enter nothing not in the public domain; no private/confidential/suppressed/privileged info; contact registry if disclosed; (3) accountability — *you* are responsible, check everything before use; hallucinated cases/citations/quotes; check with a lawyer if possible; (4) bias/ethics incl. Māori and Pasifika context; (5) disclosure — **not required by default**, only if the court/tribunal asks | verified (same PDF) | (same) |
| Judicial-officer and lawyer versions of the same guidelines (same date, same page) | landing page verified; PDFs not read | listed on [courtsofnz.govt.nz](https://www.courtsofnz.govt.nz) (Going to Court → guidelines for use of generative AI) |
| NZLS — *Generative AI guidance for lawyers* + checklist, March 2024 (obligations: competence r 3; misleading r 10.9; fidelity r 13.100; supervision r 11; verify citations; confidentiality/privilege/Privacy Act IPP 12 offshore; client consent; disclose use); page updated 2026-02-24 | landing page verified this session | [lawsociety.org.nz](https://www.lawsociety.org.nz) (AI and Law Hub) |
| LCA 2006 Part 2 text — ss 6, 21, 22, 23, 24, 26, 27, 28, 29, 46 as summarised in the questions above | **verified at consolidation v22.0** (version date 2008-07-08) | [v22.0 whole Act](https://www.legislation.govt.nz/act/public/2006/0001/22.0/whole.html) |
| LCA 2006 current consolidation | **UNVERIFIED** — legislation.govt.nz refused direct fetches (HTTP 403; reader 500, two attempts); s 27(1)(b)(i) is known amended 28 Oct 2021, so the 2008 text is not assumed current. **Lawyer to confirm ss 21–27 unchanged in the current consolidation.** | [current version (landing)](https://www.legislation.govt.nz/act/public/2006/1/en/latest) |
| Lawyers: Conduct and Client Care Rules 2008 (SR 2008/214) | UNVERIFIED this session — lawyer pulls the current version at consultation | legislation.govt.nz (SR 2008/214) |
| Guidelines under revision (RNZ, July 2026: academics say the courts' GenAI guidelines need updating) | secondary report, not an official statement | treat as a flag: **re-verify the courts' guidance at use time** |

**Product duties this fixes regardless of the ruling (from the courts' guidance):** the system
must tell users their **verification duty** (check every citation, quote and fact before
filing — the product enforces with quote verification and warns it is not a sole/main source)
and their **disclosure duty** (current rule: none by default; disclose if the court/tribunal
asks — the product surfaces that rule at filing time, and any registry requirement it knows of).

**Ruling (a/b/c, plus any rider): ___________  Date: ___________**

---

## R-2 · Enterprise 00 §H decisions 1–8 *(owner sign-off on the enterprise audit's decisions)*

### D1 · Roadmap + ordering (06 §1.1)

**Question:** Approve the ten-phase roadmap and its ordering (security first; durable
execution before any frontend; eval-gated RAG last-but-one)?
**Options:** approve as ordered / re-order (specify).
**Recommendation: approve.** Two Phase-1 findings are exploitable by the agents themselves
today (00 §C.4, §G) — security cannot wait its turn.
**Blocks:** every phase; no phase starts unruled.

**Ruling: ___________  Date: ___________**

### D2 · Deny-by-default personas + guard block defaults (Phase 1)

**Question:** Ratify deny-by-default personas and guard-block defaults as shipped?
**Options:** ratify as shipped / change defaults (specify).
**Recommendation: ratify — this is ratification of already-shipped behaviour**, not a future
change. The substance of this decision **is implemented (M1, 2026-11-04)**: `65d5883`
(deny bash/webfetch/websearch/edit unless a persona grants them), `9f24821` (matter bound from
workspace only, never tool args), `cb84626` (matter resolved from a per-sync token; token-less
requests rejected), `b2716df` (guard moved into module_e; harness-owned authority file,
append-only log), `5515dbd` (provider URL overrides refused outside the scheme/host
allow-list), parity baseline `e60088e`. Hashes verified in git log today.
**Blocks:** nothing further code-wise; ratification closes 00 §H.2.

**Ruling: ___________  Date: ___________**

### D3 · Legal-pipeline halt-on-failure policy (02 §16.7)

**Question:** May the legal pipeline continue past a failed stage (e.g. drafting on missing
research), or must it halt?
**Options:** halt-on-failure / continue-with-gaps (flagged).
**Recommendation: halt-on-failure.** "Failure-continue pipelines drafting on missing research"
is a named critical risk (00 §D); a halted workflow is resumable once the durable orchestrator
lands (D4), so halting costs delay, not work.
**Blocks:** Phase 3 workflow semantics; the legal pipeline port (Phase 6).

**Ruling: halt-on-failure  Date: 2026-11-07**

### D4 · Orchestrator: SQLite-lease vs external engine (02 §16.1)

**Question:** Build the durable orchestrator on SQLite leases or adopt an external workflow
engine?
**Options:** SQLite-lease in platform.db (recommended) / external engine (Temporal, Celery,
similar).
**Recommendation: SQLite-lease.** One host, one Python service (02 §1); no new container or
runtime dependency; platform.db is already the system of record for matter/workflow/approval/
audit entities. An external engine buys distributed guarantees this single-box design does not
need yet.
**Blocks:** Phase 3 (factory → orchestrator, flag-gated), and everything downstream of durable
execution (API, frontend).

**Ruling: SQLite-lease in platform.db  Date: 2026-11-07**

### D5 · Agent-memory scoping (02 §16.6)

**Question:** May agent memory carry content across matters?
**Options:** matter-scoped memory only / global memory with a canon layer / hybrid.
**Recommendation: matter-scoped writes with an operator-curated canon layer.** Evidence: the
01 audit found the cross-matter read channel (S5); 02 §12 defines the canon content check;
the shipped memory design already carries canon in the primary `<name>-memory.md` (S7i
ruling); D-P7 set the policy direction. Global writes re-open the leak channel M1 just closed.
**Blocks:** Phase 1 guard-relocation sign-off; any agent-memory feature work.

**Ruling: matter-scoped writes + operator-curated canon layer  Date: 2026-11-07**

### D6 · FastAPI dependency + frontend stack (04 §2 · 02 §13)

**Question:** Adopt FastAPI + uvicorn as the API framework, and which frontend stack?
**Options (API):** FastAPI + uvicorn (04 §2 recommended) / stdlib `http.server` / aiohttp,
Flask, Litestar. **Options (frontend, 02 §13):** small React SPA (recommended) /
server-rendered HTML + htmx islands.
**Recommendation: FastAPI + uvicorn, React SPA.** Pydantic is already the house contract style
(gate models), so endpoint schemas reuse it; typed contracts are a stated NFR; async-native
fits the single asyncio loop; SSE primitives are mature. Stdlib is viable but re-implements
framework-tested code. React suits the swarm graph (SVG/Canvas) and dense tables; htmx is
fine for tables/approvals but the graph goes bespoke JS either way.
**Blocks:** Phase 4 (API) and Phase 5 (web workspace); brief §18 requires this sign-off before
the dependency lands.

**Ruling: API = FastAPI + uvicorn (owner yes, M7 session)  Date: 2026-11-08** · **frontend stack: React SPA (Vite build; owner pick, M8 session — over the zero-dependency vanilla-JS option) · browser E2E: Playwright (owner yes)  Date: 2026-11-09** — pinned set in [plans/2026-11-09-m8-guided-workspace.md](../../../plans/2026-11-09-m8-guided-workspace.md) §0

### D7 · UI mockup sign-off before any screen; TUI retirement at parity (05 §14)

**Question:** Confirm the rule that no screen is built before mockup sign-off, and that the
Textual TUI retires only at web parity?
**Options:** adopt / weaken (specify).
**Recommendation: adopt** — it is already the standing owner rule (2026-11-04: mockup options
shown and picked BEFORE any build; the R3 Textual TUI was built without that and its lessons
are on the record). TUI retirement stays gated on extraction + owner parity sign-off (00 §F).
**Blocks:** M8 design track from D-3 (mockups → user pick) onward; TUI/launcher retirement.

**Ruling: ___________  Date: ___________**

### D8 · Golden-case / retrieval acceptance thresholds (before Phase 8)

**Question:** Fix the numeric bars a release must clear before it ships?
**Options:** adopt the §7 bars now / set different numbers (specify) / defer to Phase 8.
**Recommendation: adopt now, at the §7 values — Release A:** citation accuracy ≥ 0.40 ·
grounding ≥ 0.60 · quote verification ≥ 0.90 · C4 supply ≥ 75%. **Release B adds:** 95% per
axis · moot-gate seeded-critical ≥ 98% · supervised pilot with a partnering lawyer · R-1
ruled · plain-language user testing. Deferring repeats the 0/30 surprise: the bar must exist
before the work that aims at it.
**Blocks:** Phase 8 (eval-gated RAG work); any Release A/B declaration.

**Ruling: ___________  Date: ___________**

---

## R-3 · Cutover ruling — old tree → gated harness (CR-6; drafted 2026-10-12, still open)

**Question:** Does any real user depend on the old tree (`..\IronFleet\legalai`) today, and
when does it switch off?
Full draft: [CUTOVER-RULING-2026-10-12.md](../CUTOVER-RULING-2026-10-12.md). Sub-questions and
recommendation from that draft:

- **Q1a:** is `case_vault/d4169ad6aa323208` real matter data to migrate, or bench? **Q1b:** is
  `data/hermes/` (41 MB) migrated or dropped? **Q1c:** is anything live in the neo4j /
  postgres / redis Docker containers? (If yes: a one-off user-run `docker` export, listed in
  the migration script header — not automated.)
- **Recommendation (as drafted): take the small shape** — a recorded decision + a migration
  script that copies Q1a's data into `matters/<ref>/` registry form; Q1b/Q1c answers decide
  the rest.
- **Switch-off criteria (all four must hold):** (1) new stack passes acceptance through R1;
  (2) one real matter runs end-to-end (ingest → gated dispatch → guarded draft →
  memory-improved persona); (3) whatever Q1a/Q1b/Q1c surface as real is migrated and
  verified; (4) the owner records the switch-off date here. Old tree stays read-only until then.
- **Riders:** **CR-7 BitLocker** — ratify `-AcceptUnencryptedStore` for dev; REQUIRE an
  encrypted store before any real matter. **CR-3 amendment** (Ollama evidence) — leave FROZEN
  (`verified=0` is honest; revisit only if a cloud-tier refusal blocks real work).
  **BATCH.md drops** — `what_if_dashboard` and `nutrient_processor` recorded out of MVP scope;
  revisit on demand.

**Blocks:** old-tree switch-off; real-matter work on the new stack; the R-ladder's meaning.

Q1a: ___________  Q1b: ___________  Q1c: ___________
Riders CR-7 / CR-3 / BATCH: ___________
**Ruling: ___________  Date: ___________  Switch-off date (when reached): ___________**

---

## R-4 · Model tier for Release A *(privileged-matter policy decides)*

**Question:** Which model tiers may serve Release A — local-only, or the approved cloud tier
per task class?
**Options:** (a) local-only (thomson1-chat mechanical-only, qwen3.8 local, bge-m3 embed,
local rerank — everything on this box); (b) cloud per task class (nvidia-nim /
nvidia-nim-tool, engine=cloud, admits full under CR-3, 128k ctx, safe_fill 0.8) for
non-privileged matters; (c) per-matter flag — cloud for bench/non-privileged, hard-local for
privileged.
**Recommendation: (c).** The routing table already supports both shapes (providers.yaml +
routing-a1.yaml are data edits, never code); `LOCAL_ONLY_TASKS` (embedding, rerank, policy)
can never route cloud — structural. What (c) adds is the **privileged-matter policy** as the
deciding artifact: a matter is flagged privileged at creation, and the flag forces local.
Whether cloud may serve *self-rep* matters is R-1 Q7, not this ruling.
**Blocks:** Release A operating posture; the per-matter cost model.

**Ruling: ___________  Date: ___________**

---

## R-5 · Pilot partner

**Question:** Which lawyer/firm reviews the Release A pilot matters?
**Options:** (a) the R-1 consulting lawyer takes the pilot-review role too — one engagement,
two deliverables (regulatory advice + pilot review); (b) a separate firm for review; (c) a
community law centre (aligns with the self-rep lane and LCA s 27(2)); (d) defer to Release B.
**Recommendation: (a)** — the R-1 engagement already builds the context a reviewer needs, and
Release B's supervised-pilot gate (§7) wants one named lawyer, not a search.
**Blocks:** Release A pilot credibility; the Release B supervised-pilot gate.

**Ruling: ___________  Date: ___________**

---

*Sheet prepared 2026-11-04 (M2). Sources verified from this box on 2026-11-04; two items
marked UNVERIFIED in R-1 (current LCA consolidation; CCC Rules 2008 current text) are for the
lawyer to confirm at consultation. No code was changed for this sheet.*
