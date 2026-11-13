import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { Ctx } from "./App.jsx";
import { ActivityStream, RunOverview, SwarmView, activity, remember, resyncNeeded, shown } from "./screens/RunPage.jsx";

// UX-4 (NEXT_STEPS §9B.4) — a deterministic fixture of the real event vocabulary the backend emits:
// orchestrator.py (execution.created/completed/failed, task.running/completed/failed, chat.replied) and
// executions.py (execution.state_changed {to, actor, task_id, note}). GET /runs/{rid} persists id/ts/type/task_id;
// SSE frames carry the full payload — which is why the client keeps only a whitelist.
const TASKS = [["t0", "intake", "ingestor"], ["t1", "research", "hunter"], ["t2", "filings", "clerk"]]
  .map(([task_id, key, agent_id], i) => ({ task_id, key, agent_id, seq: i + 1, state: "pending", attempts: 0, max_attempts: 3 }));
const T = (min) => new Date(Date.parse("2026-11-10T09:00:00Z") + min * 60000).toISOString();
const ev = (id, type, task_id = null, min = id) => ({ id, ts: T(min), type, task_id });
// what sse.js hands the bus: id is a string, data is the parsed frame (payload + matter_id + ts)
const frame = (id, event, data) => ({ id: String(id), event, data: { matter_id: "m1", ts: T(id), execution_id: "exe-1", ...data } });
const asLive = (f) => ({ id: Number(f.id), type: f.event, ts: f.data.ts, execution_id: f.data.execution_id,
  task_id: f.data.task_id ?? null, to: f.data.to, actor: f.data.actor });
const RUN = { execution_id: "exe-1", matter_id: "m1", state: "executing", started_at: T(0),
  events: [ev(1, "execution.created"), ev(2, "task.running", "t0"), ev(3, "task.completed", "t0"), ev(4, "task.running", "t1")] };
const text = (h) => h.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");
const stream = (over = {}) => renderToString(<ActivityStream run={RUN} tasks={TASKS} live="live" received={[]} {...over} />);

describe("sequencing and identity", () => {
  it("orders by the server's event id, never by timestamp, and drops nothing when clocks disagree", () => {
    const run = { ...RUN, events: [ev(3, "task.completed", "t0", 1), ev(1, "execution.created", null, 9), ev(2, "task.running", "t0", 5)] };
    const a = activity(run, TASKS);
    expect(a.map((i) => i.id)).toEqual([1, 2, 3]);
    expect(a.map((i) => i.text)).toEqual(["Run created", "Stage intake started (ingestor)", "Stage intake completed"]);
  });
  it("a live frame and the persisted copy of the same event are one entry; the frame adds who did it", () => {
    const run = { ...RUN, events: [...RUN.events, ev(5, "execution.state_changed")] };
    const live = [asLive(frame(5, "execution.state_changed", { to: "paused", actor: "alice", task_id: null })), asLive(frame(4, "task.running", { task_id: "t1" }))];
    const a = activity(run, TASKS, live);
    expect(a).toHaveLength(5);
    expect(a.at(-1).text).toBe("Paused by alice — no further stage starts until someone resumes it");
  });
  it("replay from event 0 after a reconnect (the SSE contract with no Last-Event-ID) duplicates nothing", () => {
    const replayed = RUN.events.map((e) => asLive(frame(e.id, e.type, { task_id: e.task_id })));
    expect(activity(RUN, TASKS, [...replayed, ...replayed])).toEqual(activity(RUN, TASKS));
  });
  it("a live-only event (not yet in the persisted snapshot) still shows, in id order", () => {
    const a = activity(RUN, TASKS, [asLive(frame(6, "task.completed", { task_id: "t1" }))]);
    expect(a.map((i) => i.id)).toEqual([1, 2, 3, 4, 6]);
    expect(a.at(-1).text).toBe("Stage research completed");
  });
  it("frames of other runs never leak in", () => {
    expect(activity(RUN, TASKS, [{ ...asLive(frame(9, "task.failed", { task_id: "t1" })), execution_id: "exe-OTHER" }])).toHaveLength(4);
  });
});

