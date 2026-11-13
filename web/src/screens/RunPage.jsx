// Run inspection (05 §5): drawer beside the Work plan, or the full page at #/runs/{rid}.
// Identity, state, stage timeline with each stage's output, per-agent tokens (C's meters),
// and the permission-gated actions (interject, pause/resume, cancel, redirect a pending stage).
import { useEffect, useMemo, useRef, useState } from "react";
import { post } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { EVENT as EVENT_BUS, useApi } from "../useApi.js";
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

// run-level commands, beside the run's status (05 §12: hidden without matter.dispatch, not disabled)
export function RunControls({ run: r, canAct, cmd }) {
  if (!canAct || !LIVE.has(r.state)) return null;
  const rid = r.execution_id;
  return <>
    {r.state === "paused"
      ? <button type="button" className="btn btn--primary" onClick={() => cmd(() => post(`/executions/${rid}/resume`))}>Resume</button>
      : r.state === "executing"   // a run parked at an approval is decided, not paused
        ? <button type="button" className="btn" onClick={() => cmd(() => post(`/executions/${rid}/pause`))}>Pause</button> : null}
    <button type="button" className="btn" onClick={() => {
      if (confirm("Cancel this run? Stages not yet run will not run.")) cmd(() => post(`/runs/${rid}/cancel`));
    }}>Cancel</button>
  </>;
}

// -- swarm (D-3 pick: B's node cards + C's meters; firm-only per §9A.2) -------------
const title = (s) => { s = String(s || "").replace(/[-_]/g, " "); return s.charAt(0).toUpperCase() + s.slice(1); };
const LIVE = new Set(["executing", "waiting_human", "paused"]);

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

// -- UX-4 typed activity stream (NEXT_STEPS §9B.4) ----------------------------------
// Two real sources, one identity: the run's persisted events (GET /runs/{rid}: id, ts, type, task_id —
// the latest 200) and the SSE frames this tab received for the same execution (they add `to`/`actor`).
// Both are keyed by the server's workflow_events id, so a replayed, re-fetched or re-delivered event is one
// entry, always in id order (never ts order). Only the fields below are kept — notes, reasoning, secrets
// or any other payload field are dropped on arrival and can never render.
const frames = new Map();   // event id → whitelisted fields; shown only under a run the API just returned to this user
export function remember(f) {
  const id = Number(f?.id), d = f?.data;
  if (!Number.isInteger(id) || !d?.execution_id) return;
  frames.set(id, { id, type: f.event, ts: d.ts, execution_id: d.execution_id, task_id: d.task_id ?? null, to: d.to, actor: d.actor });
  if (frames.size > 5000) frames.delete(frames.keys().next().value);   // oldest received first
}
if (typeof addEventListener === "function") addEventListener(EVENT_BUS, (e) => remember(e.detail));

const SAFE = /^[\w.@:-]{1,64}$/;
const RESUMED = { paused: ["Paused", "no further stage starts until someone resumes it"], executing: ["Resumed", ""],
  cancelled: ["Cancelled", "stages not yet started will not run"] };
export const FILTERS = [["all", "All"], ["stage", "Stages"], ["run", "Run"], ["problem", "Errors & retries"]];

// one typed entry per backend event; `task_id` is kept only when it names a stage of this run (a valid link)
export function activity(run, tasks, live = []) {
  const byId = Object.fromEntries((tasks || []).map((t) => [t.task_id, t]));
  const all = new Map();
  for (const f of live) if (f.execution_id === run.execution_id) all.set(f.id, f);
  for (const e of run.events || []) {
    const id = Number(e.id);
    if (Number.isInteger(id)) all.set(id, { ...all.get(id), id, ts: e.ts, type: e.type, task_id: e.task_id ?? null });
  }
  const started = new Set();
  return [...all.values()].sort((a, b) => a.id - b.id).map((e) => {
    const t = byId[e.task_id];
    const stage = t ? t.key : SAFE.test(e.task_id || "") ? e.task_id : "unknown";
    const by = SAFE.test(e.actor || "") ? ` by ${e.actor}` : "";
    const it = { id: e.id, ts: e.ts, task_id: t ? t.task_id : null, cat: "run", icon: "•" };
    switch (e.type) {
      case "execution.created": return { ...it, text: "Run created" };
      case "execution.completed": return { ...it, icon: "✓", text: "Run completed" };
      case "execution.failed": return { ...it, cat: "problem", icon: "✕", critical: true, text: `Run stopped: failed${e.task_id ? ` at stage ${stage}` : ""}` };
      case "chat.replied": return { ...it, text: "Lead counsel posted this run's digest in the counsel chat" };
      case "execution.state_changed": {
        if (e.task_id) return { ...it, text: `Stage ${stage} redirected to a new instruction${by}` };
        const [w, why] = RESUMED[e.to] || [];
        return { ...it, icon: e.to === "paused" ? "⏸" : "•",
          text: w ? `${w}${by}${why ? ` — ${why}` : ""}` : "Run paused, resumed or cancelled (which one was not received)" };
      }
      case "task.running": {
        const again = started.has(e.task_id);
        started.add(e.task_id);
        return again
          ? { ...it, cat: "problem", icon: "↻", text: `Stage ${stage} started again — re-claimed after its worker stopped reporting` }
          : { ...it, cat: "stage", icon: "▸", text: `Stage ${stage} started${t?.agent_id ? ` (${t.agent_id})` : ""}` };
      }
      case "task.completed": started.delete(e.task_id); return { ...it, cat: "stage", icon: "✓", text: `Stage ${stage} completed` };
      case "task.failed": started.delete(e.task_id); return { ...it, cat: "problem", icon: "✕", critical: true, text: `Stage ${stage} failed` };
      default: return { ...it, cat: "other", text: SAFE.test(e.type || "") ? `Recorded event: ${e.type}` : "Unrecognised event" };
    }
  });
}

