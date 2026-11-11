// S3 Matter Workspace (05 §3): persistent matter header + 9 tabs (Swarm/Chat are M10,
// Research folds into Evidence — plan §0). S8 document viewer + S9 activity/audit live here.
import { useEffect, useRef, useState } from "react";
import { ApiError, blob, post, upload } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { subscribe } from "../sse.js";
import { useApi } from "../useApi.js";
import { Btn, Empty, ErrorLine, Loading, StatusChip, allowed, fmtAgo, fmtDate, fmtDue, fmtTokens } from "../ui.jsx";
import { RunDrawer } from "./RunPage.jsx";
import { Members } from "./Users.jsx";

const TABS = [["overview", "Overview"], ["documents", "Documents"], ["evidence", "Evidence"],
  ["workplan", "Work plan"], ["agents", "Agents"], ["drafts", "Drafts"], ["decisions", "Decisions"],
  ["activity", "Activity"], ["audit", "Audit"]];

export function CommandError({ error }) {
  return error ? <p className="field-error" role="alert">{error.message}
    {error.code ? <span className="id"> ({error.code})</span> : null}</p> : null;
}

// a 202 shows "pending…" until the confirming SSE event refetches the view (05 §10)
export function useCommand() {
  const [st, set] = useState({ busy: false, pending: false, error: null });
  const run = async (fn) => {
    set({ busy: true, pending: false, error: null });
    try {
      const r = await fn();
      set({ busy: false, pending: !!r?.pending, error: null });
      return r || true;
    } catch (e) {
      set({ busy: false, pending: false, error: e instanceof ApiError ? e : new ApiError(0, "client_error", String(e)) });
      return null;
    }
  };
  // clear pending/error when the caller's data has moved on (e.g. the next intake question)
  const reset = () => set({ busy: false, pending: false, error: null });
  return [st, run, reset];
}

function MatterHeader({ m, mid }) {
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  const ln = useApi(`/matters/${mid}/lawyer-now`, { matter: mid });
  const next = (dl.data?.items || []).filter((d) => d.status !== "met")
    .sort((a, b) => (a.due || "").localeCompare(b.due || ""))[0];
  return (
    <>
      {ln.data && ln.data.state !== "clear" ? (
        <div className="banner banner--flag" role="status">
          <p className="banner__title">⛔ Lawyer-now flag</p> — {ln.data.triggers.join(", ")}. You decide; nothing is gated in firm mode.
        </div>) : null}
      <div className="hdr">
        <h1 id="ws-h">{m.title || mid}</h1>
        <span className="sub"><span className="id">{mid}</span>
          {m.client_ref ? ` · ${m.client_ref}` : ""}{m.jurisdiction ? ` · ${m.jurisdiction}` : ""}
          {m.confidentiality ? ` · ${m.confidentiality}` : ""}
          {lc.data?.stage ? ` · ${lc.data.stage.toLowerCase().replace(/_/g, " ")}` : ""}
          {next ? ` · next date ${fmtDue(next.due)}` : ""}</span>
        <span className="act">{m.archived ? <StatusChip state="archived" /> : <StatusChip state={m.state} />}</span>
      </div>
    </>
  );
}

