import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { LiveView, agentStats, argOf, describe as card, fmtClock, fmtMs, liveState, pairCalls, splitAgent } from "./screens/Live.jsx";
import { UsageView } from "./screens/Oversight.jsx";

// records exactly as harness/live.py writes them (driver turn.*, opencode `agent` events, gate llm.*)
const T = (s) => new Date(Date.parse("2026-11-16T09:00:00Z") + s * 1000).toISOString();
const who = { agent: "evaluator-stage-assess", session_id: "s1", model: "gate-local/gate/drafting" };
const RECS = [
  { _id: "1", ts: T(0), kind: "turn.start", ...who, prompt: "Assess the limitation defence." },
  { _id: "2", ts: T(1), kind: "agent", ...who, event: { type: "step_start", part: {} } },
  { _id: "3", ts: T(1), kind: "llm.start", ...who, provider: "nvidia-nim", model: "nvidia/nemotron-vl", n_messages: 3, tools: 22,
    input: { role: "user", content: "Assess the limitation defence." } },
  { _id: "4", ts: T(11), kind: "llm.end", ...who, provider: "nvidia-nim", model: "private/nvidia/nemotron", status: "ok", ms: 9812,
    tokens_in: 12840, tokens_out: 702, tokens_reasoning: 0, content: "Searching first.", reasoning: "s 9 governs",
    tool_calls: [{ function: { name: "ironfleet_search_corpus", arguments: "{}" } }] },
  { _id: "5", ts: T(12), kind: "agent", ...who, event: { type: "tool_use", part: { tool: "ironfleet_search_corpus",
    state: { status: "completed", input: { q: "Limitation Act s 11" }, output: "6 hits", time: { start: 1000, end: 1410 } } } } },
  { _id: "6", ts: T(13), kind: "agent", ...who, event: { type: "text", part: { text: "Assessment: the claim is in time." } } },
];
const text = (h) => h.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ");

describe("pairCalls", () => {
  it("a started call and its answer become one card carrying the input and the requested model; step markers drop", () => {
    const rows = pairCalls(RECS);
    expect(rows.map((r) => r.kind)).toEqual(["turn.start", "llm.end", "agent", "agent"]);
    expect(rows[1]).toMatchObject({ requested: "nvidia/nemotron-vl", model: "private/nvidia/nemotron", n_messages: 3,
      input: { content: "Assess the limitation defence." } });
  });
  it("a call still in flight stays a waiting card", () => {
    expect(pairCalls(RECS.slice(0, 3)).at(-1)).toMatchObject({ kind: "llm.start", model: "nvidia/nemotron-vl" });
  });
});

describe("describe(record)", () => {
  it("an answered call: short model, ms, tokens, provider, the model swap and the tools asked for", () => {
    const d = card(pairCalls(RECS)[1]);
    expect(d).toMatchObject({ chip: "LLM call", tone: "llm", title: "nemotron answered" });
    expect(d.meta).toEqual(["9.8 s", "12.8k in", "702 out", "nvidia-nim", "requested nemotron-vl", "asked for ironfleet_search_corpus"]);
    expect(d.cats).toEqual(["llm", "thinking", "output"]);
    expect(d.detail.map(([k]) => k)).toEqual(["Thinking", "Output", "Tool calls requested", "Latest input"]);
  });
  it("a waiting call is pending; a tool step names tool, status and duration", () => {
    expect(card(RECS[2])).toMatchObject({ pending: true, title: "Waiting on nemotron-vl" });
    expect(card(RECS[4])).toMatchObject({ chip: "Tool", title: "ironfleet_search_corpus", status: "completed", meta: ["410 ms", "Limitation Act s 11"] });
    expect(card(RECS[4]).detail).toEqual([["Input", { q: "Limitation Act s 11" }], ["Output", "6 hits"], ["Error", undefined]]);
  });
  it("failures are marked bad; a skill call names the skill; turns name agent and stage", () => {
    expect(card({ kind: "llm.end", provider: "p", model: "m", status: "error", error: "503", ms: 40 }))
      .toMatchObject({ title: "m failed", bad: true, tone: "bad" });
    expect(card({ kind: "agent", event: { type: "tool_use", part: { tool: "skill", state: { status: "error", input: { name: "nz-limitation" } } } } }))
      .toMatchObject({ chip: "Skill", title: "nz-limitation", bad: true });
    expect(card(RECS[0]).title).toBe("evaluator started assess");
    expect(card({ kind: "turn.end", agent: "hunter-stage-research", code: 0, ms: 72000, calls: 2, tokens_in: 8000, tokens_out: 300 }))
      .toMatchObject({ title: "hunter finished research", meta: ["1m 12s", "2 LLM calls", "8.0k in", "300 out"] });
  });
  it("unknown event types still show, never vanish", () => {
    expect(card({ kind: "agent", event: { type: "file.edited" } }).title).toBe("file.edited");
  });
});

