// Live agent + LLM activity for one matter, "mission control" layout (picked 2026-11-16 from
// design/mockups/live-panel.html): a status strip (who is running, on which real model, timers,
// tokens), an agent rail (each agent's model, state, totals; click to focus), and a card timeline
// of every LLM call, tool call, thinking and output. Source: GET /matters/{mid}/live, which tails
// <store>/live/<mid>.jsonl (harness/live.py).
import { useEffect, useRef, useState } from "react";
import { stream } from "../sse.js";
import { LiveNote, fmtAgo, fmtTokens } from "../ui.jsx";

const MAX = 5000;   // records kept in the page; the full log stays on disk
const SHOW = 300;   // cards drawn at once

export const fmtMs = (ms) => {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const s = Math.floor(ms / 1000), m = Math.floor(s / 60) % 60, h = Math.floor(s / 3600);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(s % 60).padStart(2, "0")}s`;
};
// a running clock: 00:34, 12:05, 1:02:09
export const fmtClock = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
};
const txt = (v) => (v == null ? "" : typeof v === "string" ? v : JSON.stringify(v, null, 2));
const clip = (s, n = 140) => { s = txt(s).replace(/\s+/g, " ").trim(); return s.length > n ? `${s.slice(0, n)}…` : s; };
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
// "ingestor-stage-intake" -> ["ingestor", "intake"]: the persona and the stage it is running
export const splitAgent = (a = "") => {
  const i = a.indexOf("-stage-");
  return i < 0 ? [a, ""] : [a.slice(0, i), a.slice(i + 7)];
};
const shortModel = (m = "") => m.split("/").pop();
// what a tool call was about, at a glance: its first string argument (a path shows as its file name)
export const argOf = (input) => {
  const v = input && typeof input === "object" ? Object.values(input).find((x) => typeof x === "string" && x.trim()) : null;
  if (!v) return "";
  const s = /[\\/]/.test(v) && !/\s/.test(v) ? v.split(/[\\/]/).pop() : v;
  return clip(s, 70);
};

// Outline icons (Lucide paths, 1.75 stroke) — never emoji (ui-ux-pro-max: no-emoji-icons)
const PATHS = {
  llm: <><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2" /></>,
  tool: <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94z" />,
  think: <><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5" /><path d="M9 18h6M10 22h4" /></>,
  out: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />,
  play: <polygon points="6 3 20 12 6 21 6 3" />,
  check: <path d="M20 6 9 17l-5-5" />,
  clock: <><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></>,
  chev: <path d="m9 18 6-6-6-6" />,
  alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" /><path d="M12 9v4M12 17h.01" /></>,
  pause: <><circle cx="12" cy="12" r="10" /><path d="M10 15V9M14 15V9" /></>,
  dot: <circle cx="12" cy="12" r="3" />,
};
export function Ico({ n, sm = false, className = "" }) {
  return <svg className={`lv-ico${sm ? " lv-ico--sm" : ""} ${className}`} viewBox="0 0 24 24" aria-hidden="true" focusable="false">{PATHS[n]}</svg>;
}

// A started call and its answer are one card: the start's input rides on the end record.
// opencode's step_start/step_finish carry nothing a reader needs (their tokens are 0) — dropped.
export function pairCalls(recs) {
  const out = [];
  let open = null;
  for (const r of recs) {
    if (r.kind === "llm.start") { open = { ...r }; out.push(open); continue; }
    if (r.kind === "llm.end" && open && open.agent === r.agent) {
      const { input, n_messages, tools, model: requested } = open;
      Object.assign(open, { ...r, input, n_messages, tools, requested });
      open = null;
      continue;
    }
    const t = r.event?.type;
    if (r.kind === "agent" && (t === "step_start" || t === "step_finish")) continue;
    out.push(r);
  }
  return out;
}

// one card: tone (colour family), icon, chip, title, meta facts, detail blocks, filter cats
export function describe(r) {
  const [name, stage] = splitAgent(r.agent);
  const model = shortModel(r.model);
  if (r.kind === "turn.start") return { cats: ["turn"], tone: "turn", icon: "play", chip: "Turn",
    title: `${name || "Agent"} started${stage ? ` ${stage}` : ""}`, meta: r.model ? [`route ${r.model}`] : [],
    detail: [["Instruction", r.prompt]] };
  if (r.kind === "turn.end") {
    const ok = r.code === 0;
    return { cats: ["turn"], tone: ok ? "ok" : "bad", icon: ok ? "check" : "alert", chip: "Turn", bad: !ok,
      title: ok ? `${name || "Agent"} finished${stage ? ` ${stage}` : ""}` : `${name || "Agent"} stopped (exit ${r.code})`,
      meta: [fmtMs(r.ms), plural(r.calls || 0, "LLM call"), `${fmtTokens(r.tokens_in)} in`, `${fmtTokens(r.tokens_out)} out`,
        ...(r.tokens_reasoning ? [`${fmtTokens(r.tokens_reasoning)} thinking`] : [])], detail: [] };
  }
  if (r.kind === "llm.start") return { cats: ["llm"], tone: "llm", icon: "llm", chip: "LLM call", pending: true,
    title: `Waiting on ${model}`, meta: [r.provider, plural(r.n_messages || 0, "message") + " in context",
      ...(r.tools ? [`${r.tools} tools offered`] : [])],
    detail: [["Latest input", r.input?.content ?? r.input]] };
  if (r.kind === "llm.end") {
    const input = ["Latest input", r.input?.content ?? r.input];
    const swapped = r.requested && r.requested !== r.model ? [`requested ${shortModel(r.requested)}`] : [];
    if (r.status !== "ok") return { cats: ["llm"], tone: "bad", icon: "alert", chip: "LLM call", bad: true,
      title: `${model} failed`, meta: [fmtMs(r.ms), r.provider, ...swapped], detail: [["Error", r.error], input] };
    const cats = ["llm"];
    if (r.reasoning) cats.push("thinking");
    if (r.content) cats.push("output");
    const asked = (r.tool_calls || []).map((c) => c.function?.name).filter(Boolean);
    return { cats, tone: "llm", icon: "llm", chip: "LLM call", title: `${model} answered`,
      meta: [fmtMs(r.ms), `${fmtTokens(r.tokens_in)} in`, `${fmtTokens(r.tokens_out)} out`,
        ...(r.tokens_reasoning ? [`${fmtTokens(r.tokens_reasoning)} thinking`] : []),
        r.provider, ...swapped, ...(asked.length ? [`asked for ${asked.join(", ")}`] : [])],
      detail: [["Thinking", r.reasoning], ["Output", r.content], ["Tool calls requested", asked.length ? r.tool_calls : null], input] };
  }
  const e = r.event || {}, p = e.part || {};
  if (e.type === "text") return { cats: ["output"], tone: "out", icon: "out", chip: "Output", title: clip(p.text, 160),
    meta: [], detail: [["Full text", p.text]] };
  if (e.type === "reasoning") return { cats: ["thinking"], tone: "think", icon: "think", chip: "Thinking", title: clip(p.text, 160),
    meta: [], detail: [["Thinking", p.text]] };
  if (e.type === "tool_use") {
    const s = p.state || {}, t = s.time || {};
    const ms = t.end && t.start ? t.end - t.start : null;
    const skill = p.tool === "skill";
    const bad = s.status === "error";
    return { cats: ["tool"], tone: bad ? "bad" : "tool", icon: bad ? "alert" : "tool", chip: skill ? "Skill" : "Tool", bad,
      title: skill ? (s.input?.name || "skill") : p.tool, status: s.status || "?",
      meta: [...(ms != null ? [fmtMs(ms)] : []), ...(argOf(s.input) ? [argOf(s.input)] : [])],
      detail: [["Input", s.input], ["Output", s.output], ["Error", s.error]] };
  }
  return { cats: ["other"], tone: "turn", icon: "dot", chip: "Event", title: e.type || r.kind || "event", meta: [], detail: [["Event", e]] };
}

// who is working right now (one turn per matter at a time), on which real model, and this turn's numbers
export function liveState(recs) {
  let turn = null, call = null, llm = null, cur = { in: 0, out: 0, calls: 0 };
  for (const r of recs) {
    if (r.kind === "turn.start") { turn = r; llm = null; call = null; cur = { in: 0, out: 0, calls: 0 }; }
    else if (r.kind === "turn.end") { turn = null; call = null; llm = null; }
    else if (r.kind === "llm.start") { call = r; if (!llm) llm = r; }
    else if (r.kind === "llm.end") {
      call = null;
      if (r.status === "ok") { llm = r; cur = { in: cur.in + (r.tokens_in || 0), out: cur.out + (r.tokens_out || 0), calls: cur.calls + 1 }; }
    }
  }
  return { turn, call, llm, cur };
}

// the rail: every agent seen, in pipeline order, with its state, models and totals
export function agentStats(recs) {
  const m = new Map();
  const get = (a) => {
    if (!m.has(a)) m.set(a, { agent: a, state: "seen", models: new Set(), tin: 0, tout: 0, calls: 0, tools: 0, ms: 0, since: null });
    return m.get(a);
  };
  for (const r of recs) {
    if (!r.agent) continue;
    const s = get(r.agent);
    if (r.kind === "turn.start") {
      for (const o of m.values()) if (o !== s && o.state === "running") { o.state = "stopped"; o.since = null; }
      s.state = "running"; s.since = r.ts;
    } else if (r.kind === "turn.end") { s.state = r.code === 0 ? "done" : "failed"; s.ms += r.ms || 0; s.since = null; }
    else if (r.kind === "llm.end" && r.status === "ok") {
      s.calls += 1; s.tin += r.tokens_in || 0; s.tout += r.tokens_out || 0;
      s.models.add(`${shortModel(r.model)} · ${r.provider}`);
    } else if (r.kind === "agent" && r.event?.type === "tool_use") s.tools += 1;
  }
  return [...m.values()];
}

const FILTERS = [["all", "All", null], ["llm", "LLM calls", "llm"], ["tool", "Tools", "tool"],
  ["thinking", "Thinking", "think"], ["output", "Output", "out"]];
const STATE = { running: ["Running", "clock", "run"], done: ["Done", "check", "ok"], failed: ["Failed", "alert", "bad"],
  stopped: ["Stopped", "pause", "idle"], seen: ["Seen", "dot", "idle"] };

// ticking clock; no live region anywhere it is used (it would be re-announced every second)
function Clock({ since }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  return <>{fmtClock(now - new Date(since).getTime())}</>;
}

// onSettled: a model call or turn finished — the caller refreshes its usage numbers (debounced,
// so a replay of hundreds of records costs one refetch)
export function LiveAgents({ mid, onSettled = () => {} }) {
  const [recs, setRecs] = useState([]);
  const [live, setLive] = useState("connecting");
  const settled = useRef(onSettled);
  settled.current = onSettled;
  useEffect(() => {
    setRecs([]);
    let t;
    const stop = stream(`/api/v1/matters/${encodeURIComponent(mid)}/live`, (e) => {
      setRecs((xs) => [...xs.slice(-(MAX - 1)), { ...e.data, _id: e.id }]);
      if (e.event === "llm.end" || e.event === "turn.end") {
        clearTimeout(t);
        t = setTimeout(() => settled.current(), 800);
      }
    }, { onStatus: setLive });
    return () => { clearTimeout(t); stop(); };
  }, [mid]);
  return <LiveView recs={recs} live={live} />;
}

function Strip({ recs }) {
  const { turn, call, llm, cur } = liveState(recs);
  if (!turn) {
    const done = recs.filter((r) => r.kind === "llm.end" && r.status === "ok");
    const last = [...recs].reverse().find((r) => r.kind === "turn.end");
    const [n] = splitAgent(last?.agent);
    return (
      <div className="lv-card lv-strip lv-strip--idle">
        <div>
          <div className="lv-who"><Ico n="pause" />No agent is running</div>
          <div className="lv-model">{last ? `Last: ${n} finished ${fmtAgo(last.ts)}.` : "When a run starts, every step and model call streams here."}</div>
        </div>
        <dl className="lv-stats">
          <div className="lv-stat"><dt>In</dt><dd>{fmtTokens(done.reduce((a, r) => a + (r.tokens_in || 0), 0))}</dd></div>
          <div className="lv-stat"><dt>Out</dt><dd>{fmtTokens(done.reduce((a, r) => a + (r.tokens_out || 0), 0))}</dd></div>
          <div className="lv-stat"><dt>LLM calls</dt><dd>{done.length}</dd></div>
          <div className="lv-stat"><dt>Model time</dt><dd>{fmtMs(done.reduce((a, r) => a + (r.ms || 0), 0))}</dd></div>
        </dl>
      </div>);
  }
  const [name, stage] = splitAgent(turn.agent);
  const answered = llm?.kind === "llm.end";
  return (
    <div className="lv-card lv-strip">
      <div>
        <div className="lv-who"><span className="lv-dot lv-dot--live" aria-hidden="true" />{name}
          {stage ? <span className="lv-stage">· stage {stage}</span> : null}<span className="lv-chip k-llm">Running</span></div>
        <div className="lv-model"><Ico n="llm" sm />
          {llm ? <>{answered ? "answering: " : "calling: "}<b>{`${llm.provider} · ${shortModel(llm.model)}`}</b></> : "no model called yet"}
          <span>{`(route ${turn.model || "?"})`}</span></div>
      </div>
      <dl className="lv-stats">
        <div className="lv-stat"><dt>Turn</dt><dd><Clock since={turn.ts} /></dd></div>
        <div className="lv-stat lv-stat--wait"><dt>Waiting on model</dt><dd>{call ? <Clock since={call.ts} /> : "—"}</dd></div>
        <div className="lv-stat"><dt>In</dt><dd>{fmtTokens(cur.in)}</dd></div>
        <div className="lv-stat"><dt>Out</dt><dd>{fmtTokens(cur.out)}</dd></div>
        <div className="lv-stat"><dt>LLM calls</dt><dd>{cur.calls}</dd></div>
      </dl>
    </div>);
}

function Rail({ stats, agent, onPick }) {
  return (
    <nav className="lv-card lv-rail" aria-label="Agents in this matter's runs">
      <h3>{`Agents · ${stats.length}`}</h3>
      <button type="button" className="lv-agent" aria-pressed={!agent} onClick={() => onPick("")}>
        <span className="lv-row1">All agents</span></button>
      {stats.map((s) => {
        const [name, stage] = splitAgent(s.agent);
        const [word, icon, tone] = STATE[s.state];
        return (
          <button key={s.agent} type="button" className="lv-agent" aria-pressed={agent === s.agent} onClick={() => onPick(s.agent)}>
            <span className="lv-row1">
              {s.state === "running" ? <span className="lv-dot lv-dot--live" aria-hidden="true" /> : <Ico n={icon} sm className={`k-${tone}`} />}
              {name}{stage ? <span className="lv-muted">{` · ${stage}`}</span> : null}
              <span className={`lv-st k-${tone}`}><Ico n={icon} sm />{word}</span></span>
            <span className="lv-row2 lv-mono">{s.models.size ? [...s.models].join(", ") : "no model call yet"}</span>
            <span className="lv-row3">{`${fmtTokens(s.tin + s.tout)} tok · ${plural(s.calls, "call")} · ${plural(s.tools, "tool")}`}
              {s.state === "running" && s.since ? <> · <Clock since={s.since} /></> : s.ms ? ` · ${fmtMs(s.ms)}` : ""}</span>
          </button>);
      })}
    </nav>);
}

// The card's details sit on ONE row of toggles (one block open at a time) so a card stays short;
// a model's thinking opens by default — it is the part people come here to read.
function Card({ r, d }) {
  const blocks = d.detail.filter(([, v]) => v != null && v !== "");
  const [open, setOpen] = useState(blocks.some(([k]) => k === "Thinking") ? "Thinking" : null);
  const id = `lv-${String(r._id).replace(/\W/g, "")}`;
  return (
    <li className={`lv-ev${d.pending ? " lv-ev--now" : ""}`} data-state={d.bad ? "failed" : undefined}>
      <span className={`lv-badge k-${d.tone}`} aria-hidden="true"><Ico n={d.icon} /></span>
      <div className="lv-card lv-body">
        <div className="lv-h">
          <span className={`lv-chip k-${d.tone}`}>{d.chip}</span>
          <span className={`lv-t${d.chip === "Tool" || d.chip === "Skill" ? " lv-mono" : ""}`}>{d.title}</span>
          {d.status ? <span className={`lv-chip k-${d.bad ? "bad" : "ok"}`}><Ico n={d.bad ? "alert" : "check"} sm />{d.status}</span> : null}
          {r.agent ? <span className="lv-who-sm">{splitAgent(r.agent)[0]}</span> : null}
          <time className="lv-time" dateTime={r.ts}>{r.ts ? new Date(r.ts).toLocaleTimeString("en-NZ") : ""}</time>
        </div>
        {d.meta.length || d.pending ? (
          <div className="lv-meta">{d.meta.filter(Boolean).map((m, i) => <span key={i}>{m}</span>)}
            {d.pending ? <span><b><Clock since={r.ts} /></b> so far</span> : null}</div>) : null}
        {blocks.length ? (
          <div className="lv-tabs">{blocks.map(([k]) => (
            <button key={k} type="button" className="lv-tab" aria-expanded={open === k} aria-controls={`${id}-blk`}
              onClick={() => setOpen(open === k ? null : k)}>
              <Ico n="chev" sm className="lv-chev" />{k}</button>))}
          </div>) : null}
        {open && blocks.some(([k]) => k === open) ? (
          <pre className="lv-blk" id={`${id}-blk`} aria-label={open}>{txt(blocks.find(([k]) => k === open)[1])}</pre>) : null}
      </div>
    </li>);
}

export function LiveView({ recs, live }) {
  const [cat, setCat] = useState("all");
  const [agent, setAgent] = useState("");
  const stats = agentStats(recs);
  const cards = pairCalls(recs).filter((r) => !agent || r.agent === agent).map((r) => ({ r, d: describe(r) }));
  const count = (k) => (k === "all" ? cards.length : cards.filter(({ d }) => d.cats.includes(k)).length);
  const shown = cards.filter(({ d }) => cat === "all" || d.cats.includes(cat));
  const answered = recs.filter((r) => r.kind === "llm.end" && r.status === "ok");
  return (
    <section className="stack lv" aria-labelledby="lv-h">
      <div className="hdr runsec"><h2 id="lv-h">Live activity</h2>
        <span className="sub">{plural(recs.length, "record")}</span></div>
      <LiveNote live={live} />
      <Strip recs={recs} />
      {recs.length ? (
        <div className="lv-grid">
          <Rail stats={stats} agent={agent} onPick={setAgent} />
          <div className="lv-main">
            <div className="lv-filters" role="group" aria-label="Show">
              {FILTERS.map(([k, label, tone]) => (
                <button key={k} type="button" className="lv-f" aria-pressed={cat === k} onClick={() => setCat(k)}>
                  {tone ? <Ico n={tone} sm className={`k-${tone}`} /> : null}{label}
                  <span className="lv-n">{count(k)}</span></button>))}
            </div>
            {answered.length > 0 && !answered.some((r) => r.reasoning) ? (
              <p className="small muted">These models returned no thinking text, so Thinking shows nothing.</p>) : null}
            {shown.length > SHOW ? <p className="small muted">{`Showing the latest ${SHOW} of ${shown.length}; narrow with the filters or pick an agent. The full log is kept on the server.`}</p> : null}
            {shown.length ? (
              <ol className="lv-tl" aria-label={`${agent ? splitAgent(agent)[0] : "All agents'"} activity, newest first`}>
                {shown.slice(-SHOW).reverse().map(({ r, d }) => <Card key={r._id} r={r} d={d} />)}
              </ol>) : <p className="lv-empty">Nothing of this kind yet.</p>}
          </div>
        </div>) : null}
    </section>
  );
}
