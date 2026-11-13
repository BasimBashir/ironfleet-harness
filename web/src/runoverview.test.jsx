import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Ctx } from "./App.jsx";
import { RunOverview, eventLine, fmtDur, stageState, stageTimes } from "./screens/RunPage.jsx";

// UX-2 (NEXT_STEPS §9B.2) — the run overview is a pure render of the persisted snapshot:
// GET /runs/{rid} (+events), /executions/{rid}/tasks, /matters/{mid}{,/tokens,/artifacts,/approvals}.
const KEYS = [["intake", "ingestor"], ["research", "hunter"], ["filings", "clerk", "filing"], ["advice", "clerk"], ["close", "auditor"]];
const T0 = Date.parse("2026-11-10T09:00:00Z") / 1000;
const plan = (states, over = {}) => KEYS.map(([key, agent_id, approval_kind], i) => ({
  task_id: `t${i}`, execution_id: "exe-1", seq: i + 1, key, agent_id, approval_kind: approval_kind || null,
  instruction: `do ${key}`, state: states[i] || "pending", attempts: states[i] && states[i] !== "pending" ? 1 : 0,
  max_attempts: 3, lease_expires_at: states[i] === "running" ? T0 + 600 : null,
  result_summary: states[i] === "completed" ? `${key} done` : null, ...(over[i] || {}),
}));
const ev = (id, type, task_id, min) => ({ id, type, task_id, ts: new Date((T0 + min * 60) * 1000).toISOString() });
const EVENTS = [ev(1, "execution.created", null, 0), ev(2, "task.running", "t0", 0), ev(3, "task.completed", "t0", 2),
  ev(4, "task.running", "t1", 2), ev(5, "task.completed", "t1", 9)];
const RUN = { execution_id: "exe-1", matter_id: "m1", state: "executing", input_task_text: "Prepare the SSA comparison",
  started_at: "2026-11-10T09:00:00Z", ended_at: null, events: EVENTS };
const ok = (data) => ({ data, error: null, loading: false, reload: () => {} });

function view({ run = {}, states = ["completed", "completed", "running"], taskOver, tasks, live = "live", perms = ["*"],
  mode = "firm", approvals = [], artifacts = [], tokens, stages = true, asOf = T0 + 60 } = {}) {
  return renderToString(
    <Ctx.Provider value={{ perms, mode, live }}>
      <RunOverview run={ok({ ...RUN, ...run })} tasks={tasks || ok(plan(states, taskOver))}
        tokens={tokens || ok({ total: { all: 132400 }, agents: [{ agent: "clerk", all: 18200, in: 14900, out: 3300, thinking: 0 }] })}
        matter={ok({ title: "Acme v State" })} artifacts={ok({ items: artifacts })} approvals={ok(approvals)}
        stages={stages} asOf={asOf} />
    </Ctx.Provider>);
}
const text = (h) => h.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/\s+/g, " ");

describe("run header (identity, status, times, tokens only as supplied)", () => {
  it("shows matter, task, status, start, elapsed so far, last update and the matter-wide token total", () => {
    const h = text(view());
    expect(h).toContain("Run exe-1 Running");
    expect(h).toContain("Acme v State");
    expect(h).toContain("Prepare the SSA comparison");
    expect(h).toContain("1m 00s so far");                 // asOf − started_at, never a guess
    expect(h).toContain("132.4k across this matter (all runs) · a per-run total is not recorded");
  });
  it("a finished run shows its ended time and duration from ended_at", () => {
    const h = text(view({ run: { state: "completed", ended_at: "2026-11-10T11:05:00Z" }, states: Array(5).fill("completed") }));
    expect(h).toContain("Ended");
    expect(h).toContain("Duration 2h 05m");
    expect(h).not.toContain("so far");
  });
  it("tokens unavailable is said, not zeroed", () => {
    expect(text(view({ tokens: { data: undefined, error: { message: "x" }, reload: () => {} } }))).toContain("Tokens Unavailable");
  });
});

describe("status vocabulary: every class, unknown never becomes completed", () => {
  it("maps queued / running / completed / failed / not run / interrupted / waiting / cancelled", () => {
    const tasks = plan(["completed", "running", "pending"]);
    expect(stageState(tasks[0], "executing", null)).toBe("completed");
    expect(stageState(tasks[1], "executing", null)).toBe("running");
    expect(stageState(tasks[2], "executing", null)).toBe("pending");
    expect(stageState(tasks[2], "failed", null)).toBe("not_run");
    expect(stageState(tasks[2], "cancelled", null)).toBe("not_run");
    expect(stageState(tasks[1], "executing", null, T0 + 601)).toBe("interrupted");   // lease expired as of load
    expect(stageState(tasks[1], "executing", null, T0 + 599)).toBe("running");
    expect(stageState(tasks[1], "paused", null, T0 + 9999)).toBe("running");          // only an executing run re-claims
    expect(stageState(tasks[0], "waiting_human", "t0")).toBe("waiting_human");
    expect(stageState({ ...tasks[0], state: "weird_new" }, "executing", null)).toBe("weird_new");
  });
  it("renders an unknown run and stage state as its own words, never as Completed", () => {
    const h = text(view({ run: { state: "reticulating" }, states: ["mystery"] }));
    expect(h).toContain("Run exe-1 reticulating");
    expect(h).toContain("mystery");
    expect(h).toContain("This state is not one the overview recognises");
    expect(h).not.toMatch(/Completed/);
  });
  it("counts each status class in the progress line", () => {
    expect(text(view())).toContain("2 of 5 complete · 1 running · 2 queued");
  });
});