describe("liveState", () => {
  it("open turn + open call = running now; llm switches to the model that actually answered", () => {
    expect(liveState(RECS.slice(0, 3))).toMatchObject({ turn: { agent: who.agent }, call: { kind: "llm.start" }, llm: { model: "nvidia/nemotron-vl" } });
    const s = liveState(RECS);
    expect(s.call).toBeNull();
    expect(s.llm.model).toBe("private/nvidia/nemotron");
    expect(s.cur).toEqual({ in: 12840, out: 702, calls: 1 });
    expect(liveState([...RECS, { kind: "turn.end" }])).toMatchObject({ turn: null, call: null, llm: null });
  });
});

describe("agentStats", () => {
  it("one entry per agent in order: state, models used, tokens, calls, tools", () => {
    const end = { kind: "turn.end", ...who, code: 0, ms: 14000 };
    const next = { kind: "turn.start", agent: "hunter-stage-research", ts: T(20) };
    const [a, b] = agentStats([...RECS, end, next]);
    expect(a).toMatchObject({ agent: who.agent, state: "done", tin: 12840, tout: 702, calls: 1, tools: 1, ms: 14000 });
    expect([...a.models]).toEqual(["nemotron · nvidia-nim"]);
    expect(b).toMatchObject({ agent: "hunter-stage-research", state: "running" });
  });
  it("a turn that never ended is shown stopped once another starts", () => {
    const [a] = agentStats([...RECS, { kind: "turn.start", agent: "x", ts: T(30) }]);
    expect(a.state).toBe("stopped");
  });
});

describe("formatting", () => {
  it("fmtMs: ms, seconds, minutes, hours; fmtClock: mm:ss and h:mm:ss; splitAgent", () => {
    expect([fmtMs(null), fmtMs(40), fmtMs(9812), fmtMs(125000), fmtMs(7_930_000)])
      .toEqual(["—", "40 ms", "9.8 s", "2m 05s", "2h 12m"]);
    expect([fmtClock(34_700), fmtClock(725_000), fmtClock(3_729_000)]).toEqual(["00:34", "12:05", "1:02:09"]);
    expect(splitAgent("ingestor-stage-intake")).toEqual(["ingestor", "intake"]);
    expect(splitAgent("clerk")).toEqual(["clerk", ""]);
    expect(argOf({ filePath: "C:\\ws\\ingestor\\matter.json" })).toBe("matter.json");
    expect(argOf({ query: "executor duties / estate" })).toBe("executor duties / estate");   // prose with a slash stays whole
    expect([argOf({}), argOf(null), argOf({ n: 3 })]).toEqual(["", "", ""]);
  });
});

describe("LiveView (mission control)", () => {
  it("strip says who runs on which real model; rail lists the agent; cards newest first, thinking open", () => {
    const h = text(renderToString(<LiveView recs={RECS} live="live" />));
    expect(h).toContain("evaluator · stage assess Running");
    expect(h).toContain("answering: nvidia-nim · nemotron");
    expect(h).toContain("(route gate-local/gate/drafting)");
    expect(h).toContain("Agents · 1");
    expect(h).toContain("nemotron · nvidia-nim");
    expect(h.indexOf("Assessment: the claim is in time.")).toBeLessThan(h.indexOf("evaluator started assess"));
    expect(h).toContain("s 9 governs");
    const html = renderToString(<LiveView recs={RECS} live="live" />);
    expect(html).toMatch(/aria-expanded="true"[^>]*>.*?Thinking<\/button>/);   // thinking opens by default
    expect(html).toMatch(/aria-expanded="false"[^>]*>.*?Output<\/button>/);    // the rest wait for a click
    expect(html).not.toMatch(/aria-live|role="status"/);     // ticking clocks are never announced
  });
  it("idle strip, the no-thinking note, and the empty state", () => {
    const done = [...RECS, { kind: "turn.end", ...who, ts: T(20), code: 0, ms: 20000 }];
    expect(text(renderToString(<LiveView recs={done} live="live" />))).toContain("No agent is running");
    const noThink = RECS.map((r) => (r.kind === "llm.end" ? { ...r, reasoning: null } : r));
    expect(text(renderToString(<LiveView recs={noThink} live="live" />))).toContain("returned no thinking text");
    expect(text(renderToString(<LiveView recs={[]} live="live" />))).toContain("When a run starts, every step and model call streams here.");
  });
});

describe("UsageView", () => {
  it("one row per provider/model and per user, with calls, errors, tokens and model time", () => {
    const s = (o) => ({ calls: 2, errors: 0, in: 1500, out: 20, thinking: 0, cache: 0, ms: 61000, all: 1520, ...o });
    const h = text(renderToString(<UsageView u={{ total: s({ calls: 3 }), by_model: [{ provider: "nvidia-nim", model: "nemotron", ...s() }],
      by_user: [{ user: "admin", ...s({ errors: 1 }) }] }} />));
    expect(h).toContain("All time: 3 model calls · 1.5k tokens · 1m 01s model time");
    expect(h).toContain("nvidia-nim nemotron 2 0 1.5k 20 0 1.5k 1m 01s");
    expect(h).toContain("admin 2 1 1.5k");
  });
});
