// S3 Matter Workspace (05 §3): persistent matter header + 9 tabs (Swarm/Chat are M10,
// Research folds into Evidence — plan §0). S8 document viewer + S9 activity/audit live here.
import { useEffect, useRef, useState } from "react";
import { ApiError, blob, del, get, page, post, upload } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { subscribe } from "../sse.js";
import { useApi } from "../useApi.js";
import { BulkBar, Btn, Empty, ErrorLine, LiveNote, Loading, SelectAll, SelectCell, StatusChip, allowed, confirmDelete,
  fmtAgo, fmtDate, fmtDue, fmtTokens, useSelect } from "../ui.jsx";
import { ApprovalCard, plainKind } from "./Approvals.jsx";
import { DEADLINE_WORD, Deadlines, JOURNEY_STRIP, LawyerNowBanner, STAGE_PLAIN, stripIndex } from "./CaseScreens.jsx";
import { MatterChat, RunDrawer } from "./RunPage.jsx";
import { Members } from "./Users.jsx";

export const stageName = (s) => s.toLowerCase().replace(/_/g, " ");
// the soonest open deadline; "met" ones are history
export const nextDeadline = (items = []) => items.filter((d) => d.status !== "met")
  .sort((a, b) => (a.due || "").localeCompare(b.due || ""))[0];
// a value the API returned, else an honest gap: unavailable (read failed) / loading / none recorded
export const orGap = (r, value, none = "—") => value ?? (r.error
  ? <span className="muted" title={r.error.message}>unavailable</span>
  : r.loading ? <span className="muted">loading…</span> : none);

export const TABS = [["overview", "Overview"], ["documents", "Documents"], ["evidence", "Evidence"],
  ["workplan", "Work plan"], ["agents", "Agents"], ["drafts", "Drafts"], ["decisions", "Decisions"],
  ["deadlines", "Deadlines"], ["activity", "Activity"], ["audit", "Audit"]];

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

// Persistent identity + the four answers a lawyer needs before any tab: where the case is,
// what is due next, what waits on them, how fresh it is. Only fields the API returned.
export function MatterContext({ m, mid, lc, dl }) {
  const next = nextDeadline(dl.data?.items);
  const nPend = m.outstanding_approvals || 0;
  const stage = lc.data?.stage;
  return (
    <>
      <div className="hdr">
        <h1 id="ws-h">{m.title || mid}</h1>
        <span className="sub"><span className="id">{mid}</span>
          {m.client_ref ? ` · ${m.client_ref}` : ""}{m.matter_type ? ` · ${m.matter_type}` : ""}
          {m.jurisdiction ? ` · ${m.jurisdiction}` : ""}</span>
        <span className="act">
          {m.confidentiality ? <span className="chip" data-icon="▣">{m.confidentiality}</span> : null}
          {m.archived ? <StatusChip state="archived" /> : <StatusChip state={m.state} />}</span>
      </div>
      <dl className="ctxbar" aria-label="Matter at a glance">
        <div><dt>Lifecycle stage</dt><dd>{orGap(lc, stage ? <>{stageName(stage)}
          {lc.data.entered_at ? <span className="muted"> · since {fmtDate(lc.data.entered_at)}</span> : null}</> : null, "Not started")}</dd></div>
        <div><dt>Next deadline</dt><dd className={next?.status === "overdue" ? "due-late" : undefined}>
          {orGap(dl, next ? <a href={href("workspace", { mid, tab: "deadlines" })}>
            {`${next.status === "overdue" ? "⚠ overdue · " : ""}${next.what} — ${fmtDue(next.due)}`}</a> : null, "None recorded")}</dd></div>
        <div><dt>Waiting on you</dt><dd>{nPend
          ? <a className="chip chip--waiting" data-icon="⚑" href={href("workspace", { mid, tab: "decisions" })}>{nPend} pending</a>
          : m.state === "waiting_on_you"  /* no approval row: a run (e.g. paused) waits for a person */
            ? <a className="chip chip--waiting" data-icon="⏸" href={href("workspace", { mid, tab: "workplan" })}>A run is waiting — Work plan</a>
            : "Nothing pending"}</dd></div>
        <div><dt>Last activity</dt><dd>{fmtAgo(m.last_activity_at || m.updated_at || m.created_at)}</dd></div>
      </dl>
    </>
  );
}

function MatterHeader({ m, mid }) {
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  return (<><LawyerNowBanner mid={mid} /><MatterContext m={m} mid={mid} lc={lc} dl={dl} /></>);
}

const clip = (s, n = 120) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || "");

// a summary card: its own loading / error / empty line, never a blank panel (05 §10)
function Block({ id, title, r, empty, children, more }) {
  return (
    <section className="card qcard" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      <ErrorLine error={r.error} onRetry={r.reload} stale={r.stale} />
      {r.loading ? <Loading rows={1} /> : r.error && !r.stale ? null : children || <p className="muted">{empty}</p>}
      {more}
    </section>
  );
}