function Overview({ mid, m }) {
  const { perms } = useCtx();
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const runs = useApi(`/matters/${mid}/runs`, { matter: mid });
  const [task, setTask] = useState("");
  const [st, run, reset] = useCommand();
  const canDispatch = allowed(perms, "matter.dispatch");
  const canWrite = allowed(perms, "matter.write");
  // the execution list moving on is the confirmation; until now nothing ever cleared "Pending…"
  useEffect(() => { if (st.pending) reset(); }, [runs.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const move = async (to) => { if (await run(() => post(`/matters/${mid}/lifecycle`, { to }))) lc.reload(); };
  const dispatch = async (e) => {
    e.preventDefault();
    if (await run(() => post(`/matters/${mid}/executions`, { task_text: task }))) { setTask(""); runs.reload(); }
  };
  const archive = async () => { if (await run(() => post(`/matters/${mid}/state`, { to: m.archived ? "active" : "archived" }))) location.reload(); };
  return (
    <div className="stack">
      <div className="card qcard">
        <h2>Case stage</h2>
        <p>{lc.data?.stage ? <b>{lc.data.stage.replace(/_/g, " ")}</b> : "Not started"}
          {lc.data?.entered_at ? <span className="muted"> · since {fmtDate(lc.data.entered_at)}</span> : null}</p>
        {canWrite ? <p>{(lc.data?.next_allowed || []).map((to) => (
          <button key={to} type="button" className="btn" disabled={st.busy} onClick={() => move(to)}
            style={{ marginRight: 8 }}>Move to {to.toLowerCase().replace(/_/g, " ")}</button>))}</p> : null}
        <CommandError error={st.error} />
        {m.objectives ? <p><b>Objectives:</b> {m.objectives}</p> : null}
      </div>
      {canDispatch ? (
        <form className="card qcard" onSubmit={dispatch} aria-labelledby="disp-h">
          <h2 id="disp-h">Dispatch work</h2>
          <label htmlFor="disp-t">Instruction for lead counsel</label>
          <textarea id="disp-t" rows="2" required value={task} onChange={(e) => setTask(e.target.value)} />
          <p><button className="btn btn--primary" type="submit" disabled={st.busy}>Dispatch</button>
            {st.pending ? <span className="muted" role="status"> Pending… waiting for the worker to confirm.</span> : null}</p>
        </form>) : null}
      <div className="card qcard">
        <h2>Current executions</h2>
        {runs.loading ? <Loading rows={1} /> : (runs.data || []).length === 0
          ? <Empty>No executions yet.</Empty>
          : <ul>{runs.data.map((r) => <li key={r.execution_id}>
            <a href={href("workspace", { mid, tab: "workplan" })} className="mono">{r.execution_id}</a> <StatusChip kind="agent" state={r.state} />
            <span className="muted"> {fmtAgo(r.started_at)}</span></li>)}</ul>}
      </div>
      <section className="card qcard" aria-labelledby="mem-h">
        <h2 id="mem-h">Members</h2>
        <Members mid={mid} />
      </section>
      {canWrite ? <p><button type="button" className="btn" onClick={archive}>{m.archived ? "Re-open matter" : "Archive matter"}</button></p> : null}
    </div>
  );
}

function DocViewer({ doc, onClose }) {
  const [text, setText] = useState(null);
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    let u;
    blob(`/documents/${doc.doc_id}`).then(async (b) => {
      if (/\.(txt|md|csv|json)$/i.test(doc.filename)) setText(await b.text());
      else { u = URL.createObjectURL(b); setUrl(u); }
    }, setErr);
    return () => u && URL.revokeObjectURL(u);
  }, [doc]);
  return (
    <section className="stack" aria-label={`Document ${doc.filename}`}>
      <div className="prov">
        <span className="prov__title">{doc.filename}</span><span />
        <span className={`chip chip--${doc.ingest_status === "ingested" ? "verified" : "unverified"}`}
          data-icon={doc.ingest_status === "ingested" ? "✓" : "?"}>{doc.ingest_status === "ingested" ? "Ingested" : "Not ingested"}</span>
        <dl className="prov__meta">
          <div><dt>Origin</dt><dd>upload by {doc.created_by || "—"}</dd></div>
          <div><dt>Added</dt><dd>{fmtDate(doc.created_at)}</dd></div>
          <div><dt>Size</dt><dd>{doc.size} bytes</dd></div>
          <div><dt>SHA-256</dt><dd className="prov__chain">{(doc.sha256 || "").slice(0, 16)}…</dd></div>
        </dl>
      </div>
      <ErrorLine error={err} />
      {text != null ? <pre className="card" style={{ padding: 16, whiteSpace: "pre-wrap" }}>{text}</pre> : null}
      {url ? <p><a href={url} download={doc.filename}>Download {doc.filename}</a></p> : null}
      <button type="button" className="btn" onClick={onClose}>Back to documents</button>
    </section>
  );
}

