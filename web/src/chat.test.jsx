import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Ctx } from "./App.jsx";
import { ChatDock, unanswered } from "./screens/RunPage.jsx";

// M10 T4 — counsel chat, D-3 pick C (ops dock) + A's four rail cards (design/mockups/m10-chat-c.html)
const KEYS = ["intake", "research", "strategy", "attack", "assess", "filings", "moot", "advice", "verify", "close"];
const tasks = KEYS.map((key, i) => ({ task_id: `t${i}`, seq: i, key, agent_id: "clerk",
  state: i < 6 ? "completed" : i === 6 ? "running" : "pending" }));
const run = { execution_id: "exe-2", matter_id: "m1", state: "executing", started_at: "2026-11-10T09:00:00Z",
  events: [{ id: 1, type: "task.running", task_id: "t6", ts: "2026-11-10T09:31:00Z" }] };
const msg = (id, role, text, eid) => ({ message_id: id, role, text, execution_id: eid, actor: "admin", ts: "2026-11-10T09:12:00Z" });
const messages = [msg("g1", "user", "Compare the two SSA versions", "exe-1"),
  msg("g2", "lead", "Run exe-1 completed: intake … close", "exe-1"),
  msg("g3", "user", "Now check clause 14", "exe-2")];
const approval = { approval_id: "ap-1", matter_id: "m1", execution_id: "exe-2", kind: "filing", state: "pending",
  requested_at: "2026-11-10T09:30:00Z", request_payload: {} };
const artifacts = ["a-77", "a-88", "a-92"].map((id, i) => ({ artifact_id: id, title: `Doc ${i}`, created_at: `2026-11-0${i + 1}` }))
  .concat({ artifact_id: "a-50", title: "Oldest", created_at: "2026-10-01" });

const view = (over = {}, perms = ["*"]) => renderToString(
  <Ctx.Provider value={{ perms, mode: "firm" }}>
    <ChatDock run={run} tasks={tasks} messages={messages} approvals={[approval]} artifacts={artifacts}
      interjections={[]} canSend st={{ busy: false, pending: false, error: null }} onSend={() => {}} {...over} />
  </Ctx.Provider>);

describe("unanswered (turn-based: a reply lands only when its execution completes)", () => {
  it("is every user message whose execution has no lead reply yet", () => {
    expect(unanswered(messages)).toEqual(new Set(["g3"]));
    expect(unanswered([msg("x", "user", "no run", null)])).toEqual(new Set());
  });
});

describe("ChatDock render", () => {
  it("shows the thread: You / Lead counsel, the count, and pending only under the unanswered turn", () => {
    const h = view();
    expect(h).toContain("Counsel chat — Supervision");
    expect(h).toContain("3 messages · replies land here when stages close");
    expect(h).toContain("<b>Lead counsel</b>");
    expect(h.match(/class="dot"/g)).toHaveLength(1);    // the composer hint also says "pending…"
    expect(h.indexOf('class="dot"')).toBeGreaterThan(h.indexOf("Now check clause 14"));
  });
  it("hides the composer without matter.dispatch (05 §12: hidden, not disabled)", () => {
    expect(view()).toContain("Instruction to lead counsel");
    expect(view()).toContain("Send → 202 · appears in the lanes above as pending…");
    expect(view({ canSend: false })).not.toContain("Instruction to lead counsel");
  });
  it("live line comes from the run's own events", () => {
    expect(view()).toContain("moot stage reached");
    expect(view({ run: { ...run, events: [] } })).not.toContain("stage reached");
  });
  it("inline approval reuses the Approval Center card (decide self-gates)", () => {
    expect(view()).toMatch(/class="approval__kind">⚑ (<!-- -->)?filing/);   // SSR splits JSX text nodes
    expect(view({ approvals: [] })).not.toContain("approval__kind");
  });
  it("rail: execution progress, latest 3 artifacts newest first, open approvals, honest interjections", () => {
    const h = view();
    expect(h).toContain("6 of 10 stages complete");
    expect(h).toContain("stage 7/10 (moot)");
    expect(h.indexOf("a-92")).toBeLessThan(h.indexOf("a-88"));
    expect(h).not.toContain("a-50");
    expect(h).toContain("1 ⚑ pending");
    expect(h).toContain("Approval Center");
    expect(h).toContain("None sent from this page");
    const sent = view({ interjections: [{ interjection_id: "inj-1", text: "Focus on clause 14 first.", at: "2026-11-10T09:20:00Z" }] });
    expect(sent).toContain("“Focus on clause 14 first.”");
    expect(sent).toContain("delivered at next boundary");
  });
  it("shows the backend's error instead of a success", () => {
    const h = view({ st: { busy: false, pending: false, error: { status: 403, code: "permission_denied", message: "nope" } } });
    expect(h).toContain("nope");
  });
});