// The overview: the matter's operational state at a glance, each line linking to where it lives.
// Every read is a hook result {data, error, loading, stale} so the states render honestly.
export function OverviewSummary({ mid, m, pend, na, lc, dl, runs, docs, facts, nextAction = null, stageActions = null }) {
  const wait = pend.data || [];
  const paused = (runs.data || []).filter((r) => r.state === "paused");  // a person must resume these
  const open =(dl.data?.items || []).filter((d) => d.status !== "met")
    .sort((a, b) => (a.due || "").localeCompare(b.due || ""));
  const stage = lc.data?.stage;
  const at = stripIndex(stage);
  const recent = (lc.data?.history || []).slice(-3).reverse();
  const work = (runs.data || []).slice(0, 4);
  const files = [...(docs.data?.items || [])].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")).slice(0, 4);
  const other = facts.data?.fields?.other_party;
  const tab = (t) => href("workspace", { mid, tab: t });
  return (
    <div className="ovgrid">
      <div className="stack">
        <Block id="ov-wait" title={`⚑ Waiting on you${pend.data ? ` · ${wait.length + paused.length}` : ""}`} r={pend}
          empty="Nothing is waiting on you on this matter."
          more={wait.length ? <p><a href={tab("decisions")}>Decide in Decisions →</a></p> : null}>
          {wait.length || paused.length ? <ul className="rows">{paused.map((r) => (
            <li key={r.execution_id}><a href={href("run", { rid: r.execution_id })}><b>Paused run — resume or cancel</b></a>
              <p className="muted">{clip(r.input_task_text) || r.execution_id}</p></li>))}
            {wait.slice(0, 4).map((a) => (
            <li key={a.approval_id}><a href={tab("decisions")}><b>{plainKind(a.kind, false)}</b></a>
              <span className="muted"> · requested {fmtAgo(a.requested_at)}</span>
              {clip(a.request_payload?.question || a.request_payload?.summary || a.request_payload?.result_summary)
                ? <p className="muted">{clip(a.request_payload?.question || a.request_payload?.summary || a.request_payload?.result_summary)}</p> : null}
            </li>))}</ul> : null}
        </Block>
        <Block id="ov-next" title="Next action" r={na} empty="No open next action recorded.">
          {nextAction}
        </Block>
        <Block id="ov-pos" title="Case position" r={lc} empty="">
          <p>{stage ? <><b>{stageName(stage)}</b> <span className="muted">({STAGE_PLAIN[stage] || stage})</span>
            {lc.data.entered_at ? <span className="muted"> · since {fmtDate(lc.data.entered_at)}</span> : null}</>
            : "Not started — no lifecycle stage recorded yet."}</p>
          <ol className="timeline" aria-label="Case lifecycle">
            {JOURNEY_STRIP.map(([label], i) => (
              <li key={label} data-state={i < at ? "done" : undefined} aria-current={i === at ? "step" : undefined}>{label}</li>))}
          </ol>
          {recent.length ? <ul className="rows" aria-label="Recent stage changes">{recent.map((h, i) => (
            <li key={i}>Moved to <b>{stageName(h.to)}</b><span className="muted"> by {h.actor} · {fmtAgo(h.ts)}</span></li>))}</ul> : null}
          {stageActions}
          {m.objectives ? <p><b>Objectives:</b> {m.objectives}</p> : null}
        </Block>
        <Block id="ov-dl" title={`Deadlines${dl.data ? ` · ${open.length} open` : ""}`} r={dl} empty="No deadlines recorded."
          more={<p><a href={tab("deadlines")}>{open.length ? "All deadlines →" : "Add a deadline →"}</a></p>}>
          {open.length ? <ul className="rows">{open.slice(0, 5).map((d) => (
            <li key={d.deadline_id || d.what} className={d.status === "overdue" ? "due-late" : undefined}>
              <a href={tab("deadlines")}><b>{d.what}</b></a> — {fmtDue(d.due)} · {DEADLINE_WORD[d.status] || d.status}</li>))}</ul> : null}
        </Block>
      </div>
      <div className="stack">
        <Block id="ov-work" title="Recent work" r={runs} empty="No executions yet."
          more={work.length ? <p><a href={tab("workplan")}>All in Work plan →</a></p> : null}>
          {work.length ? <ul className="rows">{work.map((r) => (
            <li key={r.execution_id}><StatusChip kind="agent" state={r.state} />{" "}
              <a href={tab("workplan")}>{clip(r.input_task_text, 70) || r.execution_id}</a>
              <span className="muted"> · {fmtAgo(r.started_at)}</span></li>))}</ul> : null}
        </Block>
        <Block id="ov-docs" title="Latest documents" r={docs} empty="No documents yet."
          more={<p><a href={tab("documents")}>{files.length ? "All documents →" : "Upload in Documents →"}</a></p>}>
          {files.length ? <ul className="rows">{files.map((d) => (
            <li key={d.doc_id}><a href={docHref(mid, d.doc_id)}>{d.filename}</a>
              <span className="muted"> · {d.ingest_status === "ingested" ? "ingested" : "not ingested"} · {fmtDate(d.created_at)}</span></li>))}</ul> : null}
        </Block>
        <Block id="ov-parties" title="Parties" r={facts} empty="">
          <dl className="kv">
            <dt>Client</dt><dd>{m.client_ref || <span className="muted">Not recorded</span>}</dd>
            <dt>Other side</dt><dd>{other ? String(other) : <span className="muted">Not recorded</span>}</dd>
          </dl>
        </Block>
      </div>
    </div>
  );
}