function Documents({ mid }) {
  const { perms } = useCtx();
  const docs = useApi(`/matters/${mid}/documents`, { matter: mid });
  const [open, setOpen] = useState(null);
  const [st, run] = useCommand();
  const [source, setSource] = useState("");
  const [report, setReport] = useState(null);
  const file = useRef(null);
  const canWrite = allowed(perms, "matter.write");
  if (open) return <DocViewer doc={open} onClose={() => setOpen(null)} />;
  const onFiles = async (e) => {
    for (const f of e.target.files) await run(() => upload(`/matters/${mid}/documents`, f));
    e.target.value = "";
    docs.reload();
  };
  return (
    <div className="stack">
      {canWrite ? (
        <p>
          <input ref={file} type="file" multiple onChange={onFiles} className="sr-only" id="doc-up" tabIndex={-1} aria-hidden="true" />
          <button type="button" className="btn btn--primary" onClick={() => file.current?.click()}>Upload documents</button>
          {st.busy ? <span className="muted" role="status"> Uploading…</span> : null}
        </p>) : null}
      <CommandError error={st.error} />
      <ErrorLine error={docs.error} onRetry={docs.reload} />
      {docs.loading ? <Loading /> : (docs.data?.items || []).length === 0
        ? <Empty>No documents yet.</Empty> : (
          <table className="table" aria-label="Documents">
            <thead><tr><th scope="col">Name</th><th scope="col">Origin</th><th scope="col">Ingest</th><th scope="col">Added</th><th scope="col" className="num">Size</th></tr></thead>
            <tbody>{docs.data.items.map((d) => (
              <tr key={d.doc_id} onClick={() => setOpen(d)}>
                <td className="title"><b><a href={`#${d.doc_id}`} onClick={(e) => { e.preventDefault(); setOpen(d); }}>{d.filename}</a></b><span className="id">{d.doc_id}</span></td>
                <td>upload</td><td>{d.ingest_status}</td><td>{fmtDate(d.created_at)}</td><td className="num">{d.size}</td>
              </tr>))}</tbody>
          </table>)}
      {canWrite ? (
        <form className="card qcard" onSubmit={async (e) => {
          e.preventDefault();
          const r = await run(() => post(`/matters/${mid}/documents/ingest`, { source }));
          setReport(r?.data?.ingest_run || null);
        }}>
          <h2>Ingest operator-supplied law sources</h2>
          <label htmlFor="ing-s">Source path or sources-spec YAML <span className="hint">(files you downloaded yourself — W2)</span></label>
          <input id="ing-s" type="text" required value={source} onChange={(e) => setSource(e.target.value)} />
          <p><button type="submit" className="btn">Ingest</button>{st.busy ? <span className="muted" role="status"> Ingesting…</span> : null}</p>
          {report ? (  /* the TUI's /ingest report lines (parity, doc 14) */
            <div role="status">
              <p><b>Ingest done</b> — {report.chunks ?? 0} chunks.
                {![...(report.ingested || []), ...(report.skipped || []), ...(report.skipped_by_resume || [])].length
                  ? " Nothing in that source was a file this ingester reads — check the path and the file types." : ""}</p>
              <ul>
                {(report.ingested || []).map((n) => <li key={`i-${n}`}>✓ ingested: {n}</li>)}
                {(report.skipped || []).map((n) => <li key={`s-${n}`}>✕ skipped: {n}</li>)}
                {(report.skipped_by_resume || []).map((n) => <li key={`r-${n}`}>○ already in the corpus: {n}</li>)}
              </ul>
            </div>) : null}
        </form>) : null}
    </div>
  );
}

function Evidence({ mid }) {
  const [q, setQ] = useState("");
  const ev = useApi(`/matters/${mid}/evidence` + (q ? `?q=${encodeURIComponent(q)}` : ""), { matter: mid });
  const rows = ev.data?.items || [];
  return (
    <div className="stack">
      <label htmlFor="ev-q">Filter evidence and authorities by label</label>
      <input id="ev-q" type="text" value={q} onChange={(e) => setQ(e.target.value)} />
      <ErrorLine error={ev.error} onRetry={ev.reload} />
      {ev.loading ? <Loading /> : rows.length === 0 ? <Empty>No evidence recorded for this matter yet.</Empty> : (
        <table className="table" aria-label="Evidence">
          <thead><tr><th scope="col">Label</th><th scope="col">Excerpt</th><th scope="col">Source</th><th scope="col">Verification</th></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={r.evidence_id || i}>
              <td className="mono">{r.label || "—"}</td>
              <td style={{ whiteSpace: "normal" }}>{r.sentence || r.excerpt || r.note || "—"}</td>
              <td>{r.source || r.doc_id || "—"}</td>
              <td>{r.verified
                ? <span className="chip chip--verified" data-icon="✓">Verified quote</span>
                : <span className="chip chip--unverified" data-icon="?">Unverified assertion</span>}</td>
            </tr>))}</tbody>
        </table>)}
    </div>
  );
}