// errors, retries and failures stay visible under every filter
export const shown = (items, cat) => items.filter((i) => cat === "all" || i.cat === cat || i.critical);

// a reconnect (or a refused stream coming back) re-reads the persisted run: the snapshot is the truth
export const resyncNeeded = (prev, next) => next === "live" && (prev === "reconnecting" || prev === "unavailable");

function connLine(live, finished, resynced) {
  if (finished) return "This run has finished — below is its recorded history; no further activity is expected.";
  if (live === "live") return resynced
    ? `Reconnected ${hm(resynced)} — the server replayed every event recorded while this browser was disconnected, and the run was reloaded.`
    : "Live — new activity appears as the server records it.";
  if (live === "reconnecting") return "Reconnecting — the connection dropped in this browser only; the run carries on on the server, and missed events are replayed on reconnect.";
  if (live === "unavailable") return "Live updates unavailable — the server refused the event stream (session expired or access changed). Retrying; reload the page if this persists.";
  return "Connecting to live updates…";
}

export function ActivityStream({ run: r, tasks, approvals = [], live, resynced = null, link = false, H = "h2", received = [...frames.values()] }) {
  const [cat, setCat] = useState("all");
  const items = activity(r, tasks, received);
  const list = shown(items, cat);
  const latest = items.at(-1);
  const keyOf = Object.fromEntries((tasks || []).map((t) => [t.task_id, t.key]));
  return (
    <section className="stack" aria-label="Run activity">
      <div className="hdr runsec">
        <H>Activity</H>
        <span className="sub">{`${items.length} event${items.length === 1 ? "" : "s"}`}</span>
        {items.length ? <span className="act seg" role="group" aria-label="Filter activity">{FILTERS.map(([k, label]) => (
          <button type="button" key={k} className="btn" aria-pressed={cat === k} onClick={() => setCat(k)}>{label}</button>))}</span> : null}
      </div>
      <p className="small">{connLine(live, TERMINAL.has(r.state), resynced)}</p>
      {approvals.filter((a) => a.execution_id === r.execution_id).map((a) => (
        <p key={a.approval_id} className="banner nextact--wait"><b>⚑ Waiting on you:</b>{` approval (${a.kind}) after stage ${keyOf[a.task_id] || "—"}, requested ${a.requested_at ? at(a.requested_at) : "—"}. `}
          <a href={href("approvals")}>Approval Center</a></p>))}
      {latest ? <p className="small"><b>Latest:</b> {latest.text}{latest.ts ? ` · ${fmtAgo(latest.ts)}` : ""}</p> : null}
      {items.length ? (
        <ol className="timeline timeline--activity activity" tabIndex={0} aria-label="Run activity, oldest first">
          {list.map((i) => (
            <li key={i.id} data-cat={i.cat} data-state={i.icon === "✓" ? "done" : i.critical ? "failed" : undefined} data-latest={i === latest ? "" : undefined}>
              <time dateTime={i.ts}>{i.ts ? DT.format(new Date(i.ts)) : "—"}</time>
              <span aria-hidden="true">{i.icon} </span>
              {link && i.task_id ? <a href={href("run", { rid: r.execution_id, node: i.task_id })}>{i.text}</a> : i.text}
              {i === latest ? <span className="chip chip--running">Latest</span> : null}
            </li>))}
        </ol>) : <p className="muted">No events recorded for this run.</p>}
      {list.length < items.length ? <p className="small muted">{`${items.length - list.length} event${items.length - list.length === 1 ? "" : "s"} hidden by the filter; errors and retries always show.`}</p> : null}
      {(r.events || []).length >= 200 ? <p className="small muted">The server returns this run's latest 200 events; older ones appear only if this page received them live.</p> : null}
      <p className="small muted">This server does not emit tool calls, progress summaries, findings or evidence references as events, so none appear here. Each stage's recorded summary is in its details.</p>
    </section>
  );
}

// what the run needs from a person right now, strictly from execution.state + pending approvals
export function nextAction(r, ts, states, approvals) {
  const failedT = ts.find((t) => t.state === "failed");
  const stuck = ts.find((t) => states[t.task_id] === "interrupted");
  switch (r.state) {
    case "waiting_human": return { tone: "wait", title: "Your approval is needed",
      text: approvals.length ? "This run is parked until the checkpoint below is decided." :
        "This run is parked at a checkpoint; its approval is not in the pending list — it may have just been decided." };
    case "paused": return { tone: "wait", title: "Paused — waiting for someone to resume it",
      text: `${ts.some((t) => t.state === "running") ? "A pause takes effect at the next stage boundary, so the stage already running will finish. " : ""}No further stages start until the run is resumed.` };
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
  onClose, onRedirect = () => {}, asOf: asOfProp, actions = null, children = null }) {
  const { perms, mode, live } = useCtx();
  const [force, setForce] = useState(null);             // Expand/Collapse all; n re-applies a repeat press
  const [resynced, setResynced] = useState(null);
  const prevLive = useRef(live);
  useEffect(() => {
    if (resyncNeeded(prevLive.current, live)) { run.reload(); tasks.reload(); setResynced(new Date().toISOString()); }
    prevLive.current = live;
  }, [live]); // eslint-disable-line react-hooks/exhaustive-deps
  const r = run.data;
  // "now" for lease checks = when this snapshot loaded, so an old snapshot never ages into a failure
  const loadedAt = useMemo(() => Date.now() / 1000, [r, tasks.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const asOf = asOfProp ?? loadedAt;
  const ts = bySeq(tasks.data);
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
      <div className="hdr runhead">
        <H>Run <span className="mono">{r.execution_id}</span> <StatusChip kind="agent" state={r.state} /></H>
        {actions || onClose ? <span className="act">{actions}
          {onClose ? <button type="button" className="btn" onClick={onClose} aria-label="Close run inspection">Close</button> : null}</span> : null}
      </div>
      {(live === "reconnecting" || live === "unavailable") && !TERMINAL.has(r.state) ? (
        <p className="stale" role="status">◐ Live updates are disconnected — this is the run as last loaded. It carries on on the server; the page catches up when the connection returns.</p>) : null}
      <ErrorLine error={run.error} onRetry={run.reload} stale />
      {/* label-over-value facts strip; the task reads as the run's lead line */}
      <dl className="runfacts">
        <div className="runfacts__wide"><dt>Task</dt><dd>{r.input_task_text || "—"}</dd></div>
        <div><dt>Matter</dt><dd><a href={href(firm ? "workspace" : "case", { mid: r.matter_id })}>{matter.data?.title || r.matter_id}</a></dd></div>
        <div><dt>Started</dt><dd>{r.started_at ? at(r.started_at) : "—"}</dd></div>
        {r.ended_at ? <div><dt>Ended</dt><dd>{at(r.ended_at)}</dd></div> : null}
        <div><dt>{r.ended_at ? "Duration" : "Elapsed"}</dt><dd>{span ? (r.ended_at ? span : `${span} so far`) : "Not available"}</dd></div>
        <div><dt>Last update</dt><dd>{last ? at(last) : "No events recorded"}</dd></div>
        <div><dt>Tokens</dt><dd>{tokens.data
          ? `${fmtTokens(tokens.data.total?.all)} across this matter (all runs) · a per-run total is not recorded`
          : tokens.error ? "Unavailable" : "…"}</dd></div>
      </dl>
      <div className={`banner nextact nextact--${act.tone}`} role={act.tone === "bad" || act.tone === "wait" ? "alert" : "status"}>
        <p className="banner__title"><span aria-hidden="true">{{ wait: "⚑", bad: "✕", done: "✓" }[act.tone] || "○"} </span>{act.title}</p><p style={{ margin: 0 }}>{act.text}</p>
        {r.state === "waiting_human" ? <>
          {appr.map((a) => <ApprovalCard key={a.approval_id} a={a} onDone={approvals.reload} />)}
          <p className="small">Also in the <a href={href("approvals")}>Approval Center</a>.</p></> : null}
      </div>
      <div className="hdr runsec">
        <H2>Stages</H2>
        <span className="sub">{ts.length ? [`${done} of ${ts.length} complete`, ...Object.entries(counts)
          .filter(([s]) => s !== "completed").map(([s, n]) => `${n} ${word(s).toLowerCase()}`)].join(" · ") : ""}</span>
        {stages && ts.length ? <span className="act">
          <button type="button" className="btn" onClick={() => setForce((f) => ({ open: true, n: (f?.n || 0) + 1 }))}>Expand all</button>{" "}
          <button type="button" className="btn" onClick={() => setForce((f) => ({ open: false, n: (f?.n || 0) + 1 }))}>Collapse all</button>
        </span> : null}
      </div>
      {ts.length ? <>
        <div className="bar2" aria-hidden="true"><i style={{ width: `${Math.round((100 * done) / ts.length)}%` }} /></div>
        {/* firm page: the stage map below carries this explanation once */}
        {stages ? <p className="small">Stages run one at a time in plan order; each starts only after every earlier stage has completed.</p> : null}
      </> : null}
      <ErrorLine error={tasks.error} onRetry={tasks.reload} stale={!!tasks.data} />
      {stages ? <>
        {tasks.data === undefined ? (tasks.error ? null : <Loading rows={2} />) : ts.length === 0
          ? <p className="muted">No stage details were recorded for this run.</p>
          : <StageList tasks={ts} runState={r.state} states={states} times={times} force={force}
            canAct={allowed(perms, "matter.dispatch")} live={LIVE.has(r.state)} onRedirect={onRedirect} />}
        {agents.length ? <>
          <H2 className="runsec">Agents</H2>
          <table className="table" aria-label="Agents in this run">
            <thead><tr><th scope="col">Agent</th><th scope="col">Stages</th><th scope="col">Tokens on this matter</th></tr></thead>
            <tbody>{agents.map((g) => {
              const a = byAgent[g.id];   // matter-wide per agent: shown once per agent, never per stage
              return (<tr key={g.id || "-"}><td>{g.id || "agent"}</td><td>{g.keys.join(", ")}</td>
                <td className="tokens">{a ? `${fmtTokens(a.all)} · in ${fmtTokens(a.in)} · out ${fmtTokens(a.out)} · think ${fmtTokens(a.thinking)}` : "None recorded"}</td></tr>);
            })}</tbody>
          </table></> : null}
      </> : null}
      {children}
      <H2 className="runsec">Deliverables</H2>
      <ErrorLine error={artifacts.error} onRetry={artifacts.reload} stale={!!artifacts.data} />
      {artifacts.data === undefined ? (artifacts.error ? null : <Loading rows={1} />) : outs.length ? (
        <ul className="links">{outs.map((a) => (
          <li key={a.artifact_id}><a href={href("workspace", { mid: r.matter_id, tab: "drafts" })}>{a.title || a.artifact_id}</a>{" "}
            <span className="muted">· {a.kind || "artifact"} · {String(a.review_state || "unreviewed").replace(/_/g, " ")}{a.created_at ? ` · ${at(a.created_at)}` : ""}</span></li>))}
        </ul>) : <p className="muted">{TERMINAL.has(r.state) ? "This run recorded no deliverables." : "No deliverables yet."}</p>}
      <ActivityStream run={r} tasks={ts} approvals={approvals.data || []} live={live} resynced={resynced} link={firm} H={H2} />
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


// runs last hours or days: "2h 05m" past the hour, else "4m 07s"
export const fmtDur = (ms) => {
  const s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(s % 60).padStart(2, "0")}s`;
};

// -- UX-3 dependency graph (NEXT_STEPS §9B.3) ---------------------------------------
// An arrow is a real dependency from one of two sources, never from event order:
//  1. tasks[].depends_on (task_id[]) when the API supplies it — it does not yet (backend gap);
//  2. else plan order: orchestrator.claim() starts a stage only once every lower-seq stage has
//     completed, so each stage waits on the stage(s) holding the next-lower seq.
// Positions are a pure function of that topology, so status updates never move a node.
// laid out top-down (a stepper): one row per dependency depth, peers side by side in a row
export const NODE = { w: 248, h: 58, gx: 16, gy: 26 };

export function runGraph(tasks) {
  const ts = bySeq(tasks);
  const ids = new Set(ts.map((t) => t.task_id));
  if (ts.some((t) => !t.task_id) || ids.size !== ts.length) return { error: "two stages share an ID, or a stage has none" };
  const explicit = ts.some((t) => "depends_on" in t);
  let deps;
  if (explicit) {
    const bad = ts.find((t) => !Array.isArray(t.depends_on) || t.depends_on.some((d) => d === t.task_id || !ids.has(d)));
    if (bad) return { error: `stage ${bad.key || bad.task_id} has missing or invalid dependency data` };
    deps = Object.fromEntries(ts.map((t) => [t.task_id, [...new Set(t.depends_on)]]));
  } else if (ts.every((t) => Number.isFinite(t.seq))) {
    deps = Object.fromEntries(ts.map((t) => {
      const prev = ts.filter((p) => p.seq < t.seq).at(-1)?.seq;   // ts is seq-sorted
      return [t.task_id, ts.filter((p) => p.seq === prev).map((p) => p.task_id)];
    }));
  } else return { error: "no dependency metadata was recorded" };
  const depth = {}, open = new Set();
  const visit = (id) => {   // longest path from a root = the column; a cycle has none
    if (id in depth) return depth[id];
    if (open.has(id)) throw new Error("cycle");
    open.add(id);
    return (depth[id] = 1 + Math.max(-1, ...deps[id].map(visit)));
  };
  try { ts.forEach((t) => visit(t.task_id)); } catch { return { error: "its recorded dependencies form a cycle" }; }
  const cols = [];
  for (const t of ts) (cols[depth[t.task_id]] ||= []).push(t);
  const pos = {};
  cols.forEach((c, y) => c.forEach((t, x) => { pos[t.task_id] = { x: x * (NODE.w + NODE.gx), y: y * (NODE.h + NODE.gy) }; }));
  const rows = Math.max(0, ...cols.map((c) => c.length));   // widest depth = peers side by side
  return {
    deps, pos, cols, source: explicit ? "explicit" : "plan",
    shape: rows <= 1 ? "sequential" : cols.length === 1 ? "parallel" : "hybrid",
    width: Math.max(0, rows * (NODE.w + NODE.gx) - NODE.gx), height: Math.max(0, cols.length * (NODE.h + NODE.gy) - NODE.gy),
    edges: ts.flatMap((t) => deps[t.task_id].map((d) => [d, t.task_id])),
  };
}

const SHAPE = { sequential: "Sequential — one stage after another.", parallel: "Parallel — no stage waits on another.",
  hybrid: "Hybrid — stages side by side in one row wait on none of each other and can run at the same time." };
const NODECLS = { done: "ok", running: "run", waiting: "wait", failed: "bad", blocked: "bad" };
const stateOf = (s) => AGENT_STATES[s] || ["idle", "?", `Unknown status (${s || "none"})`];

export function SwarmView({ run: r, tasks, tokens, artifacts = [], interjections = [], canAct, st, cmd, sel, onSelect = () => {}, onInterject = () => {},
  received = [...frames.values()] }) {
  const [hide, setHide] = useState(false);
  const [text, setText] = useState("");
  const [view, setView] = useState("graph");
  const [zoom, setZoom] = useState(1);
  const [closed, setClosed] = useState(false);
  const box = useRef(null);
  const ts = bySeq(tasks);
  const rid = r.execution_id;
  const byId = Object.fromEntries(ts.map((t) => [t.task_id, t]));
  const byAgent = Object.fromEntries((tokens?.agents || []).map((a) => [a.agent, a]));
  const parked = parkedTask(ts, r.state);
  const asOf = useMemo(() => Date.now() / 1000, [r, tasks]);   // lease checks as of this snapshot (see stageState)
  const states = Object.fromEntries(ts.map((t) => [t.task_id, stageState(t, r.state, parked, asOf)]));
  const times = stageTimes(r.events);
  const g = runGraph(ts);
  const mode = g.error ? "list" : view;
  const live = LIVE.has(r.state);
  const seen = {};
  for (const t of ts) seen[t.agent_id] = (seen[t.agent_id] || 0) + 1;
  // an agent that works several stages is named by stage, so nodes stay distinguishable
  const label = (t) => `${title(t.agent_id || "agent")}${seen[t.agent_id] > 1 ? ` · ${t.key}` : ""}${t.task_id === parked ? " ⚑" : ""}`;
  const pinned = byId[sel];
  const cur = closed && !pinned ? null : pinned || byId[parked]
    || ts.find((t) => t.state === "running") || ts.find((t) => t.state !== "completed") || ts.at(-1);
  const deps = (id) => g.deps?.[id] || [];
  const needs = (id) => (g.edges || []).filter(([a]) => a === id).map(([, b]) => b);
  // why a queued stage has not started: the dependencies it still waits on (live runs only)
  const waitOn = (id) => (live && states[id] === "pending" ? deps(id).filter((d) => byId[d].state !== "completed") : []);
  const keys = (list) => list.map((d) => byId[d].key).join(", ");
  const pick = (id) => { setClosed(false); onSelect(id); };
  const close = () => { setClosed(true); onSelect(null); };
  // whole map in the viewport: width of the column and the window height, never above 100 %
  const fit = () => {
    const w = box.current?.clientWidth;
    if (w && g.width) setZoom(Math.max(0.25, Math.min(1, (w - 16) / g.width, (innerHeight - 200) / g.height)));
  };
  const nodeBtn = (t, style, list) => {
    const s = states[t.task_id], [cls, icon, word] = stateOf(s), w = waitOn(t.task_id);
    const tm = times[t.task_id] || {}, span = fmtSpan(tm.start, tm.end), d = deps(t.task_id);
    const after = g.deps ? (d.length ? `After ${keys(d)}` : "Starts first") : null;
    const meta = [w.length ? `waits on ${keys(w)}` : span, list ? after : null].filter(Boolean).join(" · ");
    return (
      <button type="button" key={t.task_id} className={`card node ${NODECLS[cls] || ""}`} style={style} title={label(t)}
        aria-pressed={t === cur} onClick={() => pick(t.task_id)}
        aria-label={`${label(t)}: ${word}${w.length ? `, waiting on ${keys(w)}` : ""}${after ? `. ${after}` : ""}`}>
        <b>{label(t)}</b>
        <span className="line"><span className="s"><span aria-hidden="true">{icon} </span>{word}</span>{meta ? <span className="m">{meta}</span> : null}</span>
      </button>);
  };
  const order = g.cols ? g.cols.flat() : ts;
  const a = cur ? byAgent[cur.agent_id] : null;
  const cs = cur ? states[cur.task_id] : null;
  const ctm = cur ? times[cur.task_id] || {} : {};
  return (
    <section className="stagemapsec" aria-label="Stage map">
      <CommandError error={st.error} />
      {st.pending ? <p className="muted" role="status">Pending… waiting for the worker to confirm.</p> : null}
      {ts.length && !g.error ? <div className="graphbar" role="toolbar" aria-label="Stage map view">
        <span className="seg">
          <button type="button" className="btn" aria-pressed={mode === "graph"} onClick={() => setView("graph")}>Graph</button>
          <button type="button" className="btn" aria-pressed={mode === "list"} onClick={() => setView("list")}>List</button>
        </span>
        {mode === "graph" ? <span className="seg">
          <button type="button" className="btn" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))}>−</button>
          <output className="zoomval" aria-live="polite" aria-label="Zoom">{`${Math.round(zoom * 100)}%`}</output>
          <button type="button" className="btn" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(2, z + 0.25))}>+</button>
          <button type="button" className="btn" onClick={fit}>Fit</button>
          <button type="button" className="btn" onClick={() => setZoom(1)}>Reset zoom</button></span>
          : <button type="button" className="btn" aria-pressed={hide} onClick={() => setHide(!hide)}>Hide finished</button>}
      </div> : null}
      {g.error ? <p className="banner" role="status">{`Dependency graph unavailable for this run: ${g.error}. The stages are listed in plan order; no connections are drawn.`}</p>
        : ts.length ? <p className="small">{`${SHAPE[g.shape]} ${g.source === "plan"
          ? "Dependencies come from plan order: the orchestrator starts a stage only after every earlier stage has completed."
          : "Dependencies as recorded for this run."} An arrow means “must finish first” — solid once finished, dashed until then.`}</p>
        : <p className="muted">No stage details were recorded for this run.</p>}
      <div className={`swarmwrap${cur ? "" : " solo"}`}>
        {!ts.length ? null : mode === "graph" ? (
          <div className="graph" ref={box} tabIndex={0} role="group" onKeyDown={(e) => { if (e.key === "Escape") close(); }}
            aria-label={`Dependency graph, ${ts.length} stages. Scroll to pan; the List view shows the same stages as a list.`}>
            <div style={{ width: g.width * zoom, height: g.height * zoom }}>
              <div className="graph__canvas" style={{ width: g.width, height: g.height, transform: `scale(${zoom})` }}>
                <svg width={g.width} height={g.height} aria-hidden="true" focusable="false">
                  <defs><marker id={`arr-${rid}`} viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" /></marker></defs>
                  {g.edges.map(([s, e]) => {
                    const p = g.pos[s], q = g.pos[e], x1 = p.x + NODE.w / 2, y1 = p.y + NODE.h, x2 = q.x + NODE.w / 2, y2 = q.y - 2, m = (y1 + y2) / 2;
                    return <path key={`${s}>${e}`} data-edge={`${s}>${e}`} className={byId[s].state === "completed" ? "met" : undefined}
                      d={`M${x1} ${y1}C${x1} ${m} ${x2} ${m} ${x2} ${y2}`} markerEnd={`url(#arr-${rid})`} />;
                  })}
                </svg>
                {order.map((t) => nodeBtn(t, { left: g.pos[t.task_id].x, top: g.pos[t.task_id].y }))}
              </div>
            </div>
          </div>
        ) : (
          <ol className="stagemap" aria-label={g.deps ? "Stages in dependency order" : "Stages in plan order"}
            onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
            {order.filter((t) => !hide || t.state !== "completed" || t.task_id === parked)
              .map((t) => <li key={t.task_id}>{nodeBtn(t, undefined, true)}</li>)}
          </ol>)}
        {cur ? (
          <aside className="card drawer" aria-label="Stage inspection">
            <div className="hdr"><h3>{`${label(cur)} · stage ${ts.indexOf(cur) + 1} of ${ts.length}`}</h3>
              <span className="act"><button type="button" className="btn" onClick={close} aria-label="Close stage inspection">Close</button></span></div>
            {pinned ? null : <p className="small muted">Showing the current stage — select any stage to inspect it.</p>}
            <dl className="kv">
              <dt>Agent</dt><dd>{cur.agent_id || "Not recorded"}</dd>
              <dt>Goal</dt><dd>{cur.instruction || "—"}</dd>
              <dt>State</dt><dd><span className={`chip chip--${stateOf(cs)[0]}`} data-icon={stateOf(cs)[1]}>{stateOf(cs)[2]}</span></dd>
              <dt>Depends on</dt><dd>{!g.deps ? "Not available for this run" : deps(cur.task_id).length
                ? deps(cur.task_id).map((d) => <button type="button" key={d} className="btn" onClick={() => pick(d)}>{`${byId[d].key} · ${stateOf(states[d])[2]}`}</button>)
                : "Nothing — starts first"}</dd>
              {g.deps ? <><dt>Needed by</dt><dd>{needs(cur.task_id).length
                ? needs(cur.task_id).map((d) => <button type="button" key={d} className="btn" onClick={() => pick(d)}>{byId[d].key}</button>)
                : "No later stage"}</dd></> : null}
              {waitOn(cur.task_id).length ? <><dt>Waiting on</dt><dd>{`${keys(waitOn(cur.task_id))} to finish`}</dd></> : null}
              {ctm.start ? <><dt>Started</dt><dd>{at(ctm.start)}</dd></> : null}
              {ctm.end ? <><dt>Finished</dt><dd>{at(ctm.end)}</dd></> : null}
              {fmtSpan(ctm.start, ctm.end) ? <><dt>Duration</dt><dd>{fmtSpan(ctm.start, ctm.end)}</dd></> : null}
              {cur.attempts > 1 || cs === "failed" || cs === "interrupted" ? <><dt>Attempts</dt><dd>{`${cur.attempts ?? "?"} of ${cur.max_attempts ?? "?"}${cs === "interrupted"
                ? " — its worker missed its heartbeat; the stage is re-claimed automatically" : ""}`}</dd></> : null}
              {cur.approval_kind ? <><dt>Checkpoint</dt><dd>{`Approval (${cur.approval_kind}) after this stage`}</dd></> : null}
              <dt>Tokens</dt><dd>{a ? `${fmtTokens(a.all)} · in ${fmtTokens(a.in)} · out ${fmtTokens(a.out)} · think ${fmtTokens(a.thinking)} — this agent across the matter; a per-stage count is not recorded` : "None recorded for this agent"}</dd>
              <dt>Deliverables</dt><dd>{artifacts.length
                ? <><a href={href("workspace", { mid: r.matter_id, tab: "drafts" })}>{`${artifacts.length} from this run`}</a> — which stage wrote each is not recorded</>
                : TERMINAL.has(r.state) ? "This run recorded none" : "None yet from this run"}</dd>
            </dl>
            {cs === "failed" && !cur.result_summary ? <p className="small"><b>Error: </b>no error text was recorded for this stage.</p> : null}
            {/* this stage's own events, same typed mapping and dedup as the run's Activity section */}
            {(() => {
              const mine = activity(r, ts, received).filter((i) => i.task_id === cur.task_id);
              return mine.length ? <ol className="timeline timeline--activity" aria-label={`Activity for stage ${cur.key}`}>{mine.map((i) => (
                <li key={i.id} data-state={i.icon === "✓" ? "done" : i.critical ? "failed" : undefined}>
                  <time dateTime={i.ts}>{i.ts ? DT.format(new Date(i.ts)) : "—"}</time><span aria-hidden="true">{i.icon} </span>{i.text}</li>))}
              </ol> : <p className="small muted">No events recorded for this stage yet.</p>;
            })()}
            <p className="small muted">Tool activity, findings and evidence references are not recorded per stage, so none are shown here.</p>
            {canAct && live && cur.state === "pending" ? (
              <button type="button" className="btn" onClick={() => {
                const instruction = prompt(`New instruction for stage "${cur.key}"`);
                if (instruction) cmd(() => post(`/executions/${rid}/redirect`, { task_id: cur.task_id, instruction }));
              }}>Redirect</button>) : null}
            {cur.result_summary ? <>{cs === "failed" ? <p className="small"><b>Error</b></p> : null}<pre className="log">{cur.result_summary}</pre></> : null}
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
            {/* interjections are write-only in the API: only what this page sent is known */}
            {interjections.length ? <ul className="links small" aria-label="Interjections sent from this page">{interjections.map((i) => (
              <li key={i.interjection_id}>{`“${i.text}” — delivered at the next stage boundary · ${hm(i.at)}`}</li>))}</ul> : null}
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

// who answered, from the answer's persisted provenance (service/counsel.py `actor`)
export function speaker(m) {
  if (m.role !== "lead") return "You";
  const a = m.actor || "";
  if (a === "counsel:records") return "Lead counsel · from matter records";
  if (a === "counsel:proposal") return "Lead counsel · proposed change";
  if (a.startsWith("counsel:model:")) return `Lead counsel · model answer (${a.slice(14)})`;
  if (a === "counsel:unavailable") return "Lead counsel";
  return "Lead counsel · run digest";
}

// floating chat: a launcher pinned bottom-right opens a non-modal panel above it. The panel stays
// mounted while closed (hidden), so a half-typed message survives minimising. Messages are
// questions (answered from the matter's records or a model citing them) or instructions, which
// come back as a proposal card: nothing changes a run until the user confirms it.
export function ChatDock({ run: r = null, tasks, messages, canSend, st, onSend, proposal = null, onAct = () => {},
  onDismiss = () => {}, scope = "matter", defaultOpen = false }) {
  const [text, setText] = useState("");
  const [shown, setShown] = useState(defaultOpen);
  const launcher = useRef(null), input = useRef(null), end = useRef(null);
  const ts = bySeq(tasks);
  const msgs = messages || [];
  const open = unanswered(msgs);
  const byId = Object.fromEntries(ts.map((t) => [t.task_id, t]));
  const reached = [...(r?.events || [])].reverse().find((e) => e.type === "task.running" && byId[e.task_id]);
  const send = async () => { if (text.trim() && await onSend(text.trim())) setText(""); };
  const cid = `chat-${scope}`, pid = `chatpanel-${scope}`;
  const close = () => { setShown(false); launcher.current?.focus(); };
  useEffect(() => {   // on open: newest message in view, focus in the composer
    if (!shown) return;
    end.current?.scrollIntoView?.({ block: "end" });
    input.current?.focus();
  }, [shown, msgs.length]);
  return (
    <div className="chatfab">
      <section id={pid} className="card chat chatpanel" role="dialog" aria-modal="false" aria-labelledby={`${pid}-h`} hidden={!shown}
        onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
        <div className="ch">
          <div><h2 id={`${pid}-h`}>Counsel chat</h2>
            <span>{`Ask about this matter in any state · ${msgs.length} message${msgs.length === 1 ? "" : "s"}`}</span></div>
          <button type="button" className="btn chatpanel__min" onClick={close} aria-label="Minimise counsel chat">–</button>
        </div>
        <div className="msgs" aria-live="polite">
          {msgs.length ? null : <p className="small">Ask where things stand, what failed, what is waiting on you, what a stage
            found, or a question about the matter. You can also say “pause”, “resume”, “cancel”, “redirect &lt;stage&gt; to: …”
            or “start a run to …” — you confirm every change first.</p>}
          {msgs.map((m) => {
            const [body, src] = String(m.text || "").split("\n\nSources: ");
            return (
              <div key={m.message_id} className={m.role === "lead" ? "msg lead" : "msg"}>
                <div className="who"><b>{speaker(m)}</b> · {hm(m.ts)}</div>
                <div className="body">{body}</div>
                {src ? <div className="src small">Sources: {src}</div> : null}
                {open.has(m.message_id) ? <div className="pending" role="status"><span className="dot"></span> run started — its digest lands here when it completes</div> : null}
              </div>);
          })}
          {reached ? <div className="sys">{`↳ ${byId[reached.task_id].key} stage reached ${hm(reached.ts)}`}</div> : null}
          {st.busy ? <div className="pending" role="status"><span className="dot"></span> Lead counsel is answering…</div> : null}
          {proposal ? (
            <div className="card confirmcard" role="group" aria-label={`Confirm: ${proposal.title}`}>
              <p className="confirmcard__title">{proposal.title}</p>
              <p className="small">{proposal.detail}</p>
              <div className="row">
                <button type="button" className="btn" onClick={onDismiss}>Not now</button>
                <button type="button" className="btn btn--primary" disabled={st.busy} onClick={() => onAct(proposal)}>{proposal.confirm}</button>
              </div>
            </div>) : null}
          <div ref={end} />
        </div>
        {canSend ? (
          <form className="comp" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <label htmlFor={cid} className="small">Ask about this matter, or tell lead counsel what to change</label>
            <textarea id={cid} ref={input} value={text} onChange={(e) => setText(e.target.value)}
              placeholder="Where are we? · What did research find? · Pause after this stage"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
            <div className="row"><span className="hint">Enter sends · Shift+Enter for a new line</span>
              <button type="submit" className="btn btn--primary" disabled={st.busy}>Send</button></div>
            <CommandError error={st.error} />
            {st.pending ? <p className="muted" role="status">Sent — waiting for the worker to confirm.</p> : null}
          </form>) : <CommandError error={st.error} />}
      </section>
      <button type="button" ref={launcher} className="chatfab__btn" aria-expanded={shown} aria-controls={pid}
        onClick={() => (shown ? close() : setShown(true))}>
        <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" width="18" height="18"><path d="M4 5h16v10H9l-5 4z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>
        <span>Counsel chat</span>
        {open.size ? <span className="chatfab__badge">{`${open.size} awaiting reply`}</span> : null}
      </button>
    </div>
  );
}

// the matter's Supervision thread + ask/confirm wiring, shared by the run page and the matter
// workspace (so a lawyer can ask before any run exists). `run` is the run on screen, if any.
export function MatterChat({ mid, run = null, tasks = [] }) {
  const { perms } = useCtx();
  const convs = useApi(mid ? `/matters/${mid}/conversations` : null, { matter: mid });
  const conv = (convs.data || []).find((c) => c.title === "Supervision") || convs.data?.[0];
  const msgs = useApi(conv ? `/conversations/${conv.conversation_id}/messages` : null, { matter: mid });
  const [st, cmd, reset] = useCommand();
  const [proposal, setProposal] = useState(null);
  useEffect(() => { reset(); }, [msgs.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const thread = async () => {      // created on first message, never on view
    if (conv) return conv.conversation_id;
    const cid = (await post(`/matters/${mid}/conversations`, { title: "Supervision" })).data.conversation_id;
    convs.reload();
    return cid;
  };
  const onSend = (text) => cmd(async () => {
    const res = await post(`/conversations/${await thread()}/ask`, { text, execution_id: run?.execution_id || null });
    setProposal(res.data?.action || null);
    msgs.reload();
    return res;
  });
  // the confirmed proposal goes through the same command endpoints as the page's own buttons
  const onAct = (a) => cmd(async () => {
    const e = a.execution_id;
    const res = a.command === "pause" ? await post(`/executions/${e}/pause`)
      : a.command === "resume" ? await post(`/executions/${e}/resume`)
        : a.command === "cancel" ? await post(`/runs/${e}/cancel`)
          : a.command === "redirect" ? await post(`/executions/${e}/redirect`, { task_id: a.task_id, instruction: a.instruction })
            : await post(`/conversations/${await thread()}/messages`, { text: a.task_text });
    setProposal(null);
    msgs.reload();
    return res;
  });
  return <ChatDock run={run} tasks={tasks} messages={msgs.data?.items} canSend={allowed(perms, "matter.read")}
    st={st} onSend={onSend} proposal={proposal} onAct={onAct} onDismiss={() => setProposal(null)} scope={mid} />;
}

export default function RunPage({ rid, node }) {
  const { perms, mode } = useCtx();
  const firm = mode === "firm";
  const d = useRunData(rid, undefined, firm);   // self-rep: RunDrawer below does its own reads
  const { run, tasks, tokens: tk, artifacts: arts } = d;
  const [st, cmd, reset] = useCommand();
  // interjections are write-only in the API: only what this page sent is known here
  const [sent, setSent] = useState([]);
  // a 202 stays "pending…" until the confirming SSE event refetches the run (05 §10)
  useEffect(() => { reset(); }, [run.data, tasks.data]); // eslint-disable-line react-hooks/exhaustive-deps
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
    {/* firm: the stage map sits under the overview's stage progress, so the overview skips its own list */}
    <RunOverview {...d} level={1} stages={false} actions={<RunControls run={run.data} canAct={canAct} cmd={cmd} />}>
      {/* the selected stage lives in the hash (#/runs/{rid}/{task_id}): deep-linkable, back/forward-safe */}
      <SwarmView run={run.data} tasks={tasks.data} tokens={tk.data} canAct={canAct} interjections={sent}
        artifacts={(arts.data?.items || []).filter((a) => a.execution_id === rid)}
        st={st} cmd={cmd} sel={node} onSelect={(id) => { location.hash = href("run", { rid, node: id || undefined }); }}
        onInterject={(d) => setSent((s) => [...s, { ...d, at: new Date().toISOString() }])} />
    </RunOverview>
    <MatterChat mid={run.data.matter_id} run={run.data} tasks={tasks.data} />
  </>);
}