function Overview({ mid, m }) {
  const { perms } = useCtx();
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const runs = useApi(`/matters/${mid}/runs`, { matter: mid });
  const pend = useApi(`/matters/${mid}/approvals?state=pending`, { matter: mid });
  const na = useApi(`/matters/${mid}/next-actions`, { matter: mid });
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  const docs = useApi(`/matters/${mid}/documents`, { matter: mid });
  const facts = useApi(`/matters/${mid}/dossier/facts`, { matter: mid });
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
  const first = na.data?.items?.[0];
  const complete = async () => { if (await run(() => post(`/matters/${mid}/next-actions/${first.proposal_id}/complete`, {}))) na.reload(); };
  return (
    <div className="stack">
      <OverviewSummary mid={mid} m={m} pend={pend} na={na} lc={lc} dl={dl} runs={runs} docs={docs} facts={facts}
        nextAction={first ? (<>
          <p><b>{first.what}</b>{first.due ? <span className="muted"> · by {fmtDue(first.due)}</span> : null}</p>
          {first.why ? <p className="muted">{first.why}</p> : null}
          {first.missed_consequence ? <p className="small">If missed: {first.missed_consequence}</p> : null}
          <Btn why={canWrite ? "" : "requires matter.write"} disabled={st.busy} onClick={complete}>Mark done</Btn>
          {(na.data.items.length > 1) ? <p className="muted">{na.data.items.length - 1} more open</p> : null}
        </>) : null}
        stageActions={canWrite && (lc.data?.next_allowed || []).length ? <p>{lc.data.next_allowed.map((to) => (
          <button key={to} type="button" className="btn" disabled={st.busy} onClick={() => move(to)}
            style={{ marginRight: 8 }}>Move to {stageName(to)}</button>))}</p> : null} />
      <CommandError error={st.error} />
      {canDispatch ? (
        <form className="card qcard" onSubmit={dispatch} aria-labelledby="disp-h">
          <h2 id="disp-h">Dispatch work</h2>
          <label htmlFor="disp-t">Instruction for lead counsel</label>
          <textarea id="disp-t" rows="2" required value={task} onChange={(e) => setTask(e.target.value)} />
          <p><button className="btn btn--primary" type="submit" disabled={st.busy}>Dispatch</button>
            {st.pending ? <span className="muted" role="status"> Pending… waiting for the worker to confirm.</span> : null}</p>
        </form>) : null}
      <section className="card qcard" aria-labelledby="mem-h">
        <h2 id="mem-h">Members</h2>
        <Members mid={mid} />
      </section>
      {canWrite ? <p><button type="button" className="btn" onClick={archive}>{m.archived ? "Re-open matter" : "Archive matter"}</button></p> : null}
    </div>
  );
}

// M13.4: plain text as-is, PDF in the browser's own viewer, everything else (DOCX, HTML…)
// as server-extracted text — no pixel-faithful Office rendering by design
export const viewMode = (name) =>
  /\.(txt|md|csv|json)$/i.test(name) ? "text" : /\.pdf$/i.test(name) ? "pdf" : "extracted";

// M13.5: wrap every case-insensitive occurrence of q in <mark> (matches land on odd indices)
export function highlight(text, q) {
  const w = (q || "").trim();
  if (!w) return [text];
  const re = new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi");
  return text.split(re).map((s, i) => (i % 2 ? <mark key={i}>{s}</mark> : s));
}

// UX-5 evidence navigation: one URL shape for "open this document (at this passage)", used by the
// document list, the overview and evidence rows. Real history entries, so browser Back returns to
// wherever the user came from (evidence row, overview, list).
export const docHref = (mid, doc, chunk) => href("workspace", { mid, tab: "documents", item: doc, part: chunk });
export const draftHref = (mid, aid) => href("workspace", { mid, tab: "drafts", item: aid });

// a passage by its id `i` from GET /documents/{id}/chunks (the corpus rowid — stable, not a position);
// anything else (non-numeric, not in this document) is no passage. "Passage N" labels are positions.
export const passageAt = (chunks, ref) =>
  (ref == null || !/^\d+$/.test(String(ref)) ? null : chunks.find((c) => c.i === Number(ref)) || null);
export const hits = (text, q) => {
  const w = (q || "").trim().toLowerCase();
  return w ? text.toLowerCase().split(w).length - 1 : 0;
};
// verification exactly as supplied: evidence `verified` (04 §5.3) or the citation guard's verdict
// (moot/verify.py). Anything else — including absence — is "not supplied", never either answer.
const VERDICT = {
  VERIFIED: ["verified", "✓", "Verified quote", "The quoted words are, byte for byte, in this matter's corpus"],
  MISMATCH: ["unverified", "?", "Mismatch", "The cited passage does not contain this quote"],
  NOT_IN_CORPUS: ["unverified", "?", "Not in corpus", "These words are nowhere in this matter's corpus"],
  PRIVILEGED: ["waiting", "⚠", "Privileged source", "Found only in privileged material — must not appear in an open deliverable"],
};
export function VerifyChip({ v }) {
  const key = v === true ? "VERIFIED" : String(v);
  const [cls, icon, word, why] = Object.hasOwn(VERDICT, key) ? VERDICT[key]
    : v === false ? ["unverified", "?", "Unverified", "Recorded as not verified"]
      : ["", "–", "Not supplied", "The server records no verification state for this item"];
  return <span className={`chip${cls ? ` chip--${cls}` : ""}`} data-icon={icon} title={why}>{word}</span>;
}

const MODE_NOTE = {
  text: "Plain-text file, shown as stored.",
  pdf: "Original PDF in your browser's viewer.",
  extracted: "Reading view — text extracted from the file by the server; layout and formatting are not preserved.",
};

