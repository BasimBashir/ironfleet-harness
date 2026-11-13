import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Ctx } from "./App.jsx";
import { forPath } from "./useApi.js";
import { WaitingOnYou, boardOrder } from "./screens/Board.jsx";
import { ApprovalCard } from "./screens/Approvals.jsx";
import { MatterContext, MatterUnavailable, OverviewSummary, nextDeadline } from "./screens/Workspace.jsx";
import { Deadlines } from "./screens/CaseScreens.jsx";

// UX-1 (NEXT_STEPS §9B.1): command centre + matter hierarchy. Fixtures are shaped exactly as the
// API returns them: GET /approvals (catalog.list_approvals), /matters/{mid} (matters._matter_dict),
// /lifecycle (lifecycle_api.lifecycle), /deadlines, /next-actions, /runs, /documents, /dossier/facts.
const ok = (data) => ({ data, error: null, loading: false, stale: false });
const loading = { data: undefined, error: null, loading: true, stale: false };
const failed = { data: undefined, error: { status: 500, code: "http_error", message: "HTTP 500" }, loading: false, stale: false };
const R = (el) => renderToString(el).replaceAll("<!-- -->", "");  // drop SSR text-boundary markers

const approvals = [
  { approval_id: "ap-1", matter_id: "m-1", kind: "review", requested_at: "2026-11-13T09:00:00Z",
    request_payload: { result_summary: "Draft statement of claim ready for review" } },
  { approval_id: "req-2", matter_id: "m-2", kind: "info_request:info", requested_at: "2026-11-13T08:00:00Z",
    request_payload: { question: "Upload the signed engagement letter" } },
];

describe("useApi forPath — no cross-matter bleed", () => {
  const st = { path: "/matters/m-1", data: { title: "A v B" }, error: null, loading: false };
  it("never hands matter A's data to a caller now reading matter B", () => {
    expect(forPath(st, "/matters/m-2")).toEqual({ data: undefined, error: null, loading: true, stale: false });
    expect(forPath(st, "/matters/m-1").data).toEqual({ title: "A v B" });
  });
  it("marks last-good values stale when a refetch fails; a first-load failure is not stale", () => {
    expect(forPath({ ...st, error: { message: "x" } }, "/matters/m-1").stale).toBe(true);
    expect(forPath({ path: "/x", data: undefined, error: { message: "x" }, loading: false }, "/x").stale).toBe(false);
  });
});

describe("board order", () => {
  it("puts Waiting-on-you matters first and keeps server order otherwise", () => {
    const rows = [{ matter_id: "a", state: "running" }, { matter_id: "b", state: "waiting_on_you" },
      { matter_id: "c", state: "draft" }, { matter_id: "d", state: "waiting_on_you" }];
    expect(boardOrder(rows).map((m) => m.matter_id)).toEqual(["b", "d", "a", "c"]);
    expect(rows[0].matter_id).toBe("a");  // input untouched
  });
});

describe("WaitingOnYou (board)", () => {
  it("lists persisted human actions with words, the matter, and a link into its Decisions tab", () => {
    const h = R(<WaitingOnYou items={approvals} titles={{ "m-1": "Acme v State" }} />);
    expect(h).toContain("Review draft");
    expect(h).toContain("Information request");          // info_request:<kind> never shows raw
    expect(h).not.toContain("info_request:info");
    expect(h).toContain("Acme v State");
    expect(h).toContain(">m-2<");                         // no title known: the id, never an invented name
    expect(h).toContain('href="#/m/m-1/decisions"');
    expect(h).toContain("Upload the signed engagement letter");
    expect(h).toMatch(/Waiting on you<span class="muted"> · 2</);
  });
  it("a waiting matter with no approval row (paused run) is listed, not hidden behind 'Nothing is waiting'", () => {
    const h = R(<WaitingOnYou items={[]} runs={[{ matter_id: "m-9", title: "Mainzeal", state: "waiting_on_you", outstanding_approvals: 0 }]} />);
    expect(h).toContain("A run is waiting — resume or cancel");
    expect(h).toContain("Mainzeal");
    expect(h).toContain('href="#/m/m-9/workplan"');
    expect(h).toMatch(/Waiting on you<span class="muted"> · 1</);
    expect(h).not.toContain("Nothing is waiting");
  });
  it("empty: one explainer line", () => {
    expect(R(<WaitingOnYou items={[]} />)).toContain("Nothing is waiting on you");
  });
  it("loading: skeleton, no count", () => {
    const h = R(<WaitingOnYou loading />);
    expect(h).toContain('aria-busy="true"');
    expect(h).not.toContain("Nothing is waiting");
  });
  it("error: actionable error line, no fabricated empty state", () => {
    const h = R(<WaitingOnYou error={failed.error} onRetry={() => {}} />);
    expect(h).toContain("Couldn&#x27;t load this");
    expect(h).toContain("Try again");
    expect(h).not.toContain("Nothing is waiting");
  });
  it("stale: keeps last values under a refresh-failed line; paged results say so", () => {
    const h = R(<WaitingOnYou items={approvals} error={failed.error} more />);
    expect(h).toContain("showing the last loaded values");
    expect(h).toContain("Review draft");
    expect(h).toContain("All 2+ in Approvals");
  });
});