describe("typed categories from real events only", () => {
  it("lifecycle, stage, retry, failure, waiting, redirect and chat", () => {
    const run = { ...RUN, events: [ev(1, "execution.created"), ev(2, "task.running", "t0"), ev(3, "task.running", "t0"),
      ev(4, "task.completed", "t0"), ev(5, "execution.state_changed"), ev(6, "task.running", "t1"), ev(7, "task.failed", "t1"),
      ev(8, "execution.failed"), ev(9, "chat.replied")] };
    const live = [asLive(frame(5, "execution.state_changed", { to: "executing", actor: "bob" }))];
    const a = activity(run, TASKS, live);
    expect(a.map((i) => [i.cat, i.text])).toEqual([
      ["run", "Run created"],
      ["stage", "Stage intake started (ingestor)"],
      ["problem", "Stage intake started again — re-claimed after its worker stopped reporting"],
      ["stage", "Stage intake completed"],
      ["run", "Resumed by bob"],
      ["stage", "Stage research started (hunter)"],
      ["problem", "Stage research failed"],
      ["problem", "Run stopped: failed"],
      ["run", "Lead counsel posted this run's digest in the counsel chat"],
    ]);
    expect(activity({ ...RUN, events: [ev(1, "execution.state_changed", "t2")] }, TASKS,
      [asLive(frame(1, "execution.state_changed", { task_id: "t2", to: "executing", actor: "carol" }))])[0].text)
      .toBe("Stage filings redirected to a new instruction by carol");
  });
  it("without the live frame a state change says the detail was not received — it never guesses pause vs cancel", () => {
    expect(activity({ ...RUN, events: [ev(1, "execution.state_changed")] }, TASKS)[0].text)
      .toBe("Run paused, resumed or cancelled (which one was not received)");
  });
  it("an unknown event type is named, never interpreted; a malformed one is not echoed", () => {
    const a = activity({ ...RUN, events: [ev(1, "tool.started"), ev(2, "<img src=x>")] }, TASKS);
    expect(a.map((i) => [i.cat, i.text])).toEqual([["other", "Recorded event: tool.started"], ["other", "Unrecognised event"]]);
  });
  it("errors and retries stay visible under every filter; other categories filter normally", () => {
    const a = activity({ ...RUN, events: [...RUN.events, ev(5, "task.failed", "t1"), ev(6, "execution.failed", "t1")] }, TASKS);
    expect(shown(a, "stage").map((i) => i.id)).toEqual([2, 3, 4, 5, 6]);
    expect(shown(a, "run").map((i) => i.id)).toEqual([1, 5, 6]);
    expect(shown(a, "problem").map((i) => i.id)).toEqual([5, 6]);
    expect(shown(a, "all")).toHaveLength(6);
  });
});

describe("safety: nothing outside the whitelist can render", () => {
  it("a frame carrying a fake secret, a fake reasoning field and a note renders none of them", () => {
    remember({ id: "77", event: "execution.state_changed", data: { matter_id: "m9", ts: T(1), execution_id: "exe-safe", to: "paused", actor: "alice",
      note: "client confided NOTE-LEAK", reasoning: "CHAIN-OF-THOUGHT-LEAK", api_key: "sk-FAKE-SECRET-123", authorization: "Bearer FAKE-TOKEN" } });
    remember({ id: "78", event: "task.running", data: { execution_id: "exe-safe", task_id: "t0", thinking: "PRIVATE-DELIBERATION" } });
    const h = renderToString(<ActivityStream run={{ execution_id: "exe-safe", matter_id: "m9", state: "executing", events: [] }} tasks={TASKS} live="live" />);
    expect(text(h)).toContain("Paused by alice");
    for (const leak of ["NOTE-LEAK", "CHAIN-OF-THOUGHT-LEAK", "sk-FAKE-SECRET-123", "FAKE-TOKEN", "PRIVATE-DELIBERATION", "{", "reasoning"])
      expect(h).not.toContain(leak);
  });
  it("an unsafe actor string is dropped rather than rendered", () => {
    const a = activity({ ...RUN, events: [ev(1, "execution.state_changed")] }, TASKS,
      [asLive(frame(1, "execution.state_changed", { to: "cancelled", actor: "<script>x</script>" }))]);
    expect(a[0].text).toBe("Cancelled — stages not yet started will not run");
  });
});