// Presentational: every state comes in as props so each one is testable without a DOM.
// content: {text, url, err}; passages: {items, loaded, err}; sel: the passage ref from the URL or a rail pick.
export function DocView({ mid, doc, content, passages, q = "", setQ = () => {}, sel = null, onPick = () => {} }) {
  const mode = viewMode(doc.filename);
  const items = passages.items;
  const cur = passageAt(items, sel);
  const label = (c, k) => c.heading || `Passage ${k + 1}`;
  const broken = !!content.err;
  const missing = content.err?.code === "document_file_missing";
  const unreadable = content.err?.code === "unreadable_document";
  const total = q.trim() ? (items.length ? items.reduce((n, c) => n + hits(c.text, q), 0) : hits(content.text || "", q)) : 0;
  const ingested = doc.ingest_status === "ingested";
  return (
    <section className="stack" aria-label={`Document ${doc.filename}`}>
      <p className="small"><a href={href("workspace", { mid, tab: "documents" })}>← All documents in this matter</a></p>
      <div className="prov">
        <span className="prov__title">{doc.filename}</span><span />
        <span className={`chip chip--${ingested ? "verified" : "unverified"}`} data-icon={ingested ? "✓" : "?"}>
          {ingested ? "Ingested" : doc.ingest_status === "skipped" ? "Skipped by ingest" : "Not ingested"}</span>
        <dl className="prov__meta">
          {doc.doc_type ? <div><dt>Type</dt><dd>{doc.doc_type}</dd></div> : null}
          {doc.jurisdiction ? <div><dt>Jurisdiction</dt><dd>{doc.jurisdiction}</dd></div> : null}
          <div><dt>Origin</dt><dd>upload by {doc.created_by || "—"}</dd></div>
          <div><dt>Added</dt><dd>{fmtDate(doc.created_at)}</dd></div>
          <div><dt>Size</dt><dd>{doc.size} bytes</dd></div>
          <div><dt>SHA-256</dt><dd className="prov__chain" title={doc.sha256}>{(doc.sha256 || "").slice(0, 16)}…</dd></div>
          <div><dt>Document ID</dt><dd className="id">{doc.doc_id}</dd></div>
        </dl>
      </div>
      {missing ? <p className="field-error" role="alert">The stored file for this document is missing on the server,
        so it cannot be shown or searched. Upload it again to restore it.</p>
        : unreadable ? <p className="field-error" role="alert">IronFleet could not extract readable text from this file
          ({content.err.message}). {content.url ? "Download the original to read it, or upload" : "Upload"} a readable copy (PDF, DOCX or plain text).</p>
          : <ErrorLine error={content.err} />}
      {!broken ? <p className="small muted">{MODE_NOTE[mode]}</p> : null}
      {sel != null && passages.loaded && !cur ? <p className="small" role="status">
        {passages.err ? `The linked passage (ref ${sel}) cannot be shown because this document's passages could not be loaded`
          : `The linked passage (ref ${sel}) is not one of this document's indexed passages — it may have been re-ingested`} — showing the whole document instead.</p> : null}
      {content.text != null || items.length ? (
        <p><label htmlFor="doc-find">Find in document </label>
          <input id="doc-find" type="search" value={q} onChange={(e) => setQ(e.target.value)} />
          {q.trim() ? <span className="muted" role="status">{` ${total} match${total === 1 ? "" : "es"}`}</span> : null}</p>) : null}
      <div className={items.length ? "docsplit" : undefined}>
        {items.length ? (
          <nav className="card docrail" aria-label="Passages">
            <p className="small muted">{`${items.length} passage${items.length === 1 ? "" : "s"} — as agents retrieve them`}</p>
            <ol>{items.map((c, k) => {
              const n = hits(c.text, q);
              return <li key={c.i}><button type="button" aria-current={cur?.i === c.i ? "true" : undefined}
                onClick={() => onPick(c.i)}>{label(c, k)}
                {n ? <span className="pill">{n}<span className="sr-only"> matches</span></span> : null}</button></li>;
            })}</ol>
          </nav>) : null}
        <div className="stack">
          {content.url && mode === "pdf" ? <iframe className="card" src={content.url} title={`${doc.filename} (PDF viewer)`}
            style={{ width: "100%", height: "75vh", border: 0 }} /> : null}
          {items.length ? (
            <ol className="stack" aria-label="Passages as retrieval sees them" style={{ listStyle: "none", padding: 0 }}>
              {items.map((c, k) => (
                <li key={c.i} id={`chunk-${c.i}`} className="card passage" aria-current={cur?.i === c.i ? "true" : undefined}>
                  <h3>{label(c, k)}</h3>
                  <p style={{ whiteSpace: "pre-wrap" }}>{highlight(c.text, q)}</p>
                </li>))}
            </ol>
          ) : content.text != null ? <pre className="card" style={{ padding: 16, whiteSpace: "pre-wrap" }}>{highlight(content.text, q)}</pre> : null}
        </div>
      </div>
      {broken ? null : passages.err ? <p className="small muted">Passages unavailable: {passages.err.message}</p>
        : passages.loaded && !items.length ? <p className="small muted">{ingested
          ? "No indexed passages match this file's current text, so agents are not retrieving from it."
          : doc.ingest_status === "skipped"
            ? "The last ingest skipped this file (unsupported type, or too little text to index), so agents cannot retrieve passages from it."
            : "Not ingested — agents cannot retrieve passages from this document until it is ingested (Documents → Ingest documents)."}</p> : null}
      {content.url ? <p><a href={content.url} download={doc.filename}>Download {doc.filename}</a></p> : null}
    </section>
  );
}