describe("next human action, from persisted state only", () => {
  const approval = { approval_id: "ap-1", matter_id: "m1", execution_id: "exe-1", task_id: "t2", kind: "filing",
    state: "pending", requested_at: "2026-11-10T09:30:00Z", request_payload: { result_summary: "filing drafted" } };
  it("waiting_human: says approval is needed, inlines this run's approval only, links the Approval Center", () => {
    const other = { ...approval, approval_id: "ap-9", execution_id: "exe-OTHER" };
    const h = view({ run: { state: "waiting_human" }, states: ["completed", "completed", "completed"], approvals: [approval, other] });
    expect(text(h)).toContain("Your approval is needed");
    expect(h).toContain('id="ap-ap-1"');
    expect(h).not.toContain("ap-9");
    expect(h).toContain('href="#/approvals"');
    expect(text(h)).toContain("filings · clerk Awaiting approval");   // the parked stage, not "Completed"
    expect(text(h)).toContain("2 of 5 complete · 1 awaiting approval · 2 queued");   // sums to 5, no double count
  });
  it("executing with nothing parked: no action needed", () => {
    expect(text(view())).toContain("No action needed from you right now");
  });
  it("paused: someone must resume it", () => {
    expect(text(view({ run: { state: "paused" } }))).toContain("Paused — waiting for someone to resume it");
  });
  it("interrupted: the stage stopped reporting and is retried; the run itself is not marked failed", () => {
    const h = text(view({ asOf: T0 + 601 }));
    expect(h).toContain("Stage filings stopped reporting");
    expect(h).toContain("attempt 1 of 3");
    expect(h).toContain("Run exe-1 Running");
    expect(h).not.toContain("Run exe-1 Failed");
  });
});

describe("partial failure and halted runs", () => {
  const failed = { 2: { result_summary: "TimeoutError: model did not answer", attempts: 3 } };
  it("shows the failed stage's error and attempts; later stages are Not run, never Queued", () => {
    const h = text(view({ run: { state: "failed", ended_at: "2026-11-10T09:40:00Z" }, states: ["completed", "completed", "failed"], taskOver: failed }));
    expect(h).toContain("Stopped: stage filings failed");
    expect(h).toContain("Error: TimeoutError: model did not answer");
    expect(h).toContain("Attempts 3 of 3");
    expect(h).toContain("2 not run");
    expect(h).not.toContain("queued");
  });
  it("a stage retry on a still-running run is shown as an attempt count, not a failure", () => {
    const h = text(view({ taskOver: { 2: { attempts: 2 } } }));
    expect(h).toContain("Attempts 2 of 3");
    expect(h).toContain("No action needed from you right now");
  });
  it("cancelled: halted stages are Not run", () => {
    const h = text(view({ run: { state: "cancelled", ended_at: "2026-11-10T09:20:00Z" } }));
    expect(h).toContain("Run exe-1 Cancelled");
    expect(h).toContain("Stages that had not started will not run");
    expect(h).toContain("2 not run");
  });
});

describe("execution order and dependencies, honestly", () => {
  it("lists stages in seq order whatever order they arrive in, and says they run one at a time", () => {
    const shuffled = plan(["completed", "completed", "running"]).reverse();
    const h = text(view({ tasks: ok(shuffled) }));
    expect(h.indexOf(" intake ")).toBeLessThan(h.indexOf(" research "));
    expect(h.indexOf(" research ")).toBeLessThan(h.indexOf(" close "));
    expect(h).toContain("Stages run one at a time in plan order");
  });
  it("stage times come from the run's own events; a retry keeps its first start", () => {
    const t = stageTimes([ev(1, "task.running", "a", 0), ev(2, "task.running", "a", 5), ev(3, "task.completed", "a", 7)]);
    expect(Date.parse(t.a.end) - Date.parse(t.a.start)).toBe(7 * 60000);
    expect(text(view())).toContain("intake · ingestor Completed · 2m 00s");
    expect(fmtDur(26 * 3600000)).toBe("26h 00m");
  });
});

describe("agents, tokens and deliverables", () => {
  it("each agent is listed once with its stages; a multi-stage agent's tokens are not repeated per stage", () => {
    const h = view();
    expect(text(h)).toContain("clerk filings, advice 18.2k");
    expect((h.match(/18\.2k/g) || []).length).toBe(1);
    expect(text(h)).toContain("hunter research None recorded");
  });
  it("lists only this run's deliverables, linked to the matter's Drafts", () => {
    const arts = [{ artifact_id: "a-1", execution_id: "exe-1", kind: "memo", title: "SSA comparison memo", review_state: "pending_review", created_at: "2026-11-10T09:10:00Z" },
      { artifact_id: "a-2", execution_id: "exe-OTHER", title: "Someone else's draft" }];
    const h = view({ artifacts: arts });
    expect(h).toContain('href="#/m/m1/drafts"');
    expect(text(h)).toContain("SSA comparison memo · memo · pending review");
    expect(h).not.toContain("Someone else");
  });
  it("empty deliverables say so; a finished run says it recorded none", () => {
    expect(text(view())).toContain("No deliverables yet.");
    expect(text(view({ run: { state: "completed" }, states: Array(5).fill("completed") }))).toContain("This run recorded no deliverables.");
  });
});