describe("links only from valid references", () => {
  it("firm: a stage of this run links to its node; an unknown stage id stays plain text", () => {
    const run = { ...RUN, events: [ev(1, "task.running", "t1"), ev(2, "task.running", "ghost")] };
    const h = stream({ run, link: true });
    expect(h).toContain('href="#/runs/exe-1/t1"');
    expect(h).not.toContain("ghost\"");
    expect(text(h)).toContain("Stage ghost started");
    expect(h.match(/<a href="#\/runs\//g)).toHaveLength(1);
  });
  it("self-rep (no stage route): no links at all", () => {
    expect(stream({ link: false })).not.toContain('href="#/runs/');
  });
});

describe("connection, waiting and completion states", () => {
  it("live / reconnecting / unavailable / connecting each say what they are", () => {
    expect(text(stream())).toContain("Live — new activity appears as the server records it.");
    expect(text(stream({ live: "reconnecting" }))).toContain("the connection dropped in this browser only; the run carries on on the server");
    expect(text(stream({ live: "unavailable" }))).toContain("Live updates unavailable — the server refused the event stream");
    expect(text(stream({ live: "connecting" }))).toContain("Connecting to live updates…");
    expect(text(stream({ resynced: "2026-11-10T09:30:00Z" }))).toContain("the server replayed every event recorded while this browser was disconnected, and the run was reloaded");
  });
  it("only a reconnect (or a refused stream coming back) triggers a snapshot reload", () => {
    expect(resyncNeeded("reconnecting", "live")).toBe(true);
    expect(resyncNeeded("unavailable", "live")).toBe(true);
    expect(resyncNeeded("connecting", "live")).toBe(false);
    expect(resyncNeeded("live", "reconnecting")).toBe(false);
  });
  it("a disconnect never changes the persisted run status — no Failed anywhere", () => {
    const ok = (data) => ({ data, error: null, loading: false, reload: () => {} });
    for (const live of ["reconnecting", "unavailable"]) {
      const h = text(renderToString(<Ctx.Provider value={{ perms: ["*"], mode: "firm", live }}>
        <RunOverview run={ok(RUN)} tasks={ok(TASKS.map((t, i) => ({ ...t, state: ["completed", "running", "pending"][i] })))}
          tokens={ok(null)} matter={ok(null)} artifacts={ok({ items: [] })} approvals={ok([])} asOf={Date.parse(T(5)) / 1000} />
      </Ctx.Provider>));
      expect(h).toContain("Run exe-1 Running");
      expect(h).not.toMatch(/Failed|failed/);
    }
  });
  it("waiting on a person: this run's pending approval is pinned; another run's is not", () => {
    const ap = { approval_id: "ap-1", execution_id: "exe-1", task_id: "t2", kind: "filing", requested_at: T(4) };
    const h = text(stream({ run: { ...RUN, state: "waiting_human" }, approvals: [ap, { ...ap, approval_id: "ap-9", execution_id: "exe-X", kind: "other-kind" }] }));
    expect(h).toContain("⚑ Waiting on you: approval (filing) after stage filings");
    expect(h).not.toContain("other-kind");
  });
  it("completed: says the history is the record, and marks the newest event as latest", () => {
    const run = { ...RUN, state: "completed", events: [...RUN.events, ev(5, "task.completed", "t1"), ev(6, "execution.completed")] };
    const h = stream({ run });
    expect(text(h)).toContain("This run has finished — below is its recorded history");
    expect(text(h)).toContain("Latest: Run completed");
    expect(h.match(/data-latest=""/g)).toHaveLength(1);
    expect(h).not.toContain("aria-current");                       // "latest" is not "current stage"
    expect(text(h)).toContain("does not emit tool calls, progress summaries, findings or evidence references");
  });
  it("an empty run says so", () => {
    expect(text(stream({ run: { ...RUN, events: [] } }))).toContain("No events recorded for this run.");
  });
});

describe("agent inspection: the selected stage's own activity", () => {
  it("lists only that stage's events in the drawer", () => {
    const run = { ...RUN, events: [...RUN.events, ev(5, "task.completed", "t1")] };
    const h = renderToString(<SwarmView run={run} tasks={TASKS.map((t, i) => ({ ...t, state: i < 2 ? "completed" : "pending" }))}
      tokens={null} canAct={false} st={{ busy: false, pending: false, error: null }} cmd={() => {}} sel="t1" received={[]} />);
    const insp = text(h.slice(h.indexOf('aria-label="Activity for stage research"')));
    expect(insp).toContain("Stage research started (hunter)");
    expect(insp).toContain("Stage research completed");
    expect(insp).not.toContain("intake");
  });
});