function DocBody({ mid, doc, chunkRef }) {
  const [content, setContent] = useState({ text: null, url: null, err: null });
  const [passages, setPassages] = useState({ items: [], loaded: false, err: null });
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(chunkRef ?? null);
  const mode = viewMode(doc.filename);
  useEffect(() => setSel(chunkRef ?? null), [chunkRef]);   // a new deep link to the same document
  useEffect(() => {
    let u;
    const put = (x) => setContent((c) => ({ ...c, ...x }));
    blob(`/documents/${doc.doc_id}`).then(async (b) => {
      if (mode === "text") return put({ text: await b.text() });
      // the API serves octet-stream; re-type it or the iframe downloads instead of rendering
      u = URL.createObjectURL(mode === "pdf" ? new Blob([b], { type: "application/pdf" }) : b);
      put({ url: u });
      if (mode === "extracted") put({ text: (await get(`/documents/${doc.doc_id}/text`)).text });
    }).catch((err) => put({ err }));
    // the passages retrieval sees; [] when the document was never corpus-ingested
    get(`/documents/${doc.doc_id}/chunks`).then((r) => setPassages({ items: r.chunks || [], loaded: true, err: null }),
      (err) => setPassages({ items: [], loaded: true, err }));
    return () => u && URL.revokeObjectURL(u);
  }, [doc.doc_id, mode]);
  useEffect(() => {   // the selected passage into view once passages exist (deep link or rail pick)
    if (sel != null && passages.loaded) document.getElementById(`chunk-${sel}`)?.scrollIntoView?.({ block: "start" });
  }, [sel, passages.loaded]);
  useEffect(() => {
    const w = q.trim().toLowerCase();
    const hit = w && passages.items.find((c) => c.text.toLowerCase().includes(w));
    if (hit) document.getElementById(`chunk-${hit.i}`)?.scrollIntoView?.({ block: "center" });
  }, [q, passages.items]);
  // the URL follows the picked passage (shareable) without stacking a history entry per click
  const pick = (i) => { setSel(i); history.replaceState(null, "", docHref(mid, doc.doc_id, i)); };
  return <DocView mid={mid} doc={doc} content={content} passages={passages} q={q} setQ={setQ} sel={sel} onPick={pick} />;
}

// The viewer opens a document only when the server says it belongs to THIS matter
// (GET /documents/{id}/meta, parent-matter authz): a doc id from another matter — even one the
// user may read — never reaches the bytes/text/chunks routes here, and "not here" and
// "not yours" (404) read the same.
export function DocViewer({ mid, docId, chunkRef, meta }) {
  if (meta.loading) return <Loading />;
  const doc = meta.data?.matter_id === mid ? meta.data : null;
  if (!doc && meta.error && ![403, 404].includes(meta.error.status)) return <ErrorLine error={meta.error} onRetry={meta.reload} />;
  if (!doc) return (
    <section className="only-note" aria-label="Document not available">
      <h2>Document not available</h2>
      <p>It is not in this matter, it was deleted, or you cannot read it.</p>
      <p><a href={href("workspace", { mid, tab: "documents" })}>All documents in this matter</a></p>
    </section>);
  return <DocBody key={doc.doc_id} mid={mid} doc={doc} chunkRef={chunkRef} />;
}

