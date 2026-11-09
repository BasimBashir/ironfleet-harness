// Run inspection (05 §5): drawer beside the Work plan, or the full page at #/runs/{rid}.
// Identity, state, stage timeline with each stage's output, per-agent tokens (C's meters),
// and the permission-gated actions (interject, pause/resume, cancel, redirect a pending stage).
import { useState } from "react";
import { post } from "../api.js";
import { useCtx } from "../App.jsx";
import { useApi } from "../useApi.js";
import { ErrorLine, Loading, StatusChip, allowed, fmtAgo, fmtTokens } from "../ui.jsx";
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
              : <button type="button" className="btn" onClick={() => cmd(() => post(`/executions/${rid}/pause`))}>Pause</button>}{" "}
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

export default function RunPage({ rid }) {
  return (
    <section aria-labelledby="run-h">
      <div className="hdr"><h1 id="run-h">Run inspection</h1></div>
      <RunDrawer rid={rid} />
    </section>
  );
}
