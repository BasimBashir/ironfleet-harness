import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { parseRoute, href } from "./router.js";
import { NODE, RunControls, StageList, SwarmView, currentTask, parkedTask, runGraph } from "./screens/RunPage.jsx";

// the real 10-stage legal pipeline (data/module-e/legal_pipeline.yaml), as GET /executions/{eid}/tasks returns it
const KEYS = [["intake", "ingestor"], ["research", "hunter"], ["strategy", "strategist"], ["attack", "adversary"],
  ["assess", "evaluator"], ["filings", "clerk"], ["moot", "clerk", "filing"], ["advice", "clerk"],
  ["verify", "citation"], ["close", "auditor"]];
const plan = (doneUpTo, running = null) => KEYS.map(([key, agent_id, approval_kind], i) => ({
  task_id: `t${i}`, seq: i, key, agent_id, approval_kind: approval_kind || null, instruction: `do ${key}`,
  state: i < doneUpTo ? "completed" : i === running ? "running" : "pending", attempts: 1, max_attempts: 2,
  result_summary: i < doneUpTo ? `${key} done` : null,
}));
// UX-3 fixtures: explicit tasks[].depends_on — the field the backend would add for parallel work (not sent today)
const dep = (task_id, depends_on, state = "pending", extra = {}) =>
  ({ task_id, seq: 1, key: task_id, agent_id: `agent-${task_id}`, instruction: `do ${task_id}`, state, depends_on, ...extra });
const HYBRID = [dep("a", [], "completed"), dep("b", ["a"], "running"), dep("c", ["a"], "failed", { result_summary: "tool timed out" }),
  dep("d", ["b", "c"])];

describe("runGraph — dependency construction (§9B.3 items 1–3, 10)", () => {
  it("today's API: a sequential chain from plan order, one stage per row of the top-down stepper", () => {
    const g = runGraph(plan(3));
    expect(g.source).toBe("plan");
    expect(g.shape).toBe("sequential");
    expect(g.edges).toEqual(KEYS.slice(1).map((_, i) => [`t${i}`, `t${i + 1}`]));
    expect(g.cols.map((c) => c.map((t) => t.task_id))).toEqual(KEYS.map((_, i) => [`t${i}`]));
    expect([g.width, g.height]).toEqual([NODE.w, 10 * (NODE.h + NODE.gy) - NODE.gy]);
    expect(g.pos.t3).toEqual({ x: 0, y: 3 * (NODE.h + NODE.gy) });
  });
  it("equal seq = concurrently claimable under the orchestrator rule: peers in one column, never chained", () => {
    const g = runGraph([{ task_id: "x", seq: 1 }, { task_id: "y", seq: 2 }, { task_id: "z", seq: 2 }, { task_id: "w", seq: 3 }]);
    expect(g.edges).toEqual([["x", "y"], ["x", "z"], ["y", "w"], ["z", "w"]]);
    expect(g.shape).toBe("hybrid");
  });
  it("explicit parallel: no edges, one column", () => {
    const g = runGraph([dep("a", []), dep("b", []), dep("c", [])]);
    expect([g.source, g.shape, g.edges.length, g.cols.length]).toEqual(["explicit", "parallel", 0, 1]);
  });
  it("explicit hybrid: fan-out then join; a column holds only stages with no path between them", () => {
    const g = runGraph(HYBRID);
    expect(g.cols.map((c) => c.map((t) => t.task_id))).toEqual([["a"], ["b", "c"], ["d"]]);
    expect(g.edges).toEqual([["a", "b"], ["a", "c"], ["b", "d"], ["c", "d"]]);
    expect(g.shape).toBe("hybrid");
    expect(g.pos.c).toEqual({ x: NODE.w + NODE.gx, y: NODE.h + NODE.gy });
  });
  it("refuses invalid data instead of drawing a guess", () => {
    expect(runGraph([dep("a", ["b"]), dep("b", ["a"])]).error).toMatch(/cycle/);
    expect(runGraph([dep("a", ["a"])]).error).toMatch(/invalid dependency/);
    expect(runGraph([dep("a", ["ghost"])]).error).toMatch(/invalid dependency/);
    expect(runGraph([dep("a", []), { task_id: "b", seq: 2 }]).error).toMatch(/missing or invalid/);   // partial metadata
    expect(runGraph([{ task_id: "a" }, { task_id: "b" }]).error).toMatch(/no dependency metadata/);
    expect(runGraph([{ task_id: "a", seq: 1 }, { task_id: "a", seq: 2 }]).error).toMatch(/share an ID/);
  });
  it("positions depend on topology only, so status updates never move a node", () => {
    expect(runGraph(plan(7)).pos).toEqual(runGraph(plan(2, 2)).pos);
    expect(runGraph(HYBRID).pos).toEqual(runGraph(HYBRID.map((t) => ({ ...t, state: "completed" }))).pos);
  });
});