const m = { matter_id: "m-1", title: "Acme v State", client_ref: "ACME-7", matter_type: "Litigation",
  jurisdiction: "NZ", confidentiality: "Privileged", state: "waiting_on_you", outstanding_approvals: 2,
  tokens_total: 1200, archived: 0, created_at: "2026-11-01T00:00:00Z", updated_at: "2026-11-12T00:00:00Z" };
const lc = ok({ stage: "DRAFT", entered_at: "2026-11-10T00:00:00Z", next_allowed: ["MOOT"],
  history: [{ to: "STRATEGY", actor: "ann", ts: "2026-11-05T00:00:00Z" }, { to: "DRAFT", actor: "ann", ts: "2026-11-10T00:00:00Z" }] });
const dl = ok({ items: [
  { deadline_id: "d1", what: "File statement of defence", due: "2026-12-01", status: "ok" },
  { deadline_id: "d0", what: "Serve notice", due: "2026-11-20", status: "due_soon" },
  { deadline_id: "dm", what: "Old one", due: "2026-10-01", status: "met" }], next_cursor: null });

describe("MatterContext (persistent header)", () => {
  it("shows identity, stage, next deadline, pending link — API fields only", () => {
    const h = R(<MatterContext m={m} mid="m-1" lc={lc} dl={dl} />);
    for (const s of ["Acme v State", "ACME-7", "Litigation", "Privileged", "Waiting on you", "draft", "Serve notice", "2 pending"])
      expect(h).toContain(s);
    expect(h).not.toContain("Old one");                    // met deadlines are history
    expect(h).toContain('href="#/m/m-1/decisions"');
  });
  it("renders explicit neutral gaps: not started / none recorded / nothing pending", () => {
    const h = R(<MatterContext m={{ ...m, state: "draft", outstanding_approvals: 0, client_ref: null, confidentiality: null }} mid="m-1"
      lc={ok({ stage: null, history: [], next_allowed: ["INTAKE"] })} dl={ok({ items: [] })} />);
    expect(h).toContain("Not started");
    expect(h).toContain("None recorded");
    expect(h).toContain("Nothing pending");
    expect(h).not.toContain("null");
  });
  it("says unavailable / loading when a read fails or is in flight — never a blank", () => {
    const h = R(<MatterContext m={m} mid="m-1" lc={failed} dl={loading} />);
    expect(h).toContain("unavailable");
    expect(h).toContain("loading…");
  });
  it("flags an overdue deadline in words", () => {
    const h = R(<MatterContext m={m} mid="m-1" lc={lc} dl={ok({ items: [{ what: "Appeal", due: "2026-11-01", status: "overdue" }] })} />);
    expect(h).toContain("⚠ overdue · Appeal");
  });
  it("picks the soonest open deadline", () => expect(nextDeadline(dl.data.items).deadline_id).toBe("d0"));
  it("links the next deadline to the Deadlines tab and reads last activity from the event log", () => {
    const h = R(<MatterContext m={{ ...m, last_activity_at: new Date().toISOString() }} mid="m-1" lc={lc} dl={dl} />);
    expect(h).toContain('href="#/m/m-1/deadlines"');
    expect(h).toContain("Last activity");
    expect(h).toMatch(/Last activity<\/dt><dd>\d+ s ago/);   // not the 1-day-old updated_at
  });
  it("a waiting matter with no approval row (paused run) points at the Work plan, never 'Nothing pending'", () => {
    const h = R(<MatterContext m={{ ...m, outstanding_approvals: 0 }} mid="m-1" lc={lc} dl={dl} />);
    expect(h).toContain("A run is waiting");
    expect(h).toContain('href="#/m/m-1/workplan"');
    expect(h).not.toContain("Nothing pending");
  });
});

