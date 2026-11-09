import { describe, expect, it } from "vitest";
import { DEADLINE_WORD, JOURNEY_STRIP, debriefGroups, LAWYER_NOW_COPY, LAWYER_NOW_SHORT, STAGE_PLAIN, flawVerdict, predictionLine, stripIndex }
  from "./screens/CaseScreens.jsx";
import { plainKind } from "./screens/Approvals.jsx";

// D-7: approval titles are words in both modes; requests come as `info_request:<kind>`
describe("approval titles", () => {
  it("never show a raw kind id for a request", () => {
    expect(plainKind("info_request:info", true)).toBe("We need something from you");
    expect(plainKind("info_request:info", false)).toBe("Information request");
    expect(plainKind("filing", false)).toBe("Filing approval");
  });
});

// D-7: the N2 journey strip (mockup B) folds the 19 states into 8 slots, in chain order
describe("N2 journey strip", () => {
  it("covers every §3.1 state exactly once, in chain order", () => {
    expect(JOURNEY_STRIP.flatMap(([, states]) => states)).toEqual(Object.keys(STAGE_PLAIN));
  });
  it("maps a stage to its slot; no stage is slot -1", () => {
    expect(stripIndex(null)).toBe(-1);
    expect(stripIndex("INTAKE")).toBe(0);
    expect(stripIndex("FILE_SERVE")).toBe(stripIndex("PRE_ACTION"));
    expect(stripIndex("RE_STRATEGY")).toBe(stripIndex("COURT"));
    expect(stripIndex("CLOSED")).toBe(JOURNEY_STRIP.length - 1);
  });
});

describe("N7 debrief questions are grouped by topic (08 §17)", () => {
  it("places every question exactly once; an unknown id lands in the last group", () => {
    const qs = ["date", "judge_said", "orders", "next_date", "documents_handed", "costs"].map((id) => ({ id }));
    const groups = debriefGroups(qs);
    expect(groups.map(([legend]) => legend)).toEqual(["The hearing", "What the judge said", "Dates and papers"]);
    expect(groups.flatMap(([, g]) => g.map((q) => q.id)).sort()).toEqual(qs.map((q) => q.id).sort());
    expect(groups.at(-1)[1].map((q) => q.id)).toContain("costs");
  });
});

describe("board risk column uses plain lawyer-now labels", () => {
  it("has a short label for every detector rule", () =>
    expect(Object.keys(LAWYER_NOW_SHORT).sort()).toEqual(Object.keys(LAWYER_NOW_COPY).sort()));
});

// T7: N5 verdict (08 §8 — open flaws never silent), N8 status words (word + icon,
// never colour alone), N7 diff as a text pair (neutral about being wrong).
describe("N5 flaw verdict", () => {
  it("is empty when nothing was tested", () => expect(flawVerdict([])).toBe(null));
  it("passes when every flaw is fixed", () =>
    expect(flawVerdict([{ flaw_id: "f1", severity: "critical", status: "fixed" }])).toBe("Passed"));
  it("names open minor flaws", () =>
    expect(flawVerdict([{ flaw_id: "f1", severity: "minor", status: "open" }])).toBe("Passed with open flaws"));
  it("blocks on an open critical or material flaw", () =>
    expect(flawVerdict([{ flaw_id: "f1", severity: "material", status: "open" }]))
      .toBe("Not passed — open flaws must be fixed before anything is sent"));
});

describe("N8 deadline status words", () => {
  it.each([["ok", "OK"], ["due_soon", "Due soon"], ["overdue", "Overdue ⚠"]])("%s → %s", (s, w) =>
    expect(DEADLINE_WORD[s]).toBe(w));
});

describe("N7 prediction diff reads as a text pair", () => {
  it("states prediction then what the court said, no 'unfortunately'", () => {
    const line = predictionLine({ claim: "payment within 30 days",
      court_said: { judge_said: "pay within 14 days", orders: ["pay $4,500 within 14 days"] } });
    expect(line).toBe("We predicted: payment within 30 days. The court said: pay within 14 days. Orders: pay $4,500 within 14 days.");
    expect(line).not.toMatch(/unfortunately|sadly/i);
  });
  it("does not double the full stop when the claim already ends with one", () => {
    expect(predictionLine({ claim: "Judgment is entered.", court_said: { judge_said: "judgment entered." } }))
      .toBe("We predicted: Judgment is entered. The court said: judgment entered.");
  });
});

// T6 vitest gate (plan §2 T6): the N10 banner copy is byte-exact to 08 §2, and the
// N3 plain-name map covers every §3.1 state so no stage renders as a raw id.
// Existing suites: ui.test.jsx (chips/btn), api/sse/router tests — none cover 08 copy.
describe("N10 lawyer-now copy is byte-exact to 08 §2", () => {
  it("has the six trigger strings verbatim", () => {
    expect(LAWYER_NOW_COPY.criminal_exposure).toBe(
      "This may involve criminal charges. A lawyer must handle anything that could lead to criminal charges.");
    expect(LAWYER_NOW_COPY.family_safety).toBe(
      "This involves the safety or care of children. Family Court matters need a lawyer — and support services may be able to help you now.");
    expect(LAWYER_NOW_COPY.user_insolvency).toBe(
      "You may need to deal with serious debt or bankruptcy. A lawyer should guide this.");
    expect(LAWYER_NOW_COPY.claim_above_self_help).toContain("worth more than");
    expect(LAWYER_NOW_COPY.missed_limitation).toBe(
      "The time limit for this claim has passed. Only a lawyer can tell you if there is still a way forward.");
    expect(LAWYER_NOW_COPY.court_order_against_user).toBe(
      "A court has made an order against you. Get legal advice before you do anything else.");
  });
});

describe("N3 plain-name map covers every §3.1 state (statemachine.STATES)", () => {
  const STATES = ["INTAKE", "ASSESS", "STRATEGY", "PRE_ACTION", "DRAFT", "MOOT", "APPROVE",
    "FILE_SERVE", "AWAIT", "RESPOND", "HEARING_PREP", "COURT", "DEBRIEF",
    "RE_STRATEGY", "JUDGMENT", "ENFORCE", "APPEAL", "SETTLE", "CLOSED"];
  it.each(STATES)("%s has a plain name", (s) => {
    expect(STAGE_PLAIN[s]).toBeTruthy();
    expect(STAGE_PLAIN[s].length).toBeLessThanOrEqual(30);
  });
  it("matches the §3.1 chain order", () => {
    expect(Object.keys(STAGE_PLAIN)).toEqual(STATES);
  });
});