describe("node state words", () => {
  it("flags only the approval stage that parked a waiting run", () => {
    expect(parkedTask(plan(7), "waiting_human")).toBe("t6");
    expect(parkedTask(plan(7), "executing")).toBe(null);
    expect(parkedTask(plan(3), "waiting_human")).toBe(null);
  });
});

const run = { execution_id: "exe-1", matter_id: "m1", state: "waiting_human", input_task_text: "go" };
const view = (over = {}) => renderToString(<SwarmView run={run} tasks={plan(7)} tokens={{ total: { all: 132400 }, agents: [{ agent: "hunter", all: 61000 }] }}
  canAct st={{ busy: false, pending: false, error: null }} cmd={() => {}} {...over} />);
const text = (h) => h.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, " ");
const nodes = (h) => h.match(/<button type="button" class="card node[^"]*"[^>]*>/g) || [];
const edges = (h) => (h.match(/data-edge="([^"]+)"/g) || []).map((s) => s.slice(11, -1).replace("&gt;", ">"));
const boxes = (h) => h.match(/style="left:[^"]*"/g) || [];
const insp = (h) => text(h.slice(h.indexOf('aria-label="Stage inspection"')));

describe("SwarmView — graph render", () => {
  it("draws one node per stage and one edge per real dependency, with the edge source stated", () => {
    const h = view();
    expect(nodes(h)).toHaveLength(10);
    expect(edges(h)).toEqual(KEYS.slice(1).map((_, i) => `t${i}>t${i + 1}`));
    expect(text(h)).toContain("Sequential — one stage after another. Dependencies come from plan order");
    expect(h).not.toContain("The team at work");          // the overview's Stages heading names this section
  });
  it("encodes status with icon + word + class: completed, waiting, parked, queued", () => {
    const h = view();
    expect(h).toMatch(/class="card node ok"[^>]*aria-label="Ingestor: Completed\. Starts first"/);
    expect(h).toMatch(/class="card node wait"[^>]*aria-label="Clerk · moot ⚑: Awaiting approval\. After filings"/);
    expect(h).toMatch(/aria-label="Clerk · advice: Queued\. After moot"/);
    expect((h.match(/<path [^>]*class="met"/g) || []).length).toBe(7);   // solid once the source finished
  });
  it("explains why a queued stage waits, and marks a failed stage", () => {
    const h = view({ run: { ...run, state: "executing" }, tasks: plan(3, 3) });
    expect(h).toMatch(/aria-label="Adversary: Running\. After strategy"/);
    expect(h).toMatch(/aria-label="Evaluator: Queued, waiting on attack\. After attack"/);
    const f = view({ run: { ...run, state: "failed" }, tasks: plan(3).map((t, i) => (i === 3 ? { ...t, state: "failed", result_summary: "boom" } : t)), sel: "t3" });
    expect(f).toMatch(/class="card node bad"[^>]*aria-label="Adversary: Failed/);
    expect(f).toMatch(/aria-label="Evaluator: Not run\. After attack"/);   // a halted run never reaches it
    expect(insp(f)).toContain("Error boom");
    expect(insp(f)).toContain("Attempts 1 of 2");
  });
  it("renders an unknown backend status as unknown, never as done", () => {
    const h = view({ tasks: plan(2).map((t, i) => (i === 2 ? { ...t, state: "teleported" } : t)), sel: "t2" });
    expect(h).toMatch(/aria-label="Strategist: Unknown status \(teleported\)/);
    expect(insp(h)).toContain("State Unknown status (teleported)");
  });
  it("renders a hybrid run from explicit dependencies", () => {
    const h = view({ run: { ...run, state: "executing" }, tasks: HYBRID, sel: "d" });
    expect(nodes(h)).toHaveLength(4);
    expect(edges(h)).toEqual(["a>b", "a>c", "b>d", "c>d"]);
    expect(text(h)).toContain("Hybrid — stages side by side in one row");
    expect(text(h)).toContain("Dependencies as recorded for this run.");
    expect(h).toMatch(/aria-label="Agent d: Queued, waiting on b, c\. After b, c"/);
    expect(insp(h)).toContain("Waiting on b, c to finish");
  });
  it("streaming update: same nodes, same edges, same positions", () => {
    const a = view({ run: { ...run, state: "executing" }, tasks: plan(3, 3) });
    const b = view({ run: { ...run, state: "executing" }, tasks: plan(4, 4) });
    expect(boxes(a)).toEqual(boxes(b));
    expect(edges(a)).toEqual(edges(b));
    expect(nodes(a)).toHaveLength(10);
  });
});

describe("SwarmView — selection and inspection (§9B.3 item 6)", () => {
  it("with nothing selected, the inspector follows the current stage and says so", () => {
    const h = view();
    expect(insp(h)).toContain("Clerk · moot ⚑ · stage 7 of 10");
    expect(insp(h)).toContain("Showing the current stage");
    expect(h.match(/aria-pressed="true"/g)).toHaveLength(2);   // the Graph view toggle + the one current node
  });
  it("a selected node shows its own agent, goal, dependencies, dependents, tokens and the per-stage gaps", () => {
    const i = insp(view({ sel: "t1" }));
    expect(i).toContain("Hunter · stage 2 of 10");
    expect(i).not.toContain("Showing the current stage");
    expect(i).toContain("Agent hunter Goal do research State Completed");
    expect(i).toContain("Depends on intake · Completed Needed by strategy");
    expect(i).toContain("61.0k");                                      // the agent's matter ledger, labelled as such
    expect(i).toContain("a per-stage count is not recorded");
    expect(i).toContain("Tool activity, findings and evidence references are not recorded per stage");
    expect(i).toContain("research done");
  });
  it("deliverables come from this run only, without claiming which stage wrote them", () => {
    const i = insp(view({ sel: "t1", artifacts: [{ artifact_id: "a1", execution_id: "exe-1" }] }));
    expect(i).toContain("1 from this run — which stage wrote each is not recorded");
    expect(insp(view({ sel: "t1" }))).toContain("Deliverables None yet from this run");
  });
  it("a deep link to a stage not in this run falls back to the current stage", () => {
    expect(insp(view({ sel: "ghost" }))).toContain("Showing the current stage");
  });
  it("keyboard basics: every node is a native button; the graph is a labelled, focusable group; the toolbar is labelled", () => {
    const h = view();
    expect(h).toMatch(/<div class="graph" tabindex="0" role="group" aria-label="Dependency graph, 10 stages\./);
    expect(h).toContain('role="toolbar" aria-label="Stage map view"');
    for (const w of ["Zoom out", "Zoom in"]) expect(h).toContain(`aria-label="${w}"`);
    for (const w of [">Fit<", ">Reset zoom<", ">List<", 'aria-label="Close stage inspection"']) expect(h).toContain(w);
    expect(h).toMatch(/<svg[^>]*aria-hidden="true"/);
  });
  it("hides redirect/interject without matter.dispatch (05 §12: hidden, not disabled)", () => {
    const h = view({ canAct: false, run: { ...run, state: "executing" }, sel: "t8" });
    for (const word of [">Redirect<", "Interject"]) expect(h).not.toContain(word);
    expect(view({ run: { ...run, state: "executing" }, sel: "t8" })).toContain(">Redirect<");
  });
  it("numbers stages by position, not seq (the orchestrator's seq starts at 1)", () => {
    expect(view({ tasks: plan(7).map((t) => ({ ...t, seq: t.seq + 1 })), sel: "t6" })).toContain("Clerk · moot ⚑ · stage 7 of 10");
  });
  it("lists the interjections this page sent, in the inspector beside the interject form", () => {
    const h = text(view({ run: { ...run, state: "executing" }, interjections: [{ interjection_id: "inj-1", text: "Focus on clause 14 first.", at: "2026-11-10T09:20:00Z" }] }));
    expect(h).toContain("“Focus on clause 14 first.” — delivered at the next stage boundary");
  });
  it("says pending until the confirming event, never success", () => {
    expect(view({ st: { busy: false, pending: true, error: null } })).toContain("Pending… waiting for the worker to confirm.");
  });
});

describe("RunControls — beside the run status", () => {
  const ctl = (state, canAct = true) => renderToString(<RunControls run={{ ...run, state }} canAct={canAct} cmd={() => {}} />);
  it("Pause while executing, Resume (primary) while paused, Cancel on both; none once finished or parked", () => {
    expect(ctl("executing")).toMatch(/>Pause<.*>Cancel</);
    expect(ctl("paused")).toMatch(/btn btn--primary">Resume<.*>Cancel</);
    expect(ctl("waiting_human")).not.toContain(">Pause<");   // parked at an approval: decided, not paused
    expect(ctl("waiting_human")).toContain(">Cancel<");
    for (const s of ["completed", "failed", "cancelled"]) expect(ctl(s)).toBe("");
  });
  it("renders nothing without matter.dispatch (05 §12: hidden, not disabled)", () => {
    expect(ctl("executing", false)).toBe("");
  });
});

describe("SwarmView — no-graph fallback (§9B.3 item 10)", () => {
  it("no dependency metadata: a truthful list in plan order, the graph labelled unavailable, no edges", () => {
    const h = view({ tasks: plan(7).map(({ seq, ...t }) => t) });
    expect(text(h)).toContain("Dependency graph unavailable for this run: no dependency metadata was recorded.");
    expect(h).not.toContain("<svg");
    expect(h).not.toContain('role="toolbar"');
    expect(h).toContain('<ol class="stagemap" aria-label="Stages in plan order">');
    expect(nodes(h)).toHaveLength(10);
    expect(h).not.toMatch(/After |Starts first/);
    expect(insp(view({ tasks: plan(7).map(({ seq, ...t }) => t), sel: "t2" }))).toContain("Depends on Not available for this run");
  });
  it("a cycle falls back the same way", () => {
    const h = view({ tasks: [dep("a", ["b"]), dep("b", ["a"])] });
    expect(text(h)).toContain("its recorded dependencies form a cycle");
    expect(edges(h)).toEqual([]);
  });
  it("no stages at all says so", () => {
    expect(text(view({ tasks: [] }))).toContain("No stage details were recorded for this run.");
  });
});

describe("selected stage is deep-linkable (§9B.3 item 8)", () => {
  it("#/runs/{rid}/{task_id} round-trips; the bare run route is unchanged", () => {
    expect(parseRoute("#/runs/exe-1/exe-1-t3")).toEqual({ name: "run", params: { rid: "exe-1", node: "exe-1-t3" } });
    expect(parseRoute("#/runs/exe-1")).toEqual({ name: "run", params: { rid: "exe-1" } });
    expect(href("run", { rid: "exe-1", node: "exe-1-t3" })).toBe("#/runs/exe-1/exe-1-t3");
    expect(href("run", { rid: "exe-1", node: undefined })).toBe("#/runs/exe-1");
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