function WorkPlan({ mid }) {
  const runs = useApi(`/matters/${mid}/runs`, { matter: mid });
  const [sel, setSel] = useState(null);
  const rows = runs.data || [];
  return (
    <div style={{ display: "grid", gridTemplateColumns: sel ? "1fr 380px" : "1fr", gap: 16 }}>
      <div>
        <ErrorLine error={runs.error} onRetry={runs.reload} />
        {runs.loading ? <Loading /> : rows.length === 0 ? <Empty>No executions yet. Dispatch work from the Overview tab.</Empty> : (
          <table className="table" aria-label="Executions">
            <thead><tr><th scope="col">Execution</th><th scope="col">State</th><th scope="col">Task</th><th scope="col">Started</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.execution_id} aria-selected={sel === r.execution_id} onClick={() => setSel(r.execution_id)}>
                <td><a href={href("run", { rid: r.execution_id })} onClick={(e) => { e.preventDefault(); setSel(r.execution_id); }} className="mono">{r.execution_id}</a></td>
                <td><StatusChip kind="agent" state={r.state} /></td>
                <td>{r.input_task_text}</td><td>{fmtAgo(r.started_at)}</td>
              </tr>))}</tbody>
          </table>)}
      </div>
      {sel ? <RunDrawer rid={sel} mid={mid} onClose={() => setSel(null)} /> : null}
    </div>
  );
}

function Agents({ mid }) {
  const tk = useApi(`/matters/${mid}/tokens`, { matter: mid });
  const t = tk.data?.total;
  return (
    <div className="stack">
      <p>{t ? <>Matter total <b>{fmtTokens(t.all)}</b> tokens · in {fmtTokens(t.in)} · out {fmtTokens(t.out)} · thinking {fmtTokens(t.thinking)} · {t.dispatches} model calls</> : null}</p>
      <ErrorLine error={tk.error} onRetry={tk.reload} />
      {tk.loading ? <Loading /> : (tk.data?.agents || []).length === 0 ? <Empty>No model calls recorded for this matter yet.</Empty> : (
        <table className="table" aria-label="Tokens by agent">
          <thead><tr><th scope="col">Agent</th><th scope="col" className="num">Total</th><th scope="col" className="num">In</th>
            <th scope="col" className="num">Out</th><th scope="col" className="num">Thinking</th><th scope="col" className="num">Calls</th></tr></thead>
          <tbody>{tk.data.agents.map((a) => (
            <tr key={a.agent}><td>{a.agent}</td><td className="num">{fmtTokens(a.all)}</td><td className="num">{fmtTokens(a.in)}</td>
              <td className="num">{fmtTokens(a.out)}</td><td className="num">{fmtTokens(a.thinking)}</td><td className="num">{a.dispatches}</td></tr>))}</tbody>
        </table>)}
    </div>
  );
}

function Drafts({ mid }) {
  const { perms } = useCtx();
  const arts = useApi(`/matters/${mid}/artifacts`, { matter: mid });
  const [st, run] = useCommand();
  const rows = arts.data?.items || [];
  const why = allowed(perms, "matter.write") ? "" : "requires matter.write";
  return (
    <div className="stack">
      <ErrorLine error={arts.error} onRetry={arts.reload} />
      <CommandError error={st.error} />
      {arts.loading ? <Loading /> : rows.length === 0 ? <Empty>No drafts yet. Stage outputs appear in the Work plan tab.</Empty> : (
        <table className="table" aria-label="Drafts">
          <thead><tr><th scope="col">Title</th><th scope="col">Kind</th><th scope="col">Review</th><th scope="col">Updated</th><th scope="col">Action</th></tr></thead>
          <tbody>{rows.map((a) => (
            <tr key={a.artifact_id}>
              <td className="title"><b>{a.title}</b><span className="id">{a.artifact_id}</span></td>
              <td>{a.kind}</td><td>{a.review_state}</td><td>{fmtAgo(a.updated_at)}</td>
              <td><Btn why={why} onClick={() => run(() => post(`/artifacts/${a.artifact_id}/review`, { decision: "approved" }))}>Mark reviewed</Btn></td>
            </tr>))}</tbody>
        </table>)}
    </div>
  );
}

function Decisions({ mid }) {
  const pend = useApi(`/matters/${mid}/approvals?state=pending`, { matter: mid });
  const done = useApi(`/matters/${mid}/approvals?state=approved`, { matter: mid });
  const rej = useApi(`/matters/${mid}/approvals?state=rejected`, { matter: mid });
  const decided = [...(done.data || []), ...(rej.data || [])];
  return (
    <div className="stack">
      <h2>Waiting on you ({(pend.data || []).length})</h2>
      {(pend.data || []).length === 0 ? <Empty>Nothing waiting.</Empty>
        : <p><a href={href("approvals")}>Decide these in the Approval Center</a></p>}
      <ul>{(pend.data || []).map((a) => <li key={a.approval_id}>⚑ {a.kind} · <span className="id">{a.approval_id}</span> · requested {fmtAgo(a.requested_at)}</li>)}</ul>
      <h2>Decided</h2>
      {decided.length === 0 ? <Empty>No decisions yet.</Empty> : (
        <table className="table" aria-label="Decided approvals">
          <thead><tr><th scope="col">Kind</th><th scope="col">Decision</th><th scope="col">By</th><th scope="col">Note</th><th scope="col">When</th></tr></thead>
          <tbody>{decided.map((a) => <tr key={a.approval_id}><td>{a.kind}</td><td>{a.state}</td><td>{a.decided_by}</td>
            <td>{a.decision_note || "—"}</td><td>{fmtDate(a.decided_at)}</td></tr>)}</tbody>
        </table>)}
    </div>
  );
}

