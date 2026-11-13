// Run inspection (05 §5): drawer beside the Work plan, or the full page at #/runs/{rid}.
// Identity, state, stage timeline with each stage's output, per-agent tokens (C's meters),
// and the permission-gated actions (interject, pause/resume, cancel, redirect a pending stage).
import { useEffect, useMemo, useState } from "react";
import { post } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { useApi } from "../useApi.js";
import { AGENT_STATES, ErrorLine, Loading, StatusChip, allowed, fmtAgo, fmtTokens } from "../ui.jsx";
import { ApprovalCard } from "./Approvals.jsx";
import { CommandError, useCommand } from "./Workspace.jsx";

// the persisted reads one run overview needs; every one is matter-scoped server-side
function useRunData(rid, mid, on = true) {
  const run = useApi(on ? `/runs/${rid}` : null, { matter: mid });
  const matter = mid || run.data?.matter_id;
  const opt = { matter };
  return {
    run,
    tasks: useApi(matter ? `/executions/${rid}/tasks` : null, opt),
    tokens: useApi(matter ? `/matters/${matter}/tokens` : null, opt),
    matter: useApi(matter ? `/matters/${matter}` : null, opt),
    // shortcut: first 200 artifacts only (oldest-first paging); page on if a matter ever exceeds it
    artifacts: useApi(matter ? `/matters/${matter}/artifacts?limit=200` : null, opt),
    approvals: useApi(matter ? `/matters/${matter}/approvals` : null, opt),
  };
}

export function RunDrawer({ rid, mid, onClose }) {
  const { perms } = useCtx();
  const d = useRunData(rid, mid);
  const [text, setText] = useState("");
  const [st, cmd] = useCommand();
  const canAct = allowed(perms, "matter.dispatch");     // 05 §12: hidden, not disabled
  if (d.run.error && !d.run.data) return <ErrorLine error={d.run.error} onRetry={d.run.reload} />;
  if (!d.run.data) return <Loading />;
  const r = d.run.data;
  const live = LIVE.has(r.state);
  return (
    <aside className="card" style={{ padding: "14px 16px" }} aria-label={`Run ${rid}`}>
      <RunOverview {...d} level={2} onClose={onClose}
        onRedirect={(t) => {
          const instruction = prompt(`New instruction for stage "${t.key}"`);
          if (instruction) cmd(() => post(`/executions/${rid}/redirect`, { task_id: t.task_id, instruction }));
        }} />
      <CommandError error={st.error} />
      {st.pending ? <p className="muted" role="status">Pending… waiting for the worker to confirm.</p> : null}
      {canAct && live ? (
        <div className="stack">
          <p>
            {r.state === "paused"
              ? <button type="button" className="btn" onClick={() => cmd(() => post(`/executions/${rid}/resume`))}>Resume</button>
              : r.state === "executing"   // a run parked at an approval is decided, not paused
                ? <button type="button" className="btn" onClick={() => cmd(() => post(`/executions/${rid}/pause`))}>Pause</button> : null}{" "}
            <button type="button" className="btn" onClick={() => {
              if (confirm("Cancel this run? Stages not yet run will not run.")) cmd(() => post(`/runs/${rid}/cancel`));
            }}>Cancel run</button>
          </p>
          <form onSubmit={async (e) => { e.preventDefault(); if (await cmd(() => post(`/runs/${rid}/interject`, { text }))) setText(""); }}>
            <label htmlFor={`inj-${rid}`}>Interject <span className="hint">(delivered at the next stage boundary)</span></label>
            <textarea id={`inj-${rid}`} rows="2" required value={text} onChange={(e) => setText(e.target.value)} />
            <button type="submit" className="btn">Send</button>
          </form>
        </div>) : null}
    </aside>
  );
}

// -- swarm (D-3 pick: B's lanes + C's meters; firm-only per §9A.2) ------------------
// The orchestrator's plan is strictly sequential (tasks.seq): lanes group consecutive
// stages, nothing here invents parallel branches.
const LANE = { intake: "Intake", research: "Research", strategy: "Strategy & attack", attack: "Strategy & attack",
  assess: "Strategy & attack", filings: "Filings & moot", moot: "Filings & moot", advice: "Advice & close",
  verify: "Advice & close", close: "Advice & close" };
const title = (s) => { s = String(s || "").replace(/[-_]/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); };
const LIVE = new Set(["executing", "waiting_human", "paused"]);

