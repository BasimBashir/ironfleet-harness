import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Ctx } from "./App.jsx";
import { ChatDock, speaker, unanswered } from "./screens/RunPage.jsx";

// Counsel chat: a floating launcher + non-modal panel. Messages are questions (answered from the
// matter's records, or a model citing them) or instructions, which come back as a proposal the
// user must confirm (owner pick 2026-11-13: hybrid answers + chat proposes, you confirm).
const KEYS = ["intake", "research", "strategy", "attack", "assess", "filings", "moot", "advice", "verify", "close"];
const tasks = KEYS.map((key, i) => ({ task_id: `t${i}`, seq: i, key, agent_id: "clerk",
  state: i < 6 ? "completed" : i === 6 ? "running" : "pending" }));
const run = { execution_id: "exe-2", matter_id: "m1", state: "executing", started_at: "2026-11-10T09:00:00Z",
  events: [{ id: 1, type: "task.running", task_id: "t6", ts: "2026-11-10T09:31:00Z" }] };
const msg = (id, role, text, eid, actor = "admin") => ({ message_id: id, role, text, execution_id: eid, actor, ts: "2026-11-10T09:12:00Z" });
const messages = [msg("g1", "user", "Compare the two SSA versions", "exe-1"),
  msg("g2", "lead", "Run exe-1 completed: intake … close", "exe-1", "lead"),
  msg("g3", "user", "Now check clause 14", "exe-2"),
  msg("q1", "user", "where are we?", null),
  msg("a1", "lead", "Run exe-2 is running at stage 7 of 10 (moot).\n\nSources: run exe-2 · stage moot", null, "counsel:records")];
const idle = { busy: false, pending: false, error: null };

const view = (over = {}, perms = ["*"]) => renderToString(
  <Ctx.Provider value={{ perms, mode: "firm" }}>
    <ChatDock run={run} tasks={tasks} messages={messages} canSend st={idle} onSend={() => {}} scope="m1" {...over} />
  </Ctx.Provider>);

describe("unanswered (a dispatched turn waits for its run's digest; a question never does)", () => {
  it("is every user message whose execution has no lead reply yet", () => {
    expect(unanswered(messages)).toEqual(new Set(["g3"]));
    expect(unanswered([msg("x", "user", "no run", null)])).toEqual(new Set());
  });
});

describe("speaker — every answer says where it came from", () => {
  it("labels records, model (with provider/model), proposals and run digests", () => {
    expect(speaker({ role: "user" })).toBe("You");
    expect(speaker({ role: "lead", actor: "counsel:records" })).toBe("Lead counsel · from matter records");
    expect(speaker({ role: "lead", actor: "counsel:model:nvidia-nim/step-5" })).toBe("Lead counsel · model answer (nvidia-nim/step-5)");
    expect(speaker({ role: "lead", actor: "counsel:proposal" })).toBe("Lead counsel · proposed change");
    expect(speaker({ role: "lead", actor: "lead" })).toBe("Lead counsel · run digest");
  });
});

describe("ChatDock — floating launcher + panel", () => {
  it("starts minimised: the launcher controls a hidden, non-modal dialog and shows the awaiting-reply count", () => {
    const h = view();
    expect(h).toMatch(/<section id="chatpanel-m1"[^>]*role="dialog" aria-modal="false"[^>]*hidden=""/);
    expect(h).toMatch(/<button type="button" class="chatfab__btn" aria-expanded="false" aria-controls="chatpanel-m1">/);
    expect(h).toContain(">Counsel chat<");
    expect(h).toContain("1 awaiting reply");
  });
  it("renders answers with their provenance and sources split out of the text", () => {
    const h = view({ defaultOpen: true });
    expect(h).toContain("Lead counsel · from matter records");
    expect(h).toContain("Run exe-2 is running at stage 7 of 10 (moot).</div>");
    expect(h).toMatch(/class="src small">Sources: (<!-- -->)?run exe-2 · stage moot/);
    expect(h.match(/class="dot"/g)).toHaveLength(1);          // only the dispatched turn awaits a digest
  });
  it("works before any run: no run prop, an explanatory empty state", () => {
    const h = view({ run: null, tasks: [], messages: [] });
    expect(h).toContain("Ask where things stand");
    expect(h).toContain("you confirm every change first");
    expect(h).not.toContain("stage reached");
  });
  it("shows a proposal as a confirm card with Not now and the named confirm button", () => {
    const h = view({ defaultOpen: true, proposal: { command: "pause", execution_id: "exe-2", title: "Pause run exe-2",
      detail: "Takes effect at the next stage boundary; stage moot finishes first.", confirm: "Confirm pause" } });
    expect(h).toContain('aria-label="Confirm: Pause run exe-2"');
    expect(h).toContain("stage moot finishes first.");
    expect(h).toMatch(/>Not now<.*>Confirm pause</s);
    expect(view()).not.toContain("confirmcard");
  });
  it("says lead counsel is answering while a question is in flight", () => {
    expect(view({ st: { ...idle, busy: true } })).toContain("Lead counsel is answering…");
  });
  it("composer invites questions and instructions; hidden when the user cannot send", () => {
    expect(view()).toContain("Ask about this matter, or tell lead counsel what to change");
    expect(view({ canSend: false })).not.toContain("Ask about this matter, or tell");
  });
  it("live line comes from the run's own events", () => {
    expect(view()).toContain("moot stage reached");
    expect(view({ run: { ...run, events: [] } })).not.toContain("stage reached");
  });
  it("shows the backend's error instead of a success", () => {
    expect(view({ st: { ...idle, error: { status: 403, code: "permission_denied", message: "nope" } } })).toContain("nope");
  });
});
