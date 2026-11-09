// S7 Approval Center (05 §7; 08 §1.8): every irreversible act waits here. Cards carry the
// payload, requester, age, and the residual-risk line next to the action. Approve/Reject are
// disabled-with-reason without approval.decide; deciding confirms the named consequence.
import { useState } from "react";
import { post } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { useApi } from "../useApi.js";
import { Btn, Empty, ErrorLine, Loading, allowed, fmtAgo } from "../ui.jsx";
import { CommandError, useCommand } from "./Workspace.jsx";

const CONSEQUENCE = {
  filing: "The filing pack is released for you to file and serve. This cannot be taken back.",
  "matter.close": "The case becomes read-only after closure.",
  review: "The drafted output is accepted and the run continues.",
};

// requests arrive as `info_request:<kind>` (catalog.create_request) — one family for the titles
const family = (kind) => (kind.startsWith("info_request") ? "info" : kind);
export function plainKind(kind, self) {
  const k = family(kind);
  return (self
    ? { filing: "Approve the filing pack", "matter.close": "Close your case", review: "Approve this draft", info: "We need something from you" }
    : { filing: "Filing approval", "matter.close": "Close matter", review: "Review draft", info: "Information request" })[k] || kind;
}

export function ApprovalCard({ a, onDone }) {
  const { perms, mode } = useCtx();
  const self = mode === "self-rep";
  const [note, setNote] = useState("");
  const [answer, setAnswer] = useState("");
  const [st, run] = useCommand();
  const why = allowed(perms, "approval.decide") ? "" : "requires approval.decide";
  const p = a.request_payload || {};
  const consequence = CONSEQUENCE[a.kind] || "This decision is recorded in the audit chain and cannot be undone.";
  const decide = async (verb) => {
    const lead = verb === "approve" ? consequence : "The run stops here and nothing more runs.";
    if (!confirm(`${verb === "approve" ? "Approve" : "Reject"}? ${lead}`)) return;
    const go = verb === "approve" ? () => post(`/approvals/${a.approval_id}/approve`, { note }) : () => post(`/approvals/${a.approval_id}/reject`, { note });
    if (await run(go)) onDone?.();
  };
  const isInfo = a.kind === "info" || !!p.question;
  return (
    <article className="card approval" aria-labelledby={`ap-${a.approval_id}`}>
      <div className="approval__head">
        <span className="approval__kind">⚑ {a.kind}</span>
        <a href={href(self ? "case" : "workspace", { mid: a.matter_id })} className="id">{a.matter_id}</a>
        <span className="muted">requested {fmtAgo(a.requested_at)}</span>
      </div>
      <h2 className="approval__title" id={`ap-${a.approval_id}`}>{plainKind(a.kind, self)}</h2>
      <div className="approval__payload" style={{ whiteSpace: "pre-wrap" }}>
        {p.question || p.result_summary || p.summary || (Object.keys(p).length ? JSON.stringify(p, null, 2) : "No payload.")}
      </div>
      <p className="approval__by">Requested by {a.task_id ? <>stage <span className="id">{a.task_id}</span></> : "the system"}
        {a.execution_id ? <> · run <a href={href("run", { rid: a.execution_id })} className="id">{a.execution_id}</a></> : null}</p>
      {isInfo ? (
        <form onSubmit={async (e) => { e.preventDefault(); if (await run(() => post(`/requests/${a.approval_id}/answer`, { text: answer }))) onDone?.(); }}>
          <label htmlFor={`ans-${a.approval_id}`}>Your answer</label>
          <textarea id={`ans-${a.approval_id}`} rows="2" required value={answer} onChange={(e) => setAnswer(e.target.value)} />
          <div className="approval__actions"><Btn why={why} primary type="submit">Provide</Btn></div>
        </form>
      ) : (<>
        <label htmlFor={`note-${a.approval_id}`}>Note for the record <span className="hint">(optional)</span></label>
        <input id={`note-${a.approval_id}`} type="text" value={note} onChange={(e) => setNote(e.target.value)} />
        <div className="approval__actions">
          <Btn why={why} primary onClick={() => decide("approve")} aria-describedby={`risk-${a.approval_id}`}>Approve</Btn>
          <Btn why={why} onClick={() => decide("reject")}>Reject</Btn>
        </div>
        <p className="approval__risk" id={`risk-${a.approval_id}`}><b>What happens:</b> {consequence}
          {p.residual_risk ? <><br /><b>Residual risk:</b> {p.residual_risk}</> : null}</p>
      </>)}
      <CommandError error={st.error} />
    </article>
  );
}

export default function Approvals() {
  const list = useApi("/approvals?state=pending");
  const rows = list.data?.items || [];
  return (
    <section aria-labelledby="ap-h" className="stack">
      <div className="hdr"><h1 id="ap-h">Approvals</h1><span className="sub">{list.data ? `${rows.length} pending` : ""}</span></div>
      <ErrorLine error={list.error} onRetry={list.reload} />
      {list.loading ? <Loading /> : rows.length === 0
        ? <Empty>Nothing is waiting on you. We will show it here when something is.</Empty>
        : rows.map((a) => <ApprovalCard key={a.approval_id} a={a} onDone={list.reload} />)}
    </section>
  );
}
