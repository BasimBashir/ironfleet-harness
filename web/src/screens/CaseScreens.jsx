// Guided self-rep screens (08 §3 journey map): N1 intake, N2 case home + next-action
// card, N3 timeline, N10 lawyer-now banner (exact 08 §2 copy, role="alert", block in
// self-rep / flag in firm), N9 plain toggle's render rule. Routes: #/case/{mid}/{view}.
// T7 adds N4–N8 (strategy, flaws, hearing pack, debrief, deadlines) in this file.
import { useEffect, useRef, useState } from "react";
import { post, upload } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { useApi } from "../useApi.js";
import { Btn, Empty, ErrorLine, Loading, StatusChip, allowed, fmtAgo, fmtDate, fmtDue } from "../ui.jsx";
import { ApprovalCard } from "./Approvals.jsx";
import { CommandError, useCommand } from "./Workspace.jsx";

// 08 §2 banner copy — byte-exact. Keys are the detector's rule names (lawyer_now.py).
export const LAWYER_NOW_COPY = {
  criminal_exposure: "This may involve criminal charges. A lawyer must handle anything that could lead to criminal charges.",
  family_safety: "This involves the safety or care of children. Family Court matters need a lawyer — and support services may be able to help you now.",
  user_insolvency: "You may need to deal with serious debt or bankruptcy. A lawyer should guide this.",
  claim_above_self_help: "This claim is worth more than the self-help limit. At this amount, the forum expects cases to be run by lawyers, and the risk of losing money is higher.",
  missed_limitation: "The time limit for this claim has passed. Only a lawyer can tell you if there is still a way forward.",
  court_order_against_user: "A court has made an order against you. Get legal advice before you do anything else.",
};
// firm-mode board risk column: the same rules, one short phrase each
export const LAWYER_NOW_SHORT = {
  criminal_exposure: "criminal exposure", family_safety: "children's safety", user_insolvency: "client insolvency",
  claim_above_self_help: "above the self-help limit", missed_limitation: "limitation missed",
  court_order_against_user: "court order against client",
};
const LAWYER_NOW_FOOTER = "Your case stays open. You can keep uploading documents. We stop advising you on this matter until a lawyer is involved.";
const LAWYER_NOW_HELP = "Free help: Community Law Centre, Citizens Advice Bureau, or your local Duty Lawyer.";

// 08 §6 N3: the §3.1 states as fixed plain names (the legal term rides as a glossary chip).
export const STAGE_PLAIN = {
  INTAKE: "Setting up", ASSESS: "Checking your case", STRATEGY: "Planning",
  PRE_ACTION: "Letters before court", DRAFT: "Writing documents", MOOT: "Testing our work",
  APPROVE: "Your approval", FILE_SERVE: "Lodging at court", AWAIT: "Waiting",
  RESPOND: "Replying", HEARING_PREP: "Getting ready for the hearing", COURT: "Your hearing day",
  DEBRIEF: "Telling us what happened", RE_STRATEGY: "New plan", JUDGMENT: "The decision",
  ENFORCE: "Getting results", APPEAL: "Asking for a review", SETTLE: "Settling",
  CLOSED: "Finished",
};
// N2 mini journey (mockup B): the 19 states folded into 8 plain slots, chain order kept
export const JOURNEY_STRIP = [
  ["Setting up", ["INTAKE"]], ["Checking", ["ASSESS"]], ["Planning", ["STRATEGY"]],
  ["Letters & filing", ["PRE_ACTION", "DRAFT", "MOOT", "APPROVE", "FILE_SERVE"]],
  ["Waiting & replying", ["AWAIT", "RESPOND"]], ["Getting ready", ["HEARING_PREP"]],
  ["Court & after", ["COURT", "DEBRIEF", "RE_STRATEGY", "JUDGMENT", "ENFORCE", "APPEAL", "SETTLE"]],
  ["Finished", ["CLOSED"]],
];
export const stripIndex = (stage) => JOURNEY_STRIP.findIndex(([, s]) => s.includes(stage));

const STAGE_WHAT = {
  INTAKE: "We ask a few questions and collect your papers.",
  ASSESS: "We check time limits, conflicts and which court.",
  STRATEGY: "We write the plan and you approve it.",
  PRE_ACTION: "We send a formal letter first — often it settles here.",
  DRAFT: "We write the court documents.",
  MOOT: "We test the documents against likely attacks before anything is filed.",
  APPROVE: "You read and approve what we wrote.",
  FILE_SERVE: "You file the documents at court and serve the other side.",
  AWAIT: "We wait for the other side. This can repeat: we wait → they reply → we respond.",
  RESPOND: "We answer the other side's points.",
  HEARING_PREP: "We build your hearing pack and you rehearse.",
  COURT: "Your hearing day. Bring the pack.",
  DEBRIEF: "Tell us what happened; each hearing adds a round: tell us → new plan.",
  RE_STRATEGY: "We update the plan after what happened.",
  JUDGMENT: "The court's decision arrives.",
  ENFORCE: "We take steps to get what you are owed.",
  APPEAL: "We ask a higher court to review.",
  SETTLE: "The case settles — this can happen from any stage after letters.",
  CLOSED: "The case is finished and archived read-only.",
};