export function swarmLanes(tasks) {
  const lanes = [];
  for (const t of [...(tasks || [])].sort((a, b) => a.seq - b.seq)) {
    const name = LANE[t.key] || title(t.key);
    if (lanes.at(-1)?.name === name) lanes.at(-1).tasks.push(t);
    else lanes.push({ name, tasks: [t] });
  }
  return lanes;
}

export function nodeView(t, parked = false) {
  if (parked) return ["wait", "⏸ Awaiting your approval"];
  return { completed: ["ok", "✓ Done"], running: ["run", "● Running"], failed: ["bad", "✕ Failed"],
    timed_out: ["bad", "⏱ Timed out"], cancelled: ["idle", "⊘ Cancelled"] }[t.state] || ["idle", "○ Not started"];
}

// a run parks right after its approval stage completes: the last completed stage carries the kind
export function parkedTask(tasks, runState) {
  if (runState !== "waiting_human") return null;
  const last = [...(tasks || [])].sort((a, b) => a.seq - b.seq).filter((t) => t.state === "completed").at(-1);
  return last?.approval_kind ? last.task_id : null;
}

// the stage that needs attention: the parked approval stage, else the first unfinished one
export function currentTask(tasks, runState) {
  return parkedTask(tasks, runState)
    ?? [...(tasks || [])].sort((a, b) => a.seq - b.seq).find((t) => t.state !== "completed")?.task_id ?? null;
}

