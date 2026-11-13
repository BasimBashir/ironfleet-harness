import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { StageList, SwarmView, currentTask, durations, nodeView, parkedTask, stageOf, swarmLanes } from "./screens/RunPage.jsx";

// the real 10-stage legal pipeline (data/module-e/legal_pipeline.yaml), as GET /executions/{eid}/tasks returns it
const KEYS = [["intake", "ingestor"], ["research", "hunter"], ["strategy", "strategist"], ["attack", "adversary"],
  ["assess", "evaluator"], ["filings", "clerk"], ["moot", "clerk", "filing"], ["advice", "clerk"],
  ["verify", "citation"], ["close", "auditor"]];
const plan = (doneUpTo, running = null) => KEYS.map(([key, agent_id, approval_kind], i) => ({
  task_id: `t${i}`, seq: i, key, agent_id, approval_kind: approval_kind || null, instruction: `do ${key}`,
  state: i < doneUpTo ? "completed" : i === running ? "running" : "pending", attempts: 1, max_attempts: 2,
  result_summary: i < doneUpTo ? `${key} done` : null,
}));

describe("swarm lanes (D-3 pick: B's lanes)", () => {
  it("groups the legal pipeline into the mockup's five lanes, in seq order", () => {
    const lanes = swarmLanes(plan(0));
    expect(lanes.map((l) => l.name)).toEqual(["Intake", "Research", "Strategy & attack", "Filings & moot", "Advice & close"]);
    expect(lanes.map((l) => l.tasks.length)).toEqual([1, 1, 3, 2, 3]);
  });
  it("renders any compiled plan: unknown keys get a lane of their own, no invented branches", () => {
    const lanes = swarmLanes([{ task_id: "a", seq: 1, key: "pack-assemble" }, { task_id: "b", seq: 0, key: "pack-bench" }]);
    expect(lanes.map((l) => [l.name, l.tasks.map((t) => t.task_id)])).toEqual([["Pack bench", ["b"]], ["Pack assemble", ["a"]]]);
  });
});

describe("node state words", () => {
  it("maps task states to the mockup's classes and words", () => {
    expect(nodeView({ state: "completed" })).toEqual(["ok", "✓ Done"]);
    expect(nodeView({ state: "running" })).toEqual(["run", "● Running"]);
    expect(nodeView({ state: "pending" })).toEqual(["idle", "○ Not started"]);
    expect(nodeView({ state: "failed" })).toEqual(["bad", "✕ Failed"]);
    expect(nodeView({ state: "completed" }, true)).toEqual(["wait", "⏸ Awaiting your approval"]);
  });
  it("flags only the approval stage that parked a waiting run", () => {
    expect(parkedTask(plan(7), "waiting_human")).toBe("t6");
    expect(parkedTask(plan(7), "executing")).toBe(null);
    expect(parkedTask(plan(3), "waiting_human")).toBe(null);
  });
  it("counts the current stage, 1-based; a finished plan is N of N", () => {
    expect(stageOf(plan(5, 5))).toBe(6);
    expect(stageOf(plan(10))).toBe(10);
    expect(stageOf([])).toBe(0);
  });
  it("derives a stage's time from its own run events only", () => {
    const ev = [{ type: "task.running", task_id: "t0", ts: "2026-11-10T10:00:00Z" },
      { type: "task.completed", task_id: "t0", ts: "2026-11-10T10:02:04Z" },
      { type: "task.running", task_id: "t1", ts: "2026-11-10T10:02:05Z" }];
    expect(durations(ev)).toEqual({ t0: 124000 });
  });
});

const run = { execution_id: "exe-1", matter_id: "m1", state: "waiting_human", input_task_text: "go" };
const view = (over = {}) => renderToString(<SwarmView run={run} tasks={plan(7)} tokens={{ total: { all: 132400 }, agents: [{ agent: "hunter", all: 61000 }] }}
  canAct st={{ busy: false, pending: false, error: null }} cmd={() => {}} {...over} />);

describe("SwarmView render", () => {
  it("shows the header line, the lanes and the parked flag", () => {
    const h = view();
    expect(h).toContain("exe-1 · stage 8 of 10 · 132.4k tokens");
    expect(h).toContain('aria-label="Agent runs by stage, left to right"');
    expect(h).toContain("Clerk · moot ⚑");
    expect(h).toContain("⏸ Awaiting your approval");
    expect(h).toContain("61.0k");                       // the agent's ledger, not an invented number
  });
  it("hides pause/cancel/redirect/interject without matter.dispatch (05 §12: hidden, not disabled)", () => {
    const h = view({ canAct: false });
    for (const word of [">Pause<", ">Cancel<", ">Redirect<", "Interject"]) expect(h).not.toContain(word);
    expect(view({ run: { ...run, state: "executing" } })).toContain(">Pause<");
    expect(view()).not.toContain(">Pause<");              // parked at an approval: decided, not paused
  });
  it("numbers stages by position, not seq (the orchestrator's seq starts at 1)", () => {
    const h = view({ tasks: plan(7).map((t) => ({ ...t, seq: t.seq + 1 })), sel: "t6" });
    expect(h).toContain("exe-1 · stage 8 of 10");
    expect(h).toContain("Clerk · moot ⚑ · stage 7 of 10");
  });
  it("says pending until the confirming event, never success", () => {
    const h = view({ st: { busy: false, pending: true, error: null } });
    expect(h).toContain("Pending… waiting for the worker to confirm.");
  });
  it("offers Resume, not Pause, on a paused run; no controls on a finished one", () => {
    expect(view({ run: { ...run, state: "paused" } })).toContain(">Resume<");
    const done = view({ run: { ...run, state: "completed" }, tasks: plan(10) });
    expect(done).not.toContain(">Pause<");
    expect(done).not.toContain(">Cancel<");
  });
});

describe("drawer stage list (A: collapsible stages)", () => {
  const list = (over = {}) => renderToString(<StageList tasks={plan(5, 5)} runState="executing" byAgent={{}}
    canAct live onRedirect={() => {}} force={null} {...over} />);
  const opens = (h) => (h.match(/<details open=""/g) || []).length;
  it("opens only the current stage: the parked approval stage, else the first unfinished", () => {
    expect(currentTask(plan(5, 5), "executing")).toBe("t5");
    expect(currentTask(plan(7), "waiting_human")).toBe("t6");
    expect(currentTask(plan(10), "completed")).toBe(null);
    expect(opens(list())).toBe(1);
    expect(list()).toMatch(/<li aria-current="step"><details open=""><summary>.*?<b>filings<\/b>/);
  });
  it("Expand all / Collapse all override the default", () => {
    expect(opens(list({ force: { open: true, n: 1 } }))).toBe(10);
    expect(opens(list({ force: { open: false, n: 2 } }))).toBe(0);
  });
  it("keeps finished output in the DOM and Redirect gated by matter.dispatch", () => {
    expect(list()).toContain("intake done");
    expect(list()).toContain(">Redirect<");
    expect(list({ canAct: false })).not.toContain(">Redirect<");
  });
});