// N10 — 08 §2. Pinned above every self-rep screen while the detector is active;
// in firm mode it renders as the flag the workspace header and Board already show.
export function LawyerNowBanner({ mid }) {
  const { mode } = useCtx();
  const ln = useApi(`/matters/${mid}/lawyer-now`, { matter: mid });
  const self = mode === "self-rep";
  const box = useRef(null);
  const flagged = ln.data?.state === "flagged";
  // 08 §17: takes focus once — per matter and trigger set, not on every screen
  const once = `ironfleet.lnfocus.${mid}.${(ln.data?.triggers || []).join(",")}`;
  useEffect(() => {
    if (self && flagged && !sessionStorage.getItem(once)) { sessionStorage.setItem(once, "1"); box.current?.focus(); }
  }, [self, flagged, once]);
  if (!flagged) return null;
  const lines = (ln.data.triggers || []).map((t) => LAWYER_NOW_COPY[t]).filter(Boolean);
  if (self) {
    return (
      <div className="banner banner--block" role="alert" tabIndex={-1} ref={box}>
        <p className="banner__title">⛔ Stop — you need a lawyer for this</p>
        {lines.length === 1 ? <p>{lines[0]}</p> : <ul>{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
        <p>{LAWYER_NOW_FOOTER}</p>
        <p className="muted">{LAWYER_NOW_HELP}</p>
        {/* no API to attach a lawyer yet (M10 accounts): disabled-with-reason, never a dead button */}
        <p><Btn primary why="Not available yet — your lawyer can contact us directly">I have a lawyer now</Btn></p>
      </div>
    );
  }
  return (
    <div className="banner banner--flag" role="status">
      <p className="banner__title">⛔ Lawyer-now flag</p> — {lines.join(" ")} You decide; nothing is gated in firm mode.
    </div>
  );
}

// N9 — 08 §12: artifacts carry no plain field today, so the toggle is a render-layer
// label; the honest fallback is shown when a document asks for a plain version.
export function PlainNote({ artifact, plain }) {
  if (!plain || !artifact) return null;
  if (artifact.plain) return <p className="muted">Plain version shown.</p>;
  return <p className="muted" role="note">Plain version not available for this document.</p>;
}

// N1 — 08 §4: one question at a time, server-driven; uploads; "what we still need".
function Intake({ mid }) {
  const { perms } = useCtx();
  const q = useApi(`/matters/${mid}/intake/questions`, { matter: mid });
  const facts = useApi(`/matters/${mid}/dossier/facts`, { matter: mid });
  const docs = useApi(`/matters/${mid}/documents`, { matter: mid });
  const [answer, setAnswer] = useState("");
  const [st, run, reset] = useCommand();
  const file = useRef(null);
  const canWrite = allowed(perms, "matter.write");
  const why = canWrite ? "" : "requires matter.write";
  const cur = q.data?.current;
  const qa = useRef(null);
  // the next question landed: clear "pending…" and keep focus on the active question (08 §17)
  useEffect(() => { reset(); qa.current?.focus(); }, [cur?.id]);
  const missing = facts.data?.missing || [];
  const submit = async (e) => {
    e.preventDefault();
    if (await run(() => post(`/matters/${mid}/intake/answers`, { question_id: cur.id, answer }))) {
      setAnswer("");
      q.reload(); facts.reload();
    }
  };
  const onFiles = async (e) => {
    for (const f of e.target.files) await run(() => upload(`/matters/${mid}/documents`, f));
    e.target.value = "";
    docs.reload();
  };
  return (
    <section aria-labelledby="intake-h" className="stack">
      <div className="hdr"><h1 id="intake-h">Setting up your case</h1>
        <span className="sub" aria-live="polite">
          {q.data ? (cur ? `Section ${q.data.sections_done + 1} of ${q.data.sections_total}` : "All questions answered") : ""}
        </span></div>
      <ErrorLine error={q.error || facts.error} onRetry={() => { q.reload(); facts.reload(); }} />
      {q.loading ? <Loading /> : !cur ? (
        <div className="card qcard"><h2>All questions answered</h2>
          <p>The next step is on your case home. <a href={href("case", { mid, view: "home" })}>Go to my case</a></p></div>
      ) : (
        <form className="card qcard" onSubmit={submit} aria-labelledby="q-h">
          <h2 id="q-h">{cur.text}</h2>
          <fieldset>
            <label htmlFor="q-a">Your answer</label>
            <textarea id="q-a" ref={qa} rows="3" required value={answer} onChange={(e) => setAnswer(e.target.value)}
              aria-describedby={st.error ? "q-err" : undefined} autoFocus />
          </fieldset>
          <p><Btn why={why} primary type="submit" disabled={st.busy || st.pending}>
            {st.busy ? "Saving…" : st.pending ? "Saved — checking the next question…" : "Continue"}</Btn></p>
          <CommandError error={st.error} />
          {st.error ? <p className="field-error" id="q-err" role="alert">We couldn't save your last answer. Try again — nothing is lost.</p> : null}
        </form>)}
      {canWrite ? (
        <div className="card qcard">
          <h2>Upload every paper, email or photo about this problem</h2>
          <p className="hint">You can add more later. Each upload confirms what it was read as.</p>
          <input ref={file} type="file" multiple onChange={onFiles} className="sr-only" id="intake-up" tabIndex={-1} aria-hidden="true" />
          <p><button type="button" className="btn" onClick={() => file.current?.click()}>Choose files to upload</button>
            {st.busy ? <span className="muted" role="status"> Uploading…</span> : null}</p>
          <CommandError error={st.error} />
          {(docs.data?.items || []).length > 0 ? (
            <ul>{docs.data.items.map((d) => (
              <li key={d.doc_id}><b>{d.filename}</b> <span className="id">{d.doc_id}</span> —{" "}
                <span className={`chip chip--${d.ingest_status === "ingested" ? "verified" : "unverified"}`}
                  data-icon={d.ingest_status === "ingested" ? "✓" : "?"}>
                  {d.ingest_status === "ingested" ? "Read and ingested" : "Not ingested yet"}</span></li>))}</ul>) : null}
        </div>) : null}
      {cur && missing.length > 0 ? (  /* same question set: with none left, a lagging facts read is stale */
        <div className="card qcard">
          <h2>What we still need</h2>
          <ul>{missing.map((m) => <li key={m}><span className="id">{m}</span> — answer the question above to fill this in.</li>)}</ul>
        </div>) : null}
    </section>
  );
}

// N2 — 08 §5: the one next action, why, by when, miss-consequence; the rest of the
// waiting list; mini status; last update. Ordering is the server's — no client re-sort.
function CaseHome({ mid }) {
  const { perms, plain } = useCtx();
  const m = useApi(`/matters/${mid}`, { matter: mid });
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const na = useApi(`/matters/${mid}/next-actions`, { matter: mid });
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  const apr = useApi(`/matters/${mid}/approvals?state=pending`, { matter: mid });
  const [note, setNote] = useState("");
  const [st, run, reset] = useCommand();
  const canWrite = allowed(perms, "matter.write");
  const why = canWrite ? "" : "requires matter.write";
  const items = na.data?.items || [];
  const first = items[0];
  const overdue = (dl.data?.items || []).find((d) => d.status === "overdue");
  const next = (dl.data?.items || []).filter((d) => d.status !== "met")
    .sort((a, b) => (a.due || "").localeCompare(b.due || ""))[0];
  const complete = async (aid) => {
    if (await run(() => post(`/matters/${mid}/next-actions/${aid}/complete`, { note }))) { setNote(""); na.reload(); reset(); }
  };
  if (m.error) return <ErrorLine error={m.error} onRetry={m.reload} />;
  if (!m.data) return <Loading />;
  const stage = lc.data?.stage;
  return (
    <section aria-labelledby="case-h" className="stack">
      <div className="hdr"><h1 id="case-h">{m.data.title || mid}</h1>
        <span className="sub"><span className="id">{mid}</span>
          {" · You are here: "}<b>{stage ? STAGE_PLAIN[stage] || stage.toLowerCase() : "Not started"}</b>
          {next ? ` · next date ${fmtDue(next.due)}` : ""}</span>
        <span className="act"><StatusChip state={m.data.state} /></span></div>
      {overdue ? (
        <div className="banner banner--flag" role="alert">
          <p className="banner__title">⚠ A deadline was missed: {overdue.what}</p>
          {overdue.due ? <span>due {fmtDue(overdue.due)} · </span> : null}
          {overdue.missed_consequence || "We will re-plan the case with you."}
        </div>) : null}
      {na.loading ? <Loading /> : !first ? (
        <div className="card qcard"><h2>Nothing needs you right now</h2>
          <p>We will tell you when something does{next ? ` — next date ${fmtDue(next.due)}` : ""}.</p></div>
      ) : (
        <article className="card nextcard" aria-labelledby="na-h">
          <p className="nextcard__lbl">Do this now</p>
          <h2 id="na-h">{first.what}</h2>
          <dl className="facts">
            {first.why ? <div><dt>Why</dt><dd>{first.why}</dd></div> : null}
            {first.due ? <div><dt>By</dt><dd><b>{fmtDue(first.due)}</b></dd></div> : null}
            {first.missed_consequence ? <div><dt>If you miss it</dt><dd id="na-risk">{first.missed_consequence}</dd></div> : null}
          </dl>
          <label htmlFor="na-note">Note for the record <span className="hint">(optional)</span></label>
          <input id="na-note" type="text" value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="approval__actions">
            <Btn why={why} primary onClick={() => complete(first.proposal_id)}
              aria-describedby={first.missed_consequence ? "na-risk" : undefined}>Mark done</Btn>
          </div>
          <CommandError error={st.error} />
          {st.pending ? <p className="muted" role="status">Done — updating…</p> : null}
        </article>)}
      {(apr.data?.length || 0) > 0 ? (
        <div className="card qcard"><h2>Also waiting on you ({apr.data.length})</h2>
          {apr.data.slice(0, 5).map((a) => <ApprovalCard key={a.approval_id} a={a} onDone={apr.reload} />)}</div>) : null}
      {items.length > 1 ? (
        <div className="card qcard"><h2>Also on your list</h2>
          <ul>{items.slice(1).map((it) => (
            <li key={it.proposal_id}><b>{it.what}</b>{it.why ? <span className="muted"> — {it.why}</span> : null}
              {it.due ? <span className="muted"> · {fmtDue(it.due)}</span> : null}</li>))}</ul></div>) : null}
      <ol className="journey" aria-label="Your journey">
        {JOURNEY_STRIP.map(([label], i) => {
          const at = stripIndex(stage);
          return <li key={label} className={i < at ? "done" : i === at ? "now" : undefined}
            aria-current={i === at ? "step" : undefined}>{i < at ? "✓ " : ""}{label}</li>;
        })}
      </ol>
      <p className="foot">Last update: {fmtAgo(m.data.updated_at || m.data.created_at)}
        {plain ? " · Reading level: Plain" : ""} · <a href={href("case", { mid, view: "timeline" })}>See the whole journey</a></p>
    </section>
  );
}

// N3 — 08 §6: the journey as an ordered list (the list is canonical; the graphic is
// decoration). "Now" node highlighted with word + icon; loops annotated, not cycled.
function Timeline({ mid }) {
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const order = Object.keys(STAGE_PLAIN);
  const cur = lc.data?.stage;
  const curIdx = cur ? order.indexOf(cur) : -1;
  return (
    <section aria-labelledby="tl-h">
      <div className="hdr"><h1 id="tl-h">Your case, step by step</h1>
        <span className="sub">{cur ? <>You are here: <b>{STAGE_PLAIN[cur]}</b> ({cur.replace(/_/g, " ").toLowerCase()})</> : "Not started"}</span></div>
      <ErrorLine error={lc.error} onRetry={lc.reload} />
      {lc.loading ? <Loading /> : (
        <ol aria-label="Case stages, in order" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {order.map((s, i) => {
            const state = i < curIdx ? "done" : i === curIdx ? "step" : "todo";
            const when = i === curIdx ? lc.data?.entered_at : (lc.data?.history || []).filter((h) => h.to === s).pop()?.ts;
            return (
              <li key={s} data-state={state} aria-current={state === "step" ? "step" : undefined}
                style={{ borderLeft: `4px solid ${state === "done" ? "var(--s-done)" : state === "step" ? "var(--accent)" : "var(--rule)"}`, padding: "6px 0 6px 14px", color: state === "todo" ? "var(--muted)" : undefined }}>
                <b>{STAGE_PLAIN[s]}</b> <span className="id">({s.replace(/_/g, " ").toLowerCase()})</span>
                {when ? <span className="muted"> · {fmtDate(when)}</span> : null}
                <small style={{ display: "block", color: "var(--muted)" }}>{STAGE_WHAT[s]}</small>
              </li>);
          })}
        </ol>)}
      <p className="foot">A case can repeat: after “Waiting” we may wait → they reply → we respond → we wait. Each hearing adds a debrief round.</p>
    </section>
  );
}

// -- T7: N4–N8 ---------------------------------------------------------------------

const SEVERITY = { critical: "⛔ Critical", material: "⚠ Material", minor: "· Minor" };
export const DEADLINE_WORD = { ok: "OK", due_soon: "Due soon", overdue: "Overdue ⚠", unknown: "Date unknown" };

// 08 §8: the verdict is never silent about open flaws; critical/material open = gate blocked
export function flawVerdict(rows) {
  if (!rows.length) return null;
  const open = rows.filter((f) => f.status === "open");
  if (!open.length) return "Passed";
  if (open.some((f) => f.severity === "critical" || f.severity === "material"))
    return "Not passed — open flaws must be fixed before anything is sent";
  return "Passed with open flaws";
}

// 08 §10: neutral text pair — what we predicted, what the court said
const noDot = (s) => String(s ?? "").replace(/\.\s*$/, "");

export function predictionLine(d) {
  const c = d.court_said || {};
  const orders = (c.orders || []).length ? ` Orders: ${noDot([].concat(c.orders).join("; "))}.` : "";
  return `We predicted: ${noDot(d.claim)}. The court said: ${noDot(c.judge_said) || "nothing recorded"}.${orders}`;
}

function StrategyDiff({ mid, v, against }) {
  const d = useApi(`/matters/${mid}/strategy/${v}/diff?against=${against}`, { matter: mid });
  if (d.loading) return <p className="muted" role="status">Comparing versions…</p>;
  if (d.error) return <ErrorLine error={d.error} onRetry={d.reload} />;
  const { changes = [], reasons = [], failed_predictions: failed = [] } = d.data || {};
  return (
    <div className="card qcard" aria-live="polite">
      <h3>What changed from version {against} to {v}</h3>
      {changes.length ? <ul>{changes.map((c, i) => (
        <li key={i}><b>{c.op === "added" ? "＋ Added" : "－ Removed"}:</b> {c.action}</li>))}</ul>
        : <p className="muted">No steps changed.</p>}
      {reasons.length ? <p>Why: {reasons.join(" ")}</p> : null}
      {failed.map((f) => <p key={f.prediction_id}>We predicted: {noDot(f.claim)}. The court said: {noDot(f.actual)}.</p>)}
    </div>
  );
}

// N4 — 08 §7. One decision surface: approving a version happens on the S7 approval card.
function Strategy({ mid }) {
  const s = useApi(`/matters/${mid}/strategy`, { matter: mid });
  const pr = useApi(`/matters/${mid}/predictions`, { matter: mid });
  const [pick, setPick] = useState(null);
  const vs = s.data?.items || [];
  const latest = vs[vs.length - 1];
  return (
    <section aria-labelledby="st-h" className="stack">
      <div className="hdr"><h1 id="st-h">Your plan</h1></div>
      <ErrorLine error={s.error} onRetry={s.reload} />
      {s.loading ? <Loading /> : !latest ? <Empty>Your plan appears after we finish checking your case.</Empty> : (
        <article className="card qcard">
          <h2>Plan version {latest.version} — made {fmtDate(latest.ts)}</h2>
          {latest.why_changed ? <p>Why it changed: {latest.why_changed}</p> : null}
          <h3>The steps</h3>
          <ol>{(latest.next_actions || []).map((a, i) => <li key={i}>{typeof a === "string" ? a : a.what || JSON.stringify(a)}</li>)}</ol>
          <p className="muted">To approve or send back a new version, use the approval card on your case home.</p>
        </article>)}
      {vs.length > 1 ? (
        <div className="card qcard"><h2>Every version</h2>
          <ul>{vs.map((x, i) => (
            <li key={x.version}><b>Version {x.version}</b> — {fmtDate(x.ts)}
              {i > 0 ? <> <button type="button" className="btn" onClick={() => setPick([x.version, vs[i - 1].version])}>
                See what changed from version {vs[i - 1].version}</button></> : null}</li>))}</ul>
          {pick ? <StrategyDiff mid={mid} v={pick[0]} against={pick[1]} /> : null}
        </div>) : null}
      {(pr.data?.items || []).length ? (
        <div className="card qcard"><h2>What we predicted</h2>
          <ul>{pr.data.items.map((p) => (
            <li key={p.prediction_id}>{p.claim} <span className="muted">(plan version {p.strategy_version}) —{" "}
              {p.resolved ? "✓ checked against the court" : "… waiting for the court"}</span></li>))}</ul></div>) : null}
    </section>
  );
}

// N5 — 08 §8: verdict, found/fixed/remaining by class, severity word + icon.
function Flaws({ mid }) {
  const f = useApi(`/matters/${mid}/flaws`, { matter: mid });
  const rows = f.data?.items || [];
  const verdict = flawVerdict(rows);
  const open = rows.filter((x) => x.status === "open");
  const byClass = rows.reduce((m, x) => ((m[x.class || "other"] ||= []).push(x), m), {});
  return (
    <section aria-labelledby="fl-h" className="stack">
      <div className="hdr"><h1 id="fl-h">Testing our work</h1></div>
      <ErrorLine error={f.error} onRetry={f.reload} />
      {f.loading ? <Loading /> : !verdict ? <Empty>Nothing is being tested right now.</Empty> : (<>
        <div className={`card qcard${open.length ? " banner banner--flag" : ""}`}>
          <h2>{verdict}</h2>
          <p>Found {rows.length} · fixed {rows.length - open.length} · still open {open.length}</p>
          {open.length ? <><h3>Still open</h3><ul>{open.map((x) => (
            <li key={x.flaw_id}><b>{SEVERITY[x.severity] || x.severity}</b> — {x.detail || x.class}</li>))}</ul></> : null}
        </div>
        <details className="card qcard"><summary>Full list of what we found</summary>
          {Object.entries(byClass).map(([cls, xs]) => (
            <div key={cls}><h3>{cls}</h3><dl>{xs.map((x) => (<div key={x.flaw_id}>
              <dt>{SEVERITY[x.severity] || x.severity} · {x.status === "open" ? "open" : "fixed"}</dt>
              <dd>{x.detail || "—"}{x.doc ? <span className="id"> ({x.doc})</span> : null}</dd></div>))}</dl></div>))}
        </details></>)}
    </section>
  );
}

// N6 — 08 §9: the pack projection + rehearsal start (rehearsal Q&A resource is not in the API yet).
function Hearing({ mid }) {
  const { perms } = useCtx();
  const h = useApi(`/matters/${mid}/hearing-pack`, { matter: mid });
  const [st, run] = useCommand();
  const why = allowed(perms, "matter.write") ? "" : "requires matter.write";
  const sec = h.data?.sections || {};
  return (
    <section aria-labelledby="hp-h" className="stack">
      <div className="hdr"><h1 id="hp-h">Getting ready for the hearing</h1></div>
      <ErrorLine error={h.error} onRetry={h.reload} />
      {h.loading ? <Loading /> : !sec.strategy && !(sec.deadlines || []).length ? (
        <Empty>Your hearing pack appears once the hearing date is set.</Empty>) : (<>
        <div className="card qcard"><h2>Checklist</h2>
          <ul>{(h.data.checklist || []).map((c) => (
            <li key={c.item}>{c.ok ? "✓ Done" : "✗ Not yet"} — {c.item}</li>))}</ul></div>
        {sec.strategy ? <div className="card qcard"><h2>Your plan for the day (version {sec.strategy.version})</h2>
          <ol>{(sec.strategy.next_actions || []).map((a, i) => <li key={i}>{typeof a === "string" ? a : a.what || JSON.stringify(a)}</li>)}</ol></div> : null}
        {(sec.open_flaws || []).length ? <div className="card qcard"><h2>Risks to be ready for</h2>
          <ul>{sec.open_flaws.map((x) => <li key={x.flaw_id}><b>{SEVERITY[x.severity] || x.severity}</b> — {x.detail}</li>)}</ul></div> : null}
      </>)}
      <div className="card qcard"><h2>Practise the hearing</h2>
        <p>A practice run: the simulated judge asks, you answer. Nothing here is a real court.</p>
        <p><Btn why={why} primary disabled={st.busy} onClick={async () => { if (await run(() => post(`/matters/${mid}/mock-hearing`))) h.reload(); }}>
          {st.busy ? "Starting…" : "Start a practice hearing"}</Btn></p>
        <CommandError error={st.error} />
        {st.pending ? <p className="muted" role="status">Practice hearing started — it appears below when it begins.</p> : null}
        {(h.data?.rehearsals || []).length ? <ul>{h.data.rehearsals.map((r) => (
          <li key={r.execution_id}><span className="id">{r.execution_id}</span> — {fmtDate(r.started_at)} <StatusChip state={r.state} /></li>))}</ul> : null}
      </div>
    </section>
  );
}

// 08 §17 / mockup B: debrief questions grouped by topic; ids the server adds later land in the last group
const DEBRIEF_GROUPS = [["The hearing", ["date"]], ["What the judge said", ["judge_said", "orders"]],
  ["Dates and papers", ["next_date", "documents_handed"]]];
export function debriefGroups(qs) {
  const known = DEBRIEF_GROUPS.flatMap(([, ids]) => ids);
  return DEBRIEF_GROUPS.map(([legend, ids], i) => {
    const last = i === DEBRIEF_GROUPS.length - 1;
    return [legend, qs.filter((q) => ids.includes(q.id) || (last && !known.includes(q.id))), last];
  });
}

// N7 — 08 §10: guided questions, uploads, honest diff back. Answers survive errors and reloads.
function Debrief({ mid }) {
  const { perms } = useCtx();
  const q = useApi(`/matters/${mid}/debrief/questions`, { matter: mid });
  const key = `ironfleet.debrief.${mid}`;
  const [ans, setAns] = useState(() => JSON.parse(sessionStorage.getItem(key) || "{}"));
  const [docIds, setDocIds] = useState([]);
  const [st, run] = useCommand();
  const [result, setResult] = useState(null);
  const file = useRef(null);
  useEffect(() => { sessionStorage.setItem(key, JSON.stringify(ans)); }, [key, ans]);
  const canWrite = allowed(perms, "matter.write");
  const why = !canWrite ? "requires matter.write" : !ans.date ? "add the hearing date first" : "";
  const submit = async (e) => {
    e.preventDefault();
    if (why) return;  // Enter in the date input submits the form; the reason is already on screen
    const r = await run(() => post(`/matters/${mid}/debrief`, { answers: ans, doc_ids: docIds }));
    if (r) { setResult(r.data); setAns({}); sessionStorage.removeItem(key); }
  };
  const onFiles = async (e) => {
    for (const f of e.target.files) {
      const r = await run(() => upload(`/matters/${mid}/documents`, f));
      if (r?.data?.doc_id) setDocIds((d) => [...d, r.data.doc_id]);
    }
    e.target.value = "";
  };
  return (
    <section aria-labelledby="db-h" className="stack">
      <div className="hdr"><h1 id="db-h">Tell us what happened at court</h1></div>
      <ErrorLine error={q.error} onRetry={q.reload} />
      {q.loading ? <Loading /> : (
        <form onSubmit={submit}>
          {debriefGroups(q.data || []).map(([legend, qs, last]) => (
            <fieldset key={legend} className="card qcard">
              <legend>{legend}</legend>
              {qs.map((x) => {
                const props = { id: `db-${x.id}`, value: ans[x.id] || "",
                  onChange: (e) => setAns((a) => ({ ...a, [x.id]: e.target.value })) };
                return (
                  <p key={x.id}><label htmlFor={props.id}>{x.text}{x.id === "date" ? " (needed)" : ""}</label>
                    {x.id === "date" || x.id === "next_date" ? <input type="text" {...props} /> : <textarea rows="2" {...props} />}</p>);
              })}
              {last ? (
                <div className="drop">
                  <input ref={file} type="file" multiple onChange={onFiles} className="sr-only" id="db-up" tabIndex={-1} aria-hidden="true" />
                  <button type="button" className="btn" onClick={() => file.current?.click()}>Upload the minute or order</button>
                  <p className="hint">Photograph them if you have no scanner.{docIds.length ? ` ${docIds.length} uploaded.` : ""}</p>
                </div>) : null}
            </fieldset>))}
          <p><Btn why={why} primary type="submit" disabled={st.busy}>{st.busy ? "Sending…" : "Tell us what happened"}</Btn>
            {" "}<span className="hint">Your answers save as you type.</span></p>
          <CommandError error={st.error} />
        </form>)}
      {result ? (
        <div className="card diff" aria-live="polite"><h2>What we predicted, and what happened</h2>
          {(result.diff || []).length ? <ul>{result.diff.map((d) => <li key={d.prediction_id}>{predictionLine(d)}</li>)}</ul>
            : <p>No open predictions to compare.</p>}
          <p className="muted">Next: we update your plan. You will see the new version under “Your plan”.</p></div>) : null}
    </section>
  );
}

// N8 — 08 §11: list is primary; status word + icon; question a date, never edit it.
function DeadlineRow({ mid, d }) {
  const { perms } = useCtx();
  const [q, setQ] = useState("");
  const [sent, setSent] = useState(false);
  const [st, run] = useCommand();
  const why = allowed(perms, "matter.write") ? "" : "requires matter.write";
  const ask = async (e) => {
    e.preventDefault();
    setSent(false);
    if (await run(() => post(`/matters/${mid}/requests`, { kind: "info", question: `Deadline "${d.what}" (${d.due}): ${q}` }))) { setQ(""); setSent(true); }
  };
  return (
    <li className="card qcard">
      <p><b>⏱ {d.what}</b> — {fmtDue(d.due)} · <b>{DEADLINE_WORD[d.status] || d.status}</b></p>
      {d.missed_consequence ? <p>If you miss this date: {d.missed_consequence}</p> : null}
      <details><summary>How we worked this out</summary>
        <p>{d.rule || "—"}{d.source ? <span className="muted"> · {d.source}</span> : null}</p></details>
      <details><summary>Something looks wrong?</summary>
        <form onSubmit={ask}>
          <label htmlFor={`dq-${d.deadline_id}`}>What looks wrong about this date?</label>
          <textarea id={`dq-${d.deadline_id}`} rows="2" required value={q} onChange={(e) => setQ(e.target.value)} />
          <p><Btn why={why} type="submit" disabled={st.busy}>Ask the case manager</Btn></p>
          <CommandError error={st.error} />
          {sent ? <p className="muted" role="status">Sent — we will check it and answer.</p> : null}
        </form></details>
    </li>
  );
}

// the kernel computes `due` from the service date; the operator never types a due date
function AddDeadline({ mid, onAdded }) {
  const { perms } = useCtx();
  const [f, setF] = useState({ what: "", kind: "filing", service_date: "", days: "" });
  const [st, run] = useCommand();
  const why = allowed(perms, "matter.write") ? "" : "requires matter.write";
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const add = async (e) => {
    e.preventDefault();
    const body = { what: f.what, kind: f.kind, service_date: f.service_date };
    if (f.days !== "") body.days = Number(f.days);
    if (await run(() => post(`/matters/${mid}/deadlines`, body))) { setF({ ...f, what: "", days: "" }); onAdded(); }
  };
  return (
    <details className="card"><summary>Add a date</summary>
      <form onSubmit={add} className="stack">
        <label htmlFor="dl-what">What is due</label>
        <input id="dl-what" required value={f.what} onChange={set("what")} />
        <label htmlFor="dl-kind">Kind</label>
        <select id="dl-kind" value={f.kind} onChange={set("kind")}>
          <option value="filing">Court filing</option><option value="statutory_demand">Statutory demand</option>
          <option value="appeal">Appeal</option><option value="settlement">Settlement milestone</option></select>
        <label htmlFor="dl-svc">Date served</label>
        <input id="dl-svc" type="date" required value={f.service_date} onChange={set("service_date")} />
        <label htmlFor="dl-days">Working days (filing / settlement)</label>
        <input id="dl-days" type="number" min="0" value={f.days} onChange={set("days")} />
        <p><Btn why={why} type="submit" disabled={st.busy}>Add date</Btn></p>
        <CommandError error={st.error} />
      </form></details>
  );
}

// N8 — also the firm workspace's Deadlines tab (there the matter header owns the h1)
export function Deadlines({ mid }) {
  const { mode } = useCtx();
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  const rows = dl.data?.items || [];
  return (
    <section aria-labelledby="dl-h" className="stack">
      {mode === "self-rep" ? <div className="hdr"><h1 id="dl-h">Your dates</h1></div> : <h2 id="dl-h">Deadlines</h2>}
      <ErrorLine error={dl.error} onRetry={dl.reload} stale={dl.stale} />
      <AddDeadline mid={mid} onAdded={dl.reload} />
      {dl.loading ? <Loading /> : !rows.length ? <Empty>No deadlines yet. They appear when your plan is approved.</Empty> : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((d) => <DeadlineRow key={d.deadline_id} mid={mid} d={d} />)}</ul>)}
    </section>
  );
}

const VIEWS = { home: CaseHome, intake: Intake, timeline: Timeline, plan: Strategy, testing: Flaws,
  hearing: Hearing, debrief: Debrief, dates: Deadlines };
export const NAV = [["home", "Case home"], ["intake", "Set up my case"], ["timeline", "Journey"], ["plan", "Plan"],
  ["testing", "Testing"], ["dates", "Dates"], ["hearing", "Hearing"], ["debrief", "After court"]];

export default function CaseScreens({ mid, view }) {
  const { mode } = useCtx();
  const Pane = VIEWS[view] || CaseHome;
  if (mode !== "self-rep") {
    return (
      <section aria-labelledby="case-h">
        <div className="hdr"><h1 id="case-h">My case</h1></div>
        <div className="only-note">The guided view is for self-represented mode.
          Open the <a href={href("workspace", { mid })}>workspace</a> for the firm view.</div>
      </section>
    );
  }
  return (
    <div>
      <LawyerNowBanner mid={mid} />
      <nav className="filters" aria-label="Case sections" style={{ marginBottom: 14 }}>
        {NAV.map(([v, label]) => (
          <a key={v} className={`filter${(view || "home") === v ? " filter--on" : ""}`} href={href("case", { mid, view: v })}
            aria-current={(view || "home") === v ? "page" : undefined}>{label}</a>))}
      </nav>
      <Pane mid={mid} />
    </div>
  );
}