describe("history, refresh restoration and the live connection", () => {
  it("renders the persisted events once each, as plain lines (no payloads)", () => {
    const h = view();
    expect(text(h)).toContain("Run history (5 events)");
    expect((text(h).match(/Stage research completed/g) || []).length).toBe(1);
    expect(eventLine({ type: "something.new" }, {})).toBe("something.new");
    expect(eventLine({ type: "execution.failed", task_id: "t2" }, { t2: { key: "filings" } })).toBe("Run stopped: failed at stage filings");
  });
  it("is a pure function of the persisted snapshot: re-entry renders the same state", () => {
    expect(view()).toBe(view());
  });
  it("a dropped connection says live updates paused — and never that the run stopped", () => {
    const h = text(view({ live: "reconnecting" }));
    expect(h).toContain("Live updates are disconnected");
    expect(h).toContain("carries on on the server");
    expect(h).toContain("Run exe-1 Running");
    expect(text(view({ live: "reconnecting", run: { state: "completed" } }))).not.toContain("Live updates are disconnected");
  });
  it("a failed refetch keeps the last values with a stale notice", () => {
    const h = renderToString(<Ctx.Provider value={{ perms: ["*"], mode: "firm", live: "live" }}>
      <RunOverview run={{ data: RUN, error: { message: "network down" }, reload: () => {} }} tasks={ok(plan(["completed"]))}
        tokens={ok(null)} matter={ok(null)} artifacts={ok({ items: [] })} approvals={ok([])} asOf={T0} />
    </Ctx.Provider>);
    expect(text(h)).toContain("Couldn't refresh — showing the last loaded values");
    expect(text(h)).toContain("Run exe-1 Running");
  });
});

describe("stage list density: summary first, details on demand", () => {
  const opens = (h) => (h.match(/<details open=""/g) || []).length;
  it("opens only the current stage by default; keeps Expand all / Collapse all", () => {
    const h = view();
    expect(h).toContain('<li aria-current="step">');
    expect(opens(h)).toBe(1);
    expect(text(h)).toContain("Expand all");
    expect(text(h)).toContain("Collapse all");
  });
  it("a finished run marks no current stage", () => {
    expect(view({ run: { state: "completed" }, states: Array(5).fill("completed") })).not.toContain("aria-current");
  });
  it("no stage records: says so, invents no agent rows", () => {
    const h = text(view({ tasks: ok([]) }));
    expect(h).toContain("No stage details were recorded for this run.");
    expect(h).not.toContain("Agents in this run");
    expect(h).not.toContain("Expand all");
  });
  it("firm page variant (stages=false) keeps the summary and leaves the explanation to the stage map", () => {
    const h = text(view({ stages: false }));
    expect(h).toContain("2 of 5 complete");
    expect(h).not.toContain("Stages run one at a time");     // said once, by the stage map
    expect(h).not.toContain("Expand all");
  });
  it("puts run commands beside the status and the stage map under the stage progress, before deliverables", () => {
    const h = renderToString(
      <Ctx.Provider value={{ perms: ["*"], mode: "firm", live: "live" }}>
        <RunOverview run={ok(RUN)} tasks={ok(plan(["completed"]))} tokens={ok({ total: { all: 1 }, agents: [] })}
          matter={ok({ title: "Acme" })} artifacts={ok({ items: [] })} approvals={ok([])} stages={false} asOf={T0 + 60}
          actions={<button type="button">Pause</button>}><div id="stage-map" /></RunOverview>
      </Ctx.Provider>);
    expect(h.indexOf(">Pause<")).toBeLessThan(h.indexOf("Prepare the SSA comparison"));
    expect(h.indexOf("1 of 5 complete")).toBeLessThan(h.indexOf('id="stage-map"'));
    expect(h.indexOf('id="stage-map"')).toBeLessThan(h.indexOf(">Deliverables<"));
  });
  it("a paused run with a stage still running says that stage will finish first", () => {
    expect(text(view({ run: { state: "paused" } }))).toContain("the stage already running will finish. No further stages start until the run is resumed.");
    expect(text(view({ run: { state: "paused" }, states: ["completed", "completed"] }))).not.toContain("already running");
  });
  it("Redirect stays gated by matter.dispatch", () => {
    expect(view()).toContain(">Redirect<");
    expect(view({ perms: ["matter.read"] })).not.toContain(">Redirect<");
  });
  it("self-rep matter link goes to the case view", () => {
    expect(view({ mode: "self-rep" })).toContain('href="#/case/m1"');
  });
});