function Documents({ mid, item: openId, part: chunk }) {
  const { perms } = useCtx();
  const docs = useApi(`/matters/${mid}/documents`, { matter: mid });
  const meta = useApi(openId ? `/documents/${openId}/meta` : null, { matter: mid });
  const [st, run] = useCommand();
  const [source, setSource] = useState("");
  const [report, setReport] = useState(null);
  const file = useRef(null);
  const pick = useSelect();
  const canWrite = allowed(perms, "matter.write");
  if (openId) return <DocViewer mid={mid} docId={openId} chunkRef={chunk} meta={meta} />;
  const why = canWrite ? "" : "requires matter.write";
  const remove = async (ids) => {
    if (!confirmDelete(ids.length, "document")) return;
    await run(async () => { for (const id of ids) await del(`/documents/${id}`); });
    pick.clear();
    docs.reload();
  };
  const onFiles = async (e) => {
    for (const f of e.target.files) await run(() => upload(`/matters/${mid}/documents`, f));
    e.target.value = "";
    docs.reload();
  };
  const ingestMine = async () => {
    const r = await run(() => post(`/matters/${mid}/documents/ingest`, { source: "" }));
    setReport(r?.data?.ingest_run || null);
    docs.reload();
  };
  const hasDocs = (docs.data?.items || []).length > 0;
  return (
    <div className="stack">
      {canWrite ? (
        <p>
          <input ref={file} type="file" multiple onChange={onFiles} className="sr-only" id="doc-up" tabIndex={-1} aria-hidden="true" />
          <button type="button" className="btn btn--primary" onClick={() => file.current?.click()}>Upload documents</button>{" "}
          {hasDocs ? <button type="button" className="btn" onClick={ingestMine} disabled={st.busy}
            title="Run this matter's uploaded documents through the retrieval pipeline">Ingest documents</button> : null}
          {st.busy ? <span className="muted" role="status"> Working…</span> : null}
        </p>) : null}
      <CommandError error={st.error} />
      <ErrorLine error={docs.error} onRetry={docs.reload} />
      <BulkBar s={pick} why={why} busy={st.busy} onDelete={() => remove([...pick.sel])} />
      {docs.loading ? <Loading /> : (docs.data?.items || []).length === 0
        ? <Empty>No documents yet.</Empty> : (
          <table className="table" aria-label="Documents">
            <thead><tr><SelectAll ids={docs.data.items.map((d) => d.doc_id)} s={pick} /><th scope="col">Name</th><th scope="col">Origin</th><th scope="col">Ingest</th><th scope="col">Added</th><th scope="col" className="num">Size</th>
              <th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{docs.data.items.map((d) => (
              <tr key={d.doc_id} onClick={() => { location.hash = docHref(mid, d.doc_id); }}>
                <SelectCell id={d.doc_id} label={d.filename} s={pick} />
                <td className="title"><b><a href={docHref(mid, d.doc_id)} onClick={(e) => e.stopPropagation()}>{d.filename}</a></b><span className="id">{d.doc_id}</span></td>
                <td>upload</td><td>{d.ingest_status}</td><td>{fmtDate(d.created_at)}</td><td className="num">{d.size}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <Btn why={why} disabled={st.busy} onClick={() => remove([d.doc_id])}>Delete</Btn></td>
              </tr>))}</tbody>
          </table>)}
      {canWrite ? (
        <form className="card qcard" onSubmit={async (e) => {
          e.preventDefault();
          const r = await run(() => post(`/matters/${mid}/documents/ingest`, { source }));
          setReport(r?.data?.ingest_run || null);
          docs.reload();
        }}>
          <h2>Ingest operator-supplied law sources</h2>
          <label htmlFor="ing-s">Source path or sources-spec YAML <span className="hint">(files you downloaded yourself — W2)</span></label>
          <input id="ing-s" type="text" required value={source} onChange={(e) => setSource(e.target.value)} />
          <p><button type="submit" className="btn">Ingest</button>{st.busy ? <span className="muted" role="status"> Ingesting…</span> : null}</p>
        </form>) : null}
      {report ? (  /* the TUI's /ingest report lines (parity, doc 14) — shared by both ingest actions */
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
    </div>
  );
}

// one evidence register row (GET /matters/{mid}/evidence: evidence_id, op, label, file, sha256,
// actor, ts + doc_id, which the server sets only on an exact SHA-256 match to an upload of this matter)
export function EvidenceRow({ mid, r }) {
  return (
    <tr>
      <td className="mono">{r.label || "—"}</td>
      <td>{r.doc_id ? <a href={docHref(mid, r.doc_id)}>View source · {r.file || r.doc_id}</a>
        : <>{r.file || "—"}{r.file ? <span className="muted small"> · no upload in this matter has this file's SHA-256</span> : null}</>}</td>
      <td>{r.actor || "—"}<span className="muted"> · {fmtDate(r.ts)}</span></td>
      <td><VerifyChip v={r.verified} /></td>
    </tr>);
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
      {ev.loading ? <Loading /> : rows.length === 0 ? <Empty>No evidence recorded for this matter yet.
        Quotations in drafts are checked against the matter's documents in each draft's Sources panel.</Empty> : (
        <table className="table" aria-label="Evidence">
          <thead><tr><th scope="col">Label</th><th scope="col">Source</th><th scope="col">Recorded</th><th scope="col">Verification</th></tr></thead>
          <tbody>{rows.map((r, i) => <EvidenceRow key={r.evidence_id || i} mid={mid} r={r} />)}</tbody>
        </table>)}
    </div>
  );
}

// GET /artifacts/{aid}/sources: each quotation the citation guard checked, with the upload +
// passage it was found in. A link only when the server resolved both; never from the quote text.
export function DraftSources({ mid, s }) {
  const quotes = s.data?.quotes || [];
  const none = s.data && s.data.corpus_chunks === 0;   // nothing ingested: no verdict is meaningful
  return (
    <section className="card qcard" aria-labelledby="dsrc-h">
      <h2 id="dsrc-h">Sources quoted in this draft</h2>
      <p className="small muted">Each quotation of six or more words, checked word for word against this matter's ingested documents.</p>
      <ErrorLine error={s.error} onRetry={s.reload} />
      {s.loading ? <Loading rows={1} /> : !s.data ? null : !quotes.length
        ? <p className="muted">{none ? "No documents are ingested for this matter, so there is nothing to check against."
          : "This draft quotes no passage of six or more words."}</p> : (<>
          {none ? <p className="small">No documents are ingested for this matter, so these quotations could not be checked.</p> : null}
          <ul className="rows">{quotes.map((q, i) => (
            <li key={i}><VerifyChip v={none ? undefined : q.verdict} />{" "}“{clip(q.quote, 180)}”
              <span className="muted"> · line {q.line}</span>
              {q.doc_id ? <p><a href={docHref(mid, q.doc_id, q.chunk)}>{`View source · ${q.filename}, passage ${q.passage}`}</a></p>
                : q.source_name ? <p className="muted">Found in {q.source_name} — a law source, not an uploaded document.</p> : null}
            </li>))}</ul>
        </>)}
    </section>);
}

function WorkPlan({ mid }) {
  const runs = useApi(`/matters/${mid}/runs`, { matter: mid });
  const [sel, setSel] = useState(null);
  const rows = runs.data || [];
  return (
    <div className={`split${sel ? " split--open" : ""}`}>
      <div>
        <ErrorLine error={runs.error} onRetry={runs.reload} />
        {runs.loading ? <Loading /> : rows.length === 0 ? <Empty>No executions yet. Dispatch work from the Overview tab.</Empty> : (
          <table className="table" aria-label="Executions">
            <thead><tr><th scope="col">Execution</th><th scope="col">State</th><th scope="col">Task</th><th scope="col">Started</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.execution_id} aria-selected={sel === r.execution_id} onClick={() => setSel(r.execution_id)}>
                <td><a href={href("run", { rid: r.execution_id })} onClick={(e) => { e.preventDefault(); setSel(r.execution_id); }} className="mono">{r.execution_id}</a></td>
                <td><StatusChip kind="agent" state={r.state} /></td>
                <td title={r.input_task_text}>{r.input_task_text}</td><td>{fmtAgo(r.started_at)}</td>
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

function DraftViewer({ mid, aid, why, onReview, onClose, onDelete = null }) {
  const art = useApi(`/artifacts/${aid}`);
  const src = useApi(`/artifacts/${aid}/sources`);
  const a = art.data;
  return (
    <section className="stack" aria-label={`Draft ${a?.title || aid}`}>
      <ErrorLine error={art.error} onRetry={art.reload} />
      {art.loading ? <Loading /> : a ? (<>
        <div className="prov">
          <span className="prov__title">{a.title}</span><span />
          <span className="chip">{a.review_state}</span>
          <dl className="prov__meta">
            <div><dt>Kind</dt><dd>{a.kind}</dd></div>
            <div><dt>Updated</dt><dd>{fmtDate(a.updated_at)}</dd></div>
            {a.execution_id ? <div><dt>Produced by</dt><dd><a href={href("run", { rid: a.execution_id })}>run {a.execution_id}</a></dd></div> : null}
            {a.review_note ? <div><dt>Review note</dt><dd>{a.review_note}</dd></div> : null}
          </dl>
        </div>
        <pre className="card" style={{ padding: 16, whiteSpace: "pre-wrap" }}>{a.content || "(empty)"}</pre>
        <DraftSources mid={mid} s={src} />
      </>) : null}
      <p>
        <Btn why={why} onClick={async () => { if (await onReview(aid)) art.reload(); }}>Mark reviewed</Btn>{" "}
        {onDelete}{" "}
        <button type="button" className="btn" onClick={onClose}>Back to drafts</button>
      </p>
    </section>
  );
}

function Drafts({ mid, item: open }) {
  const { perms } = useCtx();
  const arts = useApi(`/matters/${mid}/artifacts`, { matter: mid });
  const [st, run] = useCommand();
  // the open draft lives in the URL (UX-5): a source link out and browser Back return to it
  const setOpen = (aid) => { location.hash = aid ? draftHref(mid, aid) : href("workspace", { mid, tab: "drafts" }); };
  const rows = arts.data?.items || [];
  // the review route requires approval.decide (service/documents.review_artifact)
  const why = allowed(perms, "approval.decide") ? "" : "requires approval.decide";
  const review = async (aid) => {
    const r = await run(() => post(`/artifacts/${aid}/review`, { decision: "approve" }));
    arts.reload();
    return r;
  };
  const pick = useSelect();
  const delWhy = allowed(perms, "matter.write") ? "" : "requires matter.write";
  const remove = async (ids) => {
    if (!confirmDelete(ids.length, "draft")) return;
    await run(async () => { for (const id of ids) await del(`/artifacts/${id}`); });
    pick.clear();
    setOpen(null);
    arts.reload();
  };
  return (
    <div className="stack">
      <ErrorLine error={arts.error} onRetry={arts.reload} />
      <CommandError error={st.error} />
      {open ? null : <BulkBar s={pick} why={delWhy} busy={st.busy} onDelete={() => remove([...pick.sel])} />}
      {open ? <DraftViewer mid={mid} aid={open} why={why} onReview={review} onClose={() => setOpen(null)}
          onDelete={<Btn why={delWhy} disabled={st.busy} onClick={() => remove([open])}>Delete</Btn>} />
        : arts.loading ? <Loading /> : rows.length === 0 ? <Empty>No drafts yet. Stage outputs appear in the Work plan tab.</Empty> : (
        <table className="table" aria-label="Drafts">
          <thead><tr><SelectAll ids={rows.map((a) => a.artifact_id)} s={pick} /><th scope="col">Title</th><th scope="col">Kind</th><th scope="col">Review</th><th scope="col">Updated</th><th scope="col">Action</th></tr></thead>
          <tbody>{rows.map((a) => (
            <tr key={a.artifact_id}>
              <SelectCell id={a.artifact_id} label={a.title} s={pick} />
              <td className="title"><b><a href={draftHref(mid, a.artifact_id)}>{a.title}</a></b>
                <span className="id">{a.artifact_id}</span></td>
              <td>{a.kind}</td><td>{a.review_state}</td><td>{fmtAgo(a.updated_at)}</td>
              <td><button type="button" className="btn" onClick={() => setOpen(a.artifact_id)}>Read</button>{" "}
                <Btn why={why} onClick={() => review(a.artifact_id)}>Mark reviewed</Btn>{" "}
                <Btn why={delWhy} disabled={st.busy} onClick={() => remove([a.artifact_id])}>Delete</Btn></td>
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
  const reload = () => { pend.reload(); done.reload(); rej.reload(); };
  return (
    <div className="stack">
      <h2>Waiting on you{pend.data ? ` (${pend.data.length})` : ""}</h2>
      <ErrorLine error={pend.error} onRetry={pend.reload} stale={pend.stale} />
      {pend.loading ? <Loading rows={2} /> : !pend.data ? null : pend.data.length === 0 ? <Empty>Nothing waiting.</Empty>
        : pend.data.map((a) => <ApprovalCard key={a.approval_id} a={a} onDone={reload} />)}
      <h2>Decided</h2>
      <ErrorLine error={done.error || rej.error} onRetry={reload} />
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
            <li key={e.id}>{/* neutral dot: an event is not a "done" state (task.failed drew green) */}
              <time dateTime={e.data?.ts}>{e.data?.ts ? new Date(e.data.ts).toLocaleString("en-NZ") : ""}</time>
              <b>{e.event}</b>{e.data?.task_id ? <span className="id"> {e.data.task_id}</span> : null}
            </li>))}
        </ol>)}
    </div>
  );
}

export function AuditView({ chain, items, allMatters = false, onMore }) {
  return (
    <>
      {chain ? (chain.ok
        ? <p><span className="chip chip--done" data-icon="✓">Chain verified</span> every row hashes to the one before it.</p>
        : <p><span className="chip chip--failed" data-icon="⚠">Chain broken</span> first bad row: <span className="id">{chain.first_bad}</span></p>) : null}
      <table className="table" aria-label="Audit chain">
        <thead><tr><th scope="col">When</th>{allMatters ? <th scope="col">Matter</th> : null}<th scope="col">Actor</th>
          <th scope="col">Action</th><th scope="col">Target</th><th scope="col">Hash</th></tr></thead>
        <tbody>{items.map((r) => (
          <tr key={r.audit_id}><td>{new Date(r.ts).toLocaleString("en-NZ")}</td>
            {allMatters ? <td className="mono">{r.matter_id || "—"}</td> : null}<td>{r.actor}</td><td>{r.action}</td>
            <td className="mono">{r.target}</td><td className="mono">{(r.hash || "").slice(0, 12)}</td></tr>))}</tbody>
      </table>
      {onMore ? <p><button type="button" className="btn" onClick={onMore}>Load more</button></p> : null}
    </>
  );
}

// no mid = every matter (admin oversight, M13.3)
export function Audit({ mid }) {
  const { perms } = useCtx();
  const can = allowed(perms, "audit.read");
  const path = mid ? `/audit?matter_id=${encodeURIComponent(mid)}` : "/audit";
  const au = useApi(can ? path : null, { matter: mid });
  const [more, setMore] = useState({ items: [], next: undefined });
  const [err, setErr] = useState(null);
  useEffect(() => setMore({ items: [], next: undefined }), [au.data]);  // a refetch restarts paging
  if (!can) return <p className="table__empty">🔒 The audit chain needs the audit.read permission.</p>;
  const next = more.next === undefined ? au.data?.next_cursor : more.next;
  const loadMore = async () => {
    try {
      const r = await page(path, next);
      setMore({ items: [...more.items, ...r.items], next: r.next_cursor });
    } catch (x) { setErr(x); }
  };
  return (
    <div className="stack">
      <ErrorLine error={au.error || err} onRetry={() => { setErr(null); au.reload(); }} />
      {au.loading ? <Loading /> : (
        <AuditView chain={au.data?.chain} items={[...(au.data?.items || []), ...more.items]}
          allMatters={!mid} onMore={next ? loadMore : null} />)}
    </div>
  );
}

// the API answers 404 for both "no such matter" and "not a member" — say neither
export function MatterUnavailable() {
  return (
    <section aria-labelledby="ws-h" className="only-note">
      <h1 id="ws-h">Matter not available</h1>
      <p>It does not exist, or you are not a member of it. Ask the matter's owner for access.</p>
      <p><a href={href("board")}>Back to Matters</a></p>
    </section>);
}

export default function Workspace({ mid, tab, item, part }) {
  const m = useApi(`/matters/${mid}`, { matter: mid });
  const panes = { overview: Overview, documents: Documents, evidence: Evidence, workplan: WorkPlan,
    agents: Agents, drafts: Drafts, decisions: Decisions, deadlines: Deadlines, activity: Activity, audit: Audit };
  const { live } = useCtx();
  const Pane = panes[tab] || Overview;
  // even with data on screen: access revoked mid-view must drop the matter, not keep it as "stale"
  if (m.error && [403, 404].includes(m.error.status)) return <MatterUnavailable />;
  if (m.error && !m.data) return <ErrorLine error={m.error} onRetry={m.reload} />;
  if (!m.data) return <Loading />;
  const nPend = m.data.outstanding_approvals || 0;
  return (
    <section aria-labelledby="ws-h">
      <ErrorLine error={m.error} onRetry={m.reload} stale={m.stale} />
      <LiveNote live={live} />
      <MatterHeader m={m.data} mid={mid} />
      <nav className="filters" aria-label="Matter sections">
        {TABS.map(([k, label]) => (
          <a key={k} className={`filter${tab === k ? " filter--on" : ""}`} href={href("workspace", { mid, tab: k })}
            aria-current={tab === k ? "page" : undefined}>{label}
            {k === "decisions" && nPend ?  <span className="pill">{nPend}<span className="sr-only"> waiting on you</span></span> : null}</a>))}
        <a className="filter" href={href("case", { mid })}>Guided view →</a>
      </nav>
      {/* key: a pane's local state (open document, open draft) never follows you into another matter */}
      <Pane key={mid} mid={mid} m={m.data} item={item} part={part} />
      {/* ask about the matter before, during or after any run; key: never carry a thread across matters */}
      <MatterChat key={`chat-${mid}`} mid={mid} />
    </section>
  );
}