describe("firm Deadlines tab reuses the N8 screen", () => {
  const dlFor = (mode) => R(<Ctx.Provider value={{ mode, perms: ["*"] }}><Deadlines mid="m-1" /></Ctx.Provider>);
  it("firm: an h2 under the matter header, no coaching h1", () => {
    expect(dlFor("firm")).toContain('<h2 id="dl-h">Deadlines</h2>');
    expect(dlFor("firm")).not.toContain("Your dates");
  });
  it("self-rep keeps its own page heading", () => expect(dlFor("self-rep")).toContain('<h1 id="dl-h">Your dates</h1>'));
});

const reads = {
  pend: ok(approvals.filter((a) => a.matter_id === "m-1")), na: ok({ items: [], next_cursor: null }), lc, dl,
  runs: ok([{ execution_id: "ex-1", state: "completed", input_task_text: "Draft the statement of claim", started_at: "2026-11-12T00:00:00Z" }]),
  docs: ok({ items: [{ doc_id: "doc-1", filename: "contract.pdf", ingest_status: "ingested", created_at: "2026-11-11T00:00:00Z" }] }),
  facts: ok({ fields: { other_party: "State of NZ" }, missing: [] }),
};

describe("OverviewSummary", () => {
  it("populated: waiting, position, deadlines, recent work, documents, parties — each linking to its tab", () => {
    const h = R(<OverviewSummary mid="m-1" m={m} {...reads}
      nextAction={<p><b>Send the pre-action letter</b></p>} />);
    for (const s of ["Review draft", "Send the pre-action letter", "Writing documents", "Moved to", "Serve notice",
      "Due soon", "Draft the statement of claim", "contract.pdf", "ACME-7", "State of NZ"]) expect(h).toContain(s);
    for (const t of ["decisions", "workplan", "documents"]) expect(h).toContain(`href="#/m/m-1/${t}"`);
    expect(h).toContain('aria-current="step"');           // lifecycle position, not colour alone
  });
  it("a paused run is waiting on you: counted, linked to its run page (resume/cancel live there)", () => {
    const h = R(<OverviewSummary mid="m-1" m={m} {...reads}
      runs={ok([{ execution_id: "ex-9", state: "paused", input_task_text: "Research s 292", started_at: "2026-11-12T00:00:00Z" }])} />);
    expect(h).toContain("Waiting on you · 2");             // 1 approval + 1 paused run
    expect(h).toContain("Paused run — resume or cancel");
    expect(h).toContain('href="#/runs/ex-9"');
    expect(h).toContain('href="#/m/m-1/deadlines"');
  });
  it("empty matter: one honest line per block, no invented values", () => {
    const empty = { pend: ok([]), na: ok({ items: [] }), lc: ok({ stage: null, history: [], next_allowed: [] }),
      dl: ok({ items: [] }), runs: ok([]), docs: ok({ items: [] }), facts: ok({ fields: {}, missing: ["other_party"] }) };
    const h = R(<OverviewSummary mid="m-1" m={{ ...m, client_ref: null }} {...empty} />);
    for (const s of ["Nothing is waiting on you on this matter", "No open next action recorded", "Not started",
      "No deadlines recorded", "No executions yet", "No documents yet", "Not recorded"]) expect(h).toContain(s);
  });
  it("loading and error per block: skeletons and retry lines, never a blank panel", () => {
    const h = R(<OverviewSummary mid="m-1" m={m} {...reads} pend={loading} runs={failed} />);
    expect(h).toContain('aria-busy="true"');
    expect(h).toContain("Couldn&#x27;t load this");
    expect(h).not.toContain("No executions yet");          // a failed read is not "empty"
  });
});

describe("permission-limited states", () => {
  it("a non-member (404) sees neither the matter nor whether it exists", () => {
    const h = R(<MatterUnavailable />);
    expect(h).toContain("Matter not available");
    expect(h).toContain("does not exist, or you are not a member");
    expect(h).toContain('href="#/board"');
  });
  it("in-matter decisions: a reader sees the request but the decide control says why it is off", () => {
    const h = R(<Ctx.Provider value={{ perms: ["matter.read"], mode: "firm" }}><ApprovalCard a={approvals[0]} /></Ctx.Provider>);
    expect(h).toContain("Draft statement of claim ready for review");
    expect(h).toContain("requires approval.decide");
    expect(h).toContain('aria-disabled="true"');
  });
});