// S9 activity: the matter channel replayed from the start (Last-Event-ID absent), then live
function Activity({ mid }) {
  const [events, setEvents] = useState([]);
  const [type, setType] = useState("");
  useEffect(() => {
    setEvents([]);
    return subscribe([`matter:${mid}`], (e) => setEvents((xs) => [e, ...xs]));
  }, [mid]);
  const types = [...new Set(events.map((e) => e.event.split(".")[0]))];
  const shown = type ? events.filter((e) => e.event.startsWith(`${type}.`)) : events;
  return (
    <div className="stack">
      <div className="filters" role="group" aria-label="Filter activity">
        <button type="button" className="filter" aria-pressed={!type} onClick={() => setType("")}>All</button>
        {types.map((t) => <button key={t} type="button" className="filter" aria-pressed={type === t} onClick={() => setType(t)}>{t}</button>)}
      </div>
      {shown.length === 0 ? <Empty>No activity yet.</Empty> : (
        <ol className="timeline timeline--activity" aria-label="Activity, newest first">
          {shown.map((e) => (
            <li key={e.id} data-state="done">
              <time dateTime={e.data?.ts}>{e.data?.ts ? new Date(e.data.ts).toLocaleString("en-NZ") : ""}</time>
              <b>{e.event}</b>{e.data?.task_id ? <span className="id"> {e.data.task_id}</span> : null}
            </li>))}
        </ol>)}
    </div>
  );
}

function Audit({ mid }) {
  const { perms } = useCtx();
  const can = allowed(perms, "audit.read");
  const au = useApi(can ? `/audit?matter_id=${encodeURIComponent(mid)}` : null, { matter: mid });
  if (!can) return <p className="table__empty">🔒 The audit chain needs the audit.read permission.</p>;
  const chain = au.data?.chain;
  return (
    <div className="stack">
      {chain ? (chain.ok
        ? <p><span className="chip chip--done" data-icon="✓">Chain verified</span> every row hashes to the one before it.</p>
        : <p><span className="chip chip--failed" data-icon="⚠">Chain broken</span> first bad row: <span className="id">{chain.first_bad}</span></p>) : null}
      <ErrorLine error={au.error} onRetry={au.reload} />
      {au.loading ? <Loading /> : (
        <table className="table" aria-label="Audit chain">
          <thead><tr><th scope="col">When</th><th scope="col">Actor</th><th scope="col">Action</th><th scope="col">Target</th><th scope="col">Hash</th></tr></thead>
          <tbody>{(au.data?.items || []).map((r) => (
            <tr key={r.audit_id}><td>{new Date(r.ts).toLocaleString("en-NZ")}</td><td>{r.actor}</td><td>{r.action}</td>
              <td className="mono">{r.target}</td><td className="mono">{(r.hash || "").slice(0, 12)}</td></tr>))}</tbody>
        </table>)}
    </div>
  );
}

export default function Workspace({ mid, tab }) {
  const m = useApi(`/matters/${mid}`, { matter: mid });
  const panes = { overview: Overview, documents: Documents, evidence: Evidence, workplan: WorkPlan,
    agents: Agents, drafts: Drafts, decisions: Decisions, activity: Activity, audit: Audit };
  const Pane = panes[tab] || Overview;
  if (m.error) return <ErrorLine error={m.error} onRetry={m.reload} />;
  if (!m.data) return <Loading />;
  return (
    <section aria-labelledby="ws-h">
      <MatterHeader m={m.data} mid={mid} />
      <nav className="filters" aria-label="Matter sections">
        {TABS.map(([k, label]) => (
          <a key={k} className={`filter${tab === k ? " filter--on" : ""}`} href={href("workspace", { mid, tab: k })}
            aria-current={tab === k ? "page" : undefined}>{label}</a>))}
        <a className="filter" href={href("case", { mid })}>Guided view →</a>
      </nav>
      <Pane mid={mid} m={m.data} />
    </section>
  );
}
