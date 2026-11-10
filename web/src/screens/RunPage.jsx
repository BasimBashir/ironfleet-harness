// Run inspection (05 §5): drawer beside the Work plan, or the full page at #/runs/{rid}.
// Identity, state, stage timeline with each stage's output, per-agent tokens (C's meters),
// and the permission-gated actions (interject, pause/resume, cancel, redirect a pending stage).
import { useEffect, useState } from "react";
import { post } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { useApi } from "../useApi.js";
import { ErrorLine, Loading, StatusChip, allowed, fmtAgo, fmtTokens } from "../ui.jsx";
import { ApprovalCard } from "./Approvals.jsx";
import { CommandError, useCommand } from "./Workspace.jsx";

export function RunDrawer({ rid, mid, onClose }) {
  const { perms } = useCtx();
  const run = useApi(`/runs/${rid}`, { matter: mid });
  const tasks = useApi(`/executions/${rid}/tasks`, { matter: mid });
  const matter = mid || run.data?.matter_id;
  const tk = useApi(matter ? `/matters/${matter}/tokens` : null, { matter });
  const [text, setText] = useState("");
  const [st, cmd] = useCommand();
  const canAct = allowed(perms, "matter.dispatch");     // 05 §12: hidden, not disabled
  if (run.error) return <ErrorLine error={run.error} onRetry={run.reload} />;
  if (!run.data) return <Loading />;
  const r = run.data;
  const byAgent = Object.fromEntries((tk.data?.agents || []).map((a) => [a.agent, a]));
  const live = r.state === "executing" || r.state === "waiting_human" || r.state === "paused";
  return (
    <aside className="card" style={{ padding: "14px 16px" }} aria-label={`Run ${rid}`}>
      <div className="hdr" style={{ marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: "var(--fs-md)" }}>Run <span className="mono">{rid}</span></h2>
        {onClose ? <span className="act"><button type="button" className="btn" onClick={onClose} aria-label="Close run inspection">Close</button></span> : null}
      </div>
      <dl className="prov__meta" style={{ display: "grid", gridTemplateColumns: "90px 1fr", gap: "4px 10px" }}>
        <dt>State</dt><dd><StatusChip kind="agent" state={r.state} /></dd>
        <dt>Objective</dt><dd>{r.input_task_text}</dd>
        <dt>Started</dt><dd>{fmtAgo(r.started_at)}</dd>
        <dt>Tokens</dt><dd className="tokens">matter total {fmtTokens(tk.data?.total?.all)} · in {fmtTokens(tk.data?.total?.in)} · out {fmtTokens(tk.data?.total?.out)} · thinking {fmtTokens(tk.data?.total?.thinking)}</dd>
      </dl>
      <h3 style={{ fontSize: "var(--fs-sm)" }}>Stages</h3>
      {tasks.loading ? <Loading rows={2} /> : (
        <ol className="timeline timeline--activity">
          {(tasks.data || []).map((t) => {
            const a = byAgent[t.agent_id];
            const parked = r.state === "waiting_human" && t.approval_kind && t.state === "completed";
            return (
              <li key={t.task_id} data-state={t.state === "completed" ? "done" : undefined}>
                <b>{t.key}</b> <span className="muted">· {t.agent_id || "agent"}</span>{" "}
                <StatusChip kind="agent" state={parked ? "waiting_human" : t.state} />
                {a ? <div className="tokens">{fmtTokens(a.all)} · in {fmtTokens(a.in)} · out {fmtTokens(a.out)} · think {fmtTokens(a.thinking)}</div> : null}
                {t.result_summary ? <p style={{ margin: "4px 0", whiteSpace: "pre-wrap" }}>{t.result_summary}</p> : null}
                {t.attempts > 1 ? <p className="muted">attempt {t.attempts} of {t.max_attempts}</p> : null}
                {canAct && t.state === "pending" && live ? (
                  <button type="button" className="btn" onClick={() => {
                    const instruction = prompt(`New instruction for stage "${t.key}"`);
                    if (instruction) cmd(() => post(`/executions/${rid}/redirect`, { task_id: t.task_id, instruction }));
                  }}>Redirect</button>) : null}
              </li>);
          })}
        </ol>)}
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

const fmtDur = (ms) => `${Math.floor(ms / 60000)}m ${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}s`;

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
      <div className="hdr"><h1 id="swarm-h">The team at work</h1>
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

export function ChatDock({ run: r, tasks, messages, approvals, artifacts, interjections, canSend, st, onSend }) {
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
          {appr.length ? <div className="appr"><ApprovalCard a={appr[0]} /></div> : null}
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
  const run = useApi(firm ? `/runs/${rid}` : null);
  const mid = run.data?.matter_id;
  const tasks = useApi(firm && mid ? `/executions/${rid}/tasks` : null, { matter: mid });
  const tk = useApi(firm && mid ? `/matters/${mid}/tokens` : null, { matter: mid });
  const convs = useApi(firm && mid ? `/matters/${mid}/conversations` : null, { matter: mid });
  const conv = (convs.data || []).find((c) => c.title === "Supervision") || convs.data?.[0];
  const msgs = useApi(conv ? `/conversations/${conv.conversation_id}/messages` : null, { matter: mid });
  // shortcut: first 200 artifacts only (oldest-first paging); page on if a matter ever exceeds it
  const arts = useApi(firm && mid ? `/matters/${mid}/artifacts?limit=200` : null, { matter: mid });
  const appr = useApi(firm && mid ? `/matters/${mid}/approvals` : null, { matter: mid });
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
  if (run.error) return <ErrorLine error={run.error} onRetry={run.reload} />;
  if (tasks.error) return <ErrorLine error={tasks.error} onRetry={tasks.reload} />;
  if (!run.data || !tasks.data) return <Loading />;
  const canAct = allowed(perms, "matter.dispatch");
  return (<>
    <SwarmView run={run.data} tasks={tasks.data} tokens={tk.data} canAct={canAct}
      st={st} cmd={cmd} sel={sel} onSelect={setSel}
      onInterject={(d) => setSent((s) => [...s, { ...d, at: new Date().toISOString() }])} />
    <ChatDock run={run.data} tasks={tasks.data} messages={msgs.data?.items} approvals={appr.data}
      artifacts={arts.data?.items} interjections={sent} canSend={canAct} st={chat} onSend={onSend} />
  </>);
}