// -- UX-2 execution overview (NEXT_STEPS §9B.2) -------------------------------------
// Every word below comes from persisted API state: execution.state, tasks.state/attempts/
// lease_expires_at, the run's own workflow events, approvals and artifacts. Nothing is
// estimated in the browser; a missing value renders as unavailable, never as done.
const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const DT = new Intl.DateTimeFormat("en-NZ", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const at = (iso) => `${DT.format(new Date(iso))} (${fmtAgo(iso)})`;
const word = (s) => (AGENT_STATES[s] || [, , String(s || "unknown").replace(/_/g, " ")])[2];
const bySeq = (tasks) => [...(tasks || [])].sort((a, b) => a.seq - b.seq);

// a stage's state as the overview shows it. The backend's own value wins except where persisted
// state proves more: the parked approval stage, a lease that expired with no heartbeat (as of the
// last load — `asOf`, epoch seconds), and stages a halted run will never reach.
export function stageState(t, runState, parked, asOf = 0) {
  if (t.task_id === parked) return "waiting_human";
  if (t.state === "running" && runState === "executing" && t.lease_expires_at && t.lease_expires_at <= asOf) return "interrupted";
  if (t.state === "pending" && (runState === "failed" || runState === "cancelled")) return "not_run";
  return t.state;
}

// first start → last finish per stage, from the run's own events (a retry keeps its first start)
export function stageTimes(events) {
  const out = {};
  for (const e of events || []) {
    if (!e.task_id) continue;
    const o = (out[e.task_id] ||= {});
    if (e.type === "task.running") { o.start ??= e.ts; delete o.end; }
    else if (e.type === "task.completed" || e.type === "task.failed") o.end = e.ts;
  }
  return out;
}

const EVENT = { "execution.created": "Run created", "execution.completed": "Run completed",
  "execution.failed": "Run stopped: failed", "execution.state_changed": "Run state changed (pause, resume or cancel)",
  "chat.replied": "Lead counsel replied in the chat", "task.running": "started", "task.completed": "completed",
  "task.failed": "failed" };
export function eventLine(e, byId) {
  const t = e.task_id ? byId[e.task_id] : null;
  if (e.type?.startsWith("task.")) return `Stage ${t ? t.key : e.task_id} ${EVENT[e.type] || e.type.slice(5)}`;
  return `${EVENT[e.type] || e.type}${t && e.type === "execution.failed" ? ` at stage ${t.key}` : ""}`;
}

// what the run needs from a person right now, strictly from execution.state + pending approvals
export function nextAction(r, ts, states, approvals) {
  const failedT = ts.find((t) => t.state === "failed");
  const stuck = ts.find((t) => states[t.task_id] === "interrupted");
  switch (r.state) {
    case "waiting_human": return { tone: "wait", title: "Your approval is needed",
      text: approvals.length ? "This run is parked until the checkpoint below is decided." :
        "This run is parked at a checkpoint; its approval is not in the pending list — it may have just been decided." };
    case "paused": return { tone: "wait", title: "Paused — waiting for someone to resume it", text: "No further stages start until the run is resumed." };
    case "failed": return { tone: "bad", title: failedT ? `Stopped: stage ${failedT.key} failed` : "Stopped: the run failed",
      text: failedT ? "Later stages did not run. The stage's error is in its details below." : "No stage recorded an error for this failure." };
    case "cancelled": return { tone: "idle", title: "Cancelled", text: "Stages that had not started will not run." };
    case "completed": return { tone: "done", title: "Completed — ready for your review", text: "Review the deliverables this run produced." };
    case "executing": return stuck
      ? { tone: "bad", title: `Stage ${stuck.key} stopped reporting`, text: `Its worker missed its heartbeat as of the last update; the stage is re-claimed automatically (attempt ${stuck.attempts} of ${stuck.max_attempts} so far). No action is needed unless it stays here.` }
      : { tone: "idle", title: "No action needed from you right now", text: "The run is working through its stages." };
    default: return { tone: "idle", title: `Run state: ${word(r.state)}`, text: "This state is not one the overview recognises; nothing is assumed about it." };
  }
}

const fmtSpan = (a, b) => (a && b && Date.parse(b) >= Date.parse(a) ? fmtDur(Date.parse(b) - Date.parse(a)) : null);

export function RunOverview({ run, tasks, tokens, matter, artifacts, approvals, level = 2, stages = true,
  onClose, onRedirect = () => {}, asOf: asOfProp }) {
  const { perms, mode, live } = useCtx();
  const [force, setForce] = useState(null);             // Expand/Collapse all; n re-applies a repeat press
  const r = run.data;
  // "now" for lease checks = when this snapshot loaded, so an old snapshot never ages into a failure
  const loadedAt = useMemo(() => Date.now() / 1000, [r, tasks.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const asOf = asOfProp ?? loadedAt;
  const ts = bySeq(tasks.data);
  const byId = Object.fromEntries(ts.map((t) => [t.task_id, t]));
  const parked = parkedTask(ts, r.state);
  const states = Object.fromEntries(ts.map((t) => [t.task_id, stageState(t, r.state, parked, asOf)]));
  const times = stageTimes(r.events);
  const appr = (approvals.data || []).filter((a) => a.execution_id === r.execution_id);
  const outs = (artifacts.data?.items || []).filter((a) => a.execution_id === r.execution_id);
  const act = nextAction(r, ts, states, appr);
  const H = `h${level}`, H2 = `h${level + 1}`;
  const firm = mode !== "self-rep";
  const counts = {};
  for (const t of ts) counts[states[t.task_id]] = (counts[states[t.task_id]] || 0) + 1;
  const done = counts.completed || 0;   // same per-stage state as the counts, so the line adds up to N
  const last = r.events?.at(-1)?.ts;
  const end = r.ended_at || (TERMINAL.has(r.state) ? null : new Date(asOf * 1000).toISOString());
  const span = fmtSpan(r.started_at, end);
  const agents = [];
  for (const t of ts) {
    const g = agents.find((a) => a.id === t.agent_id);
    if (g) g.keys.push(t.key); else agents.push({ id: t.agent_id, keys: [t.key] });
  }
  const byAgent = Object.fromEntries((tokens.data?.agents || []).map((a) => [a.agent, a]));
  return (
    <section className="stack runov" aria-label="Run overview">
      <div className="hdr">
        <H style={{ margin: 0 }}>Run <span className="mono">{r.execution_id}</span> <StatusChip kind="agent" state={r.state} /></H>
        {onClose ? <span className="act"><button type="button" className="btn" onClick={onClose} aria-label="Close run inspection">Close</button></span> : null}
      </div>
      {live === "reconnecting" && !TERMINAL.has(r.state) ? (
        <p className="stale" role="status">◐ Live updates are disconnected — this is the run as last loaded. It carries on on the server; the page catches up when the connection returns.</p>) : null}
      <ErrorLine error={run.error} onRetry={run.reload} stale />
      <dl className="kv">
        <dt>Matter</dt><dd><a href={href(firm ? "workspace" : "case", { mid: r.matter_id })}>{matter.data?.title || r.matter_id}</a></dd>
        <dt>Task</dt><dd>{r.input_task_text || "—"}</dd>
        <dt>Started</dt><dd>{r.started_at ? at(r.started_at) : "—"}</dd>
        {r.ended_at ? <><dt>Ended</dt><dd>{at(r.ended_at)}</dd></> : null}
        <dt>{r.ended_at ? "Duration" : "Elapsed"}</dt><dd>{span ? (r.ended_at ? span : `${span} so far`) : "Not available"}</dd>
        <dt>Last update</dt><dd>{last ? at(last) : "No events recorded"}</dd>
        <dt>Tokens</dt><dd className="tokens">{tokens.data
          ? `${fmtTokens(tokens.data.total?.all)} across this matter (all runs) · a per-run total is not recorded`
          : tokens.error ? "Unavailable" : "…"}</dd>
      </dl>
      <div className={`banner nextact nextact--${act.tone}`} role={act.tone === "bad" || act.tone === "wait" ? "alert" : "status"}>
        <p className="banner__title"><span aria-hidden="true">{{ wait: "⚑", bad: "✕", done: "✓" }[act.tone] || "○"} </span>{act.title}</p><p style={{ margin: 0 }}>{act.text}</p>
        {r.state === "waiting_human" ? <>
          {appr.map((a) => <ApprovalCard key={a.approval_id} a={a} onDone={approvals.reload} />)}
          <p className="small">Also in the <a href={href("approvals")}>Approval Center</a>.</p></> : null}
      </div>
      <div className="hdr">
        <H2 style={{ fontSize: "var(--fs-sm)", margin: 0 }}>Stages</H2>
        <span className="sub">{ts.length ? [`${done} of ${ts.length} complete`, ...Object.entries(counts)
          .filter(([s]) => s !== "completed").map(([s, n]) => `${n} ${word(s).toLowerCase()}`)].join(" · ") : ""}</span>
        {stages && ts.length ? <span className="act">
          <button type="button" className="btn" onClick={() => setForce((f) => ({ open: true, n: (f?.n || 0) + 1 }))}>Expand all</button>{" "}
          <button type="button" className="btn" onClick={() => setForce((f) => ({ open: false, n: (f?.n || 0) + 1 }))}>Collapse all</button>
        </span> : null}
      </div>
      {ts.length ? <>
        <div className="bar2" aria-hidden="true"><i style={{ width: `${Math.round((100 * done) / ts.length)}%` }} /></div>
        <p className="small">Stages run one at a time in plan order; each starts only after every earlier stage has completed.
          {stages ? "" : " Select a stage in the team view below to inspect it."}</p>
      </> : null}
      <ErrorLine error={tasks.error} onRetry={tasks.reload} stale={!!tasks.data} />
      {stages ? <>
        {tasks.data === undefined ? (tasks.error ? null : <Loading rows={2} />) : ts.length === 0
          ? <p className="muted">No stage details were recorded for this run.</p>
          : <StageList tasks={ts} runState={r.state} states={states} times={times} force={force}
            canAct={allowed(perms, "matter.dispatch")} live={LIVE.has(r.state)} onRedirect={onRedirect} />}
        {agents.length ? <>
          <H2 style={{ fontSize: "var(--fs-sm)", margin: 0 }}>Agents</H2>
          <table className="table" aria-label="Agents in this run">
            <thead><tr><th scope="col">Agent</th><th scope="col">Stages</th><th scope="col">Tokens on this matter</th></tr></thead>
            <tbody>{agents.map((g) => {
              const a = byAgent[g.id];   // matter-wide per agent: shown once per agent, never per stage
              return (<tr key={g.id || "-"}><td>{g.id || "agent"}</td><td>{g.keys.join(", ")}</td>
                <td className="tokens">{a ? `${fmtTokens(a.all)} · in ${fmtTokens(a.in)} · out ${fmtTokens(a.out)} · think ${fmtTokens(a.thinking)}` : "None recorded"}</td></tr>);
            })}</tbody>
          </table></> : null}
      </> : null}
      <H2 style={{ fontSize: "var(--fs-sm)", margin: 0 }}>Deliverables</H2>
      <ErrorLine error={artifacts.error} onRetry={artifacts.reload} stale={!!artifacts.data} />
      {artifacts.data === undefined ? (artifacts.error ? null : <Loading rows={1} />) : outs.length ? (
        <ul className="links">{outs.map((a) => (
          <li key={a.artifact_id}><a href={href("workspace", { mid: r.matter_id, tab: "drafts" })}>{a.title || a.artifact_id}</a>{" "}
            <span className="muted">· {a.kind || "artifact"} · {String(a.review_state || "unreviewed").replace(/_/g, " ")}{a.created_at ? ` · ${at(a.created_at)}` : ""}</span></li>))}
        </ul>) : <p className="muted">{TERMINAL.has(r.state) ? "This run recorded no deliverables." : "No deliverables yet."}</p>}
      <details>
        <summary>Run history ({(r.events || []).length} event{(r.events || []).length === 1 ? "" : "s"}{(r.events || []).length >= 200 ? ", latest 200" : ""})</summary>
        {(r.events || []).length ? (
          <ol className="timeline timeline--activity">{r.events.map((e) => (
            <li key={e.id} data-state={/completed$/.test(e.type) ? "done" : undefined}>
              <time dateTime={e.ts}>{e.ts ? DT.format(new Date(e.ts)) : "—"}</time>{eventLine(e, byId)}</li>))}
          </ol>) : <p className="muted">No events recorded for this run.</p>}
      </details>
    </section>
  );
}

// drawer stage list (A): each stage collapses; only the current one opens by default.
// The key folds in force.n and isCur so a row re-takes its default only on a button press or a
// change of current stage — a manual toggle survives the polling re-renders.
export function StageList({ tasks, runState, canAct, live, onRedirect, force, states = {}, times = {} }) {
  const ts = bySeq(tasks);
  const cur = currentTask(ts, runState);
  return (
    <ol className="timeline timeline--activity" aria-label="Stages in execution order">
      {ts.map((t, i) => {
        const s = states[t.task_id] ?? stageState(t, runState, parkedTask(ts, runState));
        const isCur = t.task_id === cur && !TERMINAL.has(runState);
        const tm = times[t.task_id] || {};
        const span = fmtSpan(tm.start, tm.end);
        return (
          <li key={`${t.task_id}-${force?.n ?? 0}-${isCur}`} aria-current={isCur ? "step" : undefined}
            data-state={s === "completed" ? "done" : s === "failed" || s === "interrupted" ? "failed" : undefined}>
            <details open={force ? force.open : isCur}>
              <summary><span className="muted">{i + 1}.</span> <b>{t.key}</b> <span className="muted">· {t.agent_id || "agent"}</span>{" "}
                <StatusChip kind="agent" state={s} />
                {span ? <span className="tokens"> · {span}</span> : null}</summary>
              <dl className="kv">
                <dt>Agent</dt><dd>{t.agent_id || "Not recorded"}</dd>
                <dt>Task</dt><dd>{t.instruction || "—"}</dd>
                {tm.start ? <><dt>Started</dt><dd>{at(tm.start)}</dd></> : null}
                {tm.end ? <><dt>Finished</dt><dd>{at(tm.end)}</dd></> : null}
                {t.attempts > 1 || s === "failed" || s === "interrupted"
                  ? <><dt>Attempts</dt><dd>{`${t.attempts ?? "?"} of ${t.max_attempts ?? "?"}`}</dd></> : null}
                {t.approval_kind ? <><dt>Checkpoint</dt><dd>{`Approval (${t.approval_kind}) after this stage`}</dd></> : null}
              </dl>
              {t.result_summary ? <p style={{ margin: "4px 0", whiteSpace: "pre-wrap" }}>
                {s === "failed" ? <b>Error: </b> : null}{t.result_summary}</p>
                : s === "completed" ? <p className="muted">No summary recorded.</p> : null}
              {canAct && t.state === "pending" && live ? (
                <button type="button" className="btn" onClick={() => onRedirect(t)}>Redirect</button>) : null}
            </details>
          </li>);
      })}
    </ol>
  );
}

export function stageOf(tasks) {
  const ts = [...(tasks || [])].sort((a, b) => a.seq - b.seq);
  const i = ts.findIndex((t) => t.state !== "completed");
  return i === -1 ? ts.length : i + 1;
}

export function durations(events) {
  const start = {}, out = {};
  for (const e of events || []) {
    if (!e.task_id) continue;
    if (e.type === "task.running" && !(e.task_id in start)) start[e.task_id] = Date.parse(e.ts);
    if (/^task\.(completed|failed)$/.test(e.type) && e.task_id in start) out[e.task_id] = Date.parse(e.ts) - start[e.task_id];
  }
  return out;
}

// runs last hours or days: "2h 05m" past the hour, else "4m 07s"
export const fmtDur = (ms) => {
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(s % 60).padStart(2, "0")}s`;
};

export function SwarmView({ run: r, tasks, tokens, canAct, st, cmd, sel, onSelect = () => {}, onInterject = () => {} }) {
  const [hide, setHide] = useState(false);
  const [text, setText] = useState("");
  const ts = [...(tasks || [])].sort((a, b) => a.seq - b.seq);
  const rid = r.execution_id;
  const byAgent = Object.fromEntries((tokens?.agents || []).map((a) => [a.agent, a]));
  const parked = parkedTask(ts, r.state);
  const dur = durations(r.events);
  const live = LIVE.has(r.state);
  const seen = {};
  for (const t of ts) seen[t.agent_id] = (seen[t.agent_id] || 0) + 1;
  // an agent that works several stages is named by stage, so nodes stay distinguishable
  const label = (t) => `${title(t.agent_id || "agent")}${seen[t.agent_id] > 1 ? ` · ${t.key}` : ""}${t.task_id === parked ? " ⚑" : ""}`;
  const cur = ts.find((t) => t.task_id === sel) || ts.find((t) => t.task_id === parked)
    || ts.find((t) => t.state === "running") || ts.find((t) => t.state !== "completed") || ts.at(-1);
  const lanes = swarmLanes(ts)
    .map((l) => ({ ...l, tasks: hide ? l.tasks.filter((t) => t.state !== "completed" || t.task_id === parked) : l.tasks }))
    .filter((l) => l.tasks.length);
  const a = cur ? byAgent[cur.agent_id] : null;
  return (
    <section aria-labelledby="swarm-h">
      <div className="hdr"><h2 id="swarm-h">The team at work</h2>
        <span className="sub">{`${rid} · stage ${stageOf(ts)} of ${ts.length} · ${fmtTokens(tokens?.total?.all)} tokens`}</span>
        <span className="act">
          <button type="button" className="btn" aria-pressed={hide} onClick={() => setHide(!hide)}>Hide finished</button>
          {canAct && live ? <>
            {r.state === "paused"
              ? <button type="button" className="btn" onClick={() => cmd(() => post(`/executions/${rid}/resume`))}>Resume</button>
              : r.state === "executing"   // a run parked at an approval is decided, not paused
                ? <button type="button" className="btn" onClick={() => cmd(() => post(`/executions/${rid}/pause`))}>Pause</button> : null}
            <button type="button" className="btn" onClick={() => {
              if (confirm("Cancel this run? Stages not yet run will not run.")) cmd(() => post(`/runs/${rid}/cancel`));
            }}>Cancel</button></> : null}
        </span></div>
      <CommandError error={st.error} />
      {st.pending ? <p className="muted" role="status">Pending… waiting for the worker to confirm.</p> : null}
      <div className="swarmwrap">
        <div className="lanes" role="list" aria-label="Agent runs by stage, left to right"
          style={{ gridTemplateColumns: `repeat(${lanes.length || 1},minmax(120px,1fr))` }}>
          {lanes.map((l) => (
            <div className="lane" role="listitem" key={l.tasks[0].task_id}>
              <h3>{l.name} <span>{l.tasks.length}</span></h3>
              {l.tasks.map((t) => {
                const [cls, word] = nodeView(t, t.task_id === parked);
                const tk = byAgent[t.agent_id];
                const meta = [dur[t.task_id] != null ? fmtDur(dur[t.task_id]) : null, tk ? fmtTokens(tk.all) : null].filter(Boolean);
                return (
                  <button type="button" key={t.task_id} className={`card node ${cls}`} aria-pressed={t === cur}
                    onClick={() => onSelect(t.task_id)}>
                    <b>{label(t)}</b><span className="s">{word}</span>
                    {meta.length ? <span className="m">{meta.join(" · ")}</span> : null}
                  </button>);
              })}
            </div>))}
        </div>
        {cur ? (
          <aside className="card drawer" aria-label="Agent inspection">
            <h3>{`${label(cur)} · stage ${ts.indexOf(cur) + 1} of ${ts.length}`}</h3>
            <dl className="kv">
              <dt>State</dt><dd>{nodeView(cur, cur.task_id === parked)[1]}{dur[cur.task_id] != null ? ` · ${fmtDur(dur[cur.task_id])}` : ""}</dd>
              <dt>Goal</dt><dd>{cur.instruction}</dd>
              <dt>Tokens</dt><dd className="tokens">{a ? `${fmtTokens(a.all)} · in ${fmtTokens(a.in)} · out ${fmtTokens(a.out)} · think ${fmtTokens(a.thinking)}` : "none recorded for this agent"}</dd>
              {cur.attempts > 1 ? <><dt>Attempts</dt><dd>{`${cur.attempts} of ${cur.max_attempts}`}</dd></> : null}
            </dl>
            {canAct && live && cur.state === "pending" ? (
              <button type="button" className="btn" onClick={() => {
                const instruction = prompt(`New instruction for stage "${cur.key}"`);
                if (instruction) cmd(() => post(`/executions/${rid}/redirect`, { task_id: cur.task_id, instruction }));
              }}>Redirect</button>) : null}
            {cur.result_summary ? <pre className="log">{cur.result_summary}</pre> : null}
            {canAct && live ? (
              <form onSubmit={async (e) => {
                e.preventDefault();
                const res = await cmd(() => post(`/runs/${rid}/interject`, { text }));
                if (res) { setText(""); onInterject(res.data); }
              }}>
                <label htmlFor={`inj-${rid}`}>Interject <span className="hint">(delivered at the next stage boundary)</span></label>
                <textarea id={`inj-${rid}`} rows="2" required value={text} onChange={(e) => setText(e.target.value)} />
                <button type="submit" className="btn">Send</button>
              </form>) : null}
          </aside>) : null}
      </div>
    </section>
  );
}

// -- counsel chat (D-3 pick C: docked under the swarm, A's four rail cards) ----------
// Turn-based: the worker posts the lead's reply when the execution a message started completes.
export function unanswered(messages) {
  const replied = new Set((messages || []).filter((m) => m.role === "lead").map((m) => m.execution_id));
  return new Set((messages || []).filter((m) => m.role === "user" && m.execution_id && !replied.has(m.execution_id))
    .map((m) => m.message_id));
}

const hm = (ts) => (ts ? new Date(ts).toLocaleTimeString("en-NZ", { hour: "2-digit", minute: "2-digit" }) : "");
const ST = { executing: "run", waiting_human: "wait", paused: "wait", completed: "done" };

export function ChatDock({ run: r, tasks, messages, approvals, artifacts, interjections, canSend, st, onSend, inlineApproval = true }) {
  const [text, setText] = useState("");
  const ts = [...(tasks || [])].sort((a, b) => a.seq - b.seq);
  const msgs = messages || [];
  const open = unanswered(msgs);
  const done = ts.filter((t) => t.state === "completed").length;
  const cur = ts.find((t) => t.state !== "completed");
  const byId = Object.fromEntries(ts.map((t) => [t.task_id, t]));
  const reached = [...(r.events || [])].reverse().find((e) => e.type === "task.running" && byId[e.task_id]);
  const latest = [...(artifacts || [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 3);
  const appr = approvals || [];
  const send = async () => { if (text.trim() && await onSend(text.trim())) setText(""); };
  const cid = `chat-${r.execution_id}`;
  return (
    <div className="bottom">
      <section className="card chat" aria-label="Conversation: supervision">
        <div className="ch"><h2>Counsel chat — Supervision</h2><span>{`${msgs.length} message${msgs.length === 1 ? "" : "s"} · replies land here when stages close`}</span></div>
        <div className="msgs">
          {msgs.map((m) => (
            <div key={m.message_id} className={m.role === "lead" ? "msg lead" : "msg"}>
              <div className="who"><b>{m.role === "lead" ? "Lead counsel" : "You"}</b> · {hm(m.ts)}</div>
              <div className="body">{m.text}</div>
              {open.has(m.message_id) ? <div className="pending" role="status"><span className="dot"></span> pending…</div> : null}
            </div>))}
          {reached ? <div className="sys">{`↳ ${byId[reached.task_id].key} stage reached ${hm(reached.ts)} (live, from the lanes above)`}</div> : null}
          {inlineApproval && appr.length ? <div className="appr"><ApprovalCard a={appr[0]} /></div> : null}
        </div>
        {canSend ? (
          <form className="comp" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <label htmlFor={cid} className="small">Instruction to lead counsel</label>
            <textarea id={cid} value={text} onChange={(e) => setText(e.target.value)}
              placeholder="Type an instruction… (enter sends, shift+enter newline)"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <div className="row"><span className="hint">Send → 202 · appears in the lanes above as pending…</span>
              <button type="submit" className="btn btn--primary" disabled={st.busy}>Send</button></div>
            <CommandError error={st.error} />
            {st.pending ? <p className="muted" role="status">Pending… waiting for the worker to confirm.</p> : null}
          </form>) : <CommandError error={st.error} />}
      </section>
      <aside className="ctxrail" aria-label="Run context">
        <div className="card"><h3>Execution</h3>
          <dl className="kv">
            <dt>Run</dt><dd><a href={href("run", { rid: r.execution_id })} className="mono">{r.execution_id}</a></dd>
            <dt>State</dt><dd><span className={`st ${ST[r.state] || ""}`}>{r.state}{cur ? ` · stage ${stageOf(ts)}/${ts.length} (${cur.key})` : ""}</span></dd>
            <dt>Started</dt><dd>{fmtAgo(r.started_at)}</dd>
          </dl>
          <div className="bar2"><i style={{ width: `${ts.length ? Math.round((100 * done) / ts.length) : 0}%` }}></i></div>
          <span className="small">{`${done} of ${ts.length} stages complete`}</span></div>
        <div className="card"><h3>Latest artifacts</h3>
          {latest.length ? (
            <ul className="links">{latest.map((a) => (
              <li key={a.artifact_id}><a href={href("workspace", { mid: r.matter_id, tab: "drafts" })} className="mono">{a.artifact_id}</a> {a.title}</li>))}
            </ul>) : <p className="small">None yet.</p>}</div>
        <div className="card"><h3>Open approvals</h3>
          <p className="small"><span className={appr.length ? "st wait" : "st"}>{appr.length ? `${appr.length} ⚑ pending` : "None pending"}</span>
            {appr.length ? ` — ${appr.map((a) => a.kind).join(", ")}` : ""}</p>
          <p className="small">Also in the <a href={href("approvals")}>Approval Center</a>.</p></div>
        <div className="card"><h3>Interjections</h3>
          {(interjections || []).length ? interjections.map((i) => (
            <p className="small" key={i.interjection_id}>{`“${i.text}” — `}<b>delivered at next boundary</b> {hm(i.at)}</p>))
            : <p className="small">None sent from this page.</p>}</div>
      </aside>
    </div>
  );
}

export default function RunPage({ rid }) {
  const { perms, mode } = useCtx();
  const firm = mode === "firm";
  const d = useRunData(rid, undefined, firm);   // self-rep: RunDrawer below does its own reads
  const { run, tasks, tokens: tk, artifacts: arts, approvals: appr } = d;
  const mid = run.data?.matter_id;
  const convs = useApi(firm && mid ? `/matters/${mid}/conversations` : null, { matter: mid });
  const conv = (convs.data || []).find((c) => c.title === "Supervision") || convs.data?.[0];
  const msgs = useApi(conv ? `/conversations/${conv.conversation_id}/messages` : null, { matter: mid });
  const [st, cmd, reset] = useCommand();
  const [chat, chatCmd, chatReset] = useCommand();
  const [sel, setSel] = useState(null);
  // interjections are write-only in the API: only what this page sent is known here
  const [sent, setSent] = useState([]);
  // a 202 stays "pending…" until the confirming SSE event refetches the run (05 §10)
  useEffect(() => { reset(); }, [run.data, tasks.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { chatReset(); }, [msgs.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const onSend = (text) => chatCmd(async () => {
    let cid = conv?.conversation_id;    // the thread is created on first send, never on view
    if (!cid) cid = (await post(`/matters/${mid}/conversations`, { title: "Supervision" })).data.conversation_id;
    const res = await post(`/conversations/${cid}/messages`, { text });
    if (!conv) convs.reload();
    return res;
  });
  if (!firm) return (   // the swarm is firm-only (§9A.2): self-rep keeps the plain inspection view
    <section aria-labelledby="run-h">
      <div className="hdr"><h1 id="run-h">Run inspection</h1></div>
      <RunDrawer rid={rid} />
    </section>);
  // a failed refetch keeps the last snapshot on screen (the overview says it is stale)
  if (run.error && !run.data) return <ErrorLine error={run.error} onRetry={run.reload} />;
  if (tasks.error && !tasks.data) return <ErrorLine error={tasks.error} onRetry={tasks.reload} />;
  if (!run.data || !tasks.data) return <Loading />;
  const canAct = allowed(perms, "matter.dispatch");
  return (<>
    {/* firm: the swarm below is the stage map + per-stage inspection, so the overview skips its own list */}
    <RunOverview {...d} level={1} stages={false} />
    <SwarmView run={run.data} tasks={tasks.data} tokens={tk.data} canAct={canAct}
      st={st} cmd={cmd} sel={sel} onSelect={setSel}
      onInterject={(d) => setSent((s) => [...s, { ...d, at: new Date().toISOString() }])} />
    <ChatDock run={run.data} tasks={tasks.data} messages={msgs.data?.items} approvals={appr.data}
      artifacts={arts.data?.items} interjections={sent} canSend={canAct} st={chat} onSend={onSend}
      inlineApproval={false} />{/* the overview above carries the decision; one set of controls per page */}
  </>);
}
