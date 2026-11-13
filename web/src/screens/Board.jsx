// S2 Matter Board (05 §2; mockup B): portfolio table, "Needs you" loudest, live via the
// board SSE channel, j/k + Enter. Firm-only (§9A.2): self-rep sees a pointer to its case.
import { useEffect, useState } from "react";
import { del, page } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { useApi } from "../useApi.js";
import { BulkBar, Btn, Empty, ErrorLine, LiveNote, Loading, SelectAll, SelectCell, StatusChip, allowed, confirmDelete,
  fmtAgo, fmtDate, fmtTokens, useSelect } from "../ui.jsx";
import { plainKind } from "./Approvals.jsx";
import { LAWYER_NOW_SHORT } from "./CaseScreens.jsx";
import { CommandError, nextDeadline, orGap, stageName, useCommand } from "./Workspace.jsx";

const FILTERS = [["", "All"], ["running", "Running"], ["review_required", "Review"], ["blocked", "Blocked"]];

// shortcut: three reads per row (stage, next deadline, lawyer-now) — fine for a firm's
// open matters on loopback; fold them into the matter row if boards pass ~50 rows
function RowExtras({ mid, children }) {
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  const ln = useApi(`/matters/${mid}/lawyer-now`, { matter: mid });
  return children({ lc, dl, ln });
}

// 05 §2: "Waiting on you" rows sort ahead; otherwise the server's order stands
export const boardOrder = (rows) =>
  [...rows].sort((a, b) => (b.state === "waiting_on_you") - (a.state === "waiting_on_you"));

const excerpt = (p = {}) => {
  const s = String(p.question || p.summary || p.result_summary || "");
  return s.length > 140 ? `${s.slice(0, 139)}…` : s;
};

// The human actions the server holds open: pending approvals, checkpoints and information
// requests (GET /approvals?state=pending — authz-filtered there). Never inferred from a slow agent.
// `runs`: matters the server marks waiting_on_you with no approval row — a run (e.g. paused) waits for a person.
export function WaitingOnYou({ items, runs = [], more = false, titles = {}, loading = false, error = null, onRetry }) {
  const n = items ? `${items.length + runs.length}${more ? "+" : ""}` : "";
  return (
    <section className="card waiting" aria-labelledby="wait-h">
      <h2 id="wait-h">⚑ Waiting on you{items ? <span className="muted"> · {n}</span> : null}</h2>
      <ErrorLine error={error} onRetry={onRetry} stale={!!items} />
      {loading ? <Loading rows={2} /> : !items ? null : items.length + runs.length === 0 ? (
        <p className="muted">Nothing is waiting on you. Approvals, checkpoints and information requests land here.</p>
      ) : (
        <ul className="rows waitlist">
          {runs.map((m) => (
            <li key={m.matter_id}>
              <a href={href("workspace", { mid: m.matter_id, tab: "workplan" })}>
                <b>A run is waiting — resume or cancel</b>
                <span>{m.title || m.matter_id}</span>
                <span className="muted">in the Work plan</span>
              </a>
            </li>))}
          {items.slice(0, 5).map((a) => (
            <li key={a.approval_id}>
              <a href={href("workspace", { mid: a.matter_id, tab: "decisions" })}>
                <b>{plainKind(a.kind, false)}</b>
                <span>{titles[a.matter_id] || a.matter_id}</span>
                <span className="muted">requested {fmtAgo(a.requested_at)}</span>
              </a>
              {excerpt(a.request_payload) ? <p className="muted">{excerpt(a.request_payload)}</p> : null}
            </li>))}
        </ul>)}
      {items && (items.length > 5 || more) ? <p><a href={href("approvals")}>All {n} in Approvals →</a></p> : null}
    </section>
  );
}

export default function Board() {
  const { mode, perms, live } = useCtx();
  const [state, setState] = useState("");
  const [sel, setSel] = useState(0);
  // 200 = the API's page cap; past it, "Load more" walks next_cursor (same pattern as Audit)
  const path = `/matters?limit=200${state ? `&state=${state}` : ""}`;
  const list = useApi(path);
  const needs = useApi("/matters?limit=200&state=waiting_on_you");
  const pend = useApi(mode === "self-rep" ? null : "/approvals?state=pending");
  const [more, setMore] = useState({ items: [], next: undefined });
  useEffect(() => setMore({ items: [], next: undefined }), [list.data]);  // a refetch restarts paging
  const next = more.next === undefined ? list.data?.next_cursor : more.next;
  const rows = boardOrder([...(list.data?.items || []), ...more.items]);
  const nNeeds = `${needs.data?.items?.length ?? 0}${needs.data?.next_cursor ? "+" : ""}`;
  const nRunning = rows.filter((m) => m.state === "running").length;
  const titles = Object.fromEntries([...(needs.data?.items || []), ...rows].map((m) => [m.matter_id, m.title || m.matter_id]));
  const pick = useSelect();
  const [st, run] = useCommand();
  const why = allowed(perms, "user.admin") ? "" : "requires user.admin";
  const remove = async (ids) => {
    if (!confirmDelete(ids.length, "matter")) return;
    await run(async () => { for (const id of ids) await del(`/matters/${id}`); });
    pick.clear();
    list.reload();
    needs.reload();
    pend.reload();
  };
  const loadMore = () => run(async () => {
    const r = await page(path, next);
    setMore({ items: [...more.items, ...r.items], next: r.next_cursor });
  });

  useEffect(() => { setSel(0); }, [state]);

  if (mode === "self-rep") {
    return (
      <div className="only-note">The Matter Board is a firm screen. In self-represented mode you
        work from your case home. <a href={href("new")}>Start a new case</a></div>);
  }

  const open = (m) => { location.hash = href("workspace", { mid: m.matter_id }); };
  const onKey = (e) => {
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, rows.length - 1)); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter" && rows[sel]) open(rows[sel]);
  };

  return (
    <section aria-labelledby="board-h">
      <div className="hdr"><h1 id="board-h">Matters</h1>
        <span className="sub">{list.data ? `${rows.length}${next ? "+" : ""} ${state ? "shown" : `open · ${nRunning} running`} · ${nNeeds} matter${nNeeds === "1" ? "" : "s"} waiting on you` : ""}</span>
        <span className="act"><a className="btn btn--primary" href={href("new")}
          style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>New matter</a></span></div>
      <WaitingOnYou items={pend.data?.items}
        runs={(needs.data?.items || []).filter((m) => !m.outstanding_approvals)} more={pend.data?.next_cursor != null} titles={titles}
        loading={pend.loading} error={pend.error} onRetry={pend.reload} />
      <div className="filters" role="group" aria-label="Filter matters">
        <button type="button" className="filter filter--loud" aria-pressed={state === "waiting_on_you"}
          onClick={() => setState("waiting_on_you")}>⚑ Needs you · {nNeeds}</button>
        {FILTERS.map(([v, label]) => (
          <button key={v} type="button" className="filter" aria-pressed={state === v}
            onClick={() => setState(v)}>{label}</button>))}
      </div>
      <ErrorLine error={list.error} onRetry={list.reload} stale={list.stale} />
      <LiveNote live={live} />
      <CommandError error={st.error} />
      <BulkBar s={pick} why={why} busy={st.busy} onDelete={() => remove([...pick.sel])} />
      {list.loading ? <Loading /> : rows.length === 0 ? (
        <Empty action={<a href={href("new")}>Create your first matter</a>}>
          {state ? "No matters in this state." : "No matters yet."}</Empty>
      ) : (
        <table className="table" aria-label="Matters" aria-describedby="board-keys">
          <thead><tr><SelectAll ids={rows.map((m) => m.matter_id)} s={pick} /><th scope="col">Matter</th><th scope="col">State</th><th scope="col">Stage</th>
            <th scope="col">Approvals</th><th scope="col">Due</th><th scope="col">Risk</th>
            <th scope="col" className="num">Tokens</th><th scope="col">Last activity</th>
            <th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
          <tbody tabIndex={0} onKeyDown={onKey} aria-label="Matter rows">
            {rows.map((m, i) => (
              <RowExtras key={m.matter_id} mid={m.matter_id}>{({ lc, dl, ln }) => {
                const next = nextDeadline(dl.data?.items);
                const lawyer = ln.data;
                return (
                <tr aria-selected={i === sel} onClick={() => open(m)}>
                  <SelectCell id={m.matter_id} label={m.title || m.matter_id} s={pick} />
                  <td className="title"><b><a href={href("workspace", { mid: m.matter_id })}>{m.title || m.matter_id}</a></b>
                    <span><span className="id">{m.matter_id}</span>{m.client_ref ? ` · ${m.client_ref}` : ""}
                      {m.matter_type ? ` · ${m.matter_type}` : ""}</span></td>
                  <td><StatusChip state={m.state} /></td>
                  <td>{orGap(lc, lc.data?.stage ? stageName(lc.data.stage) : null)}</td>
                  <td>{m.outstanding_approvals
                    ? <a className="chip chip--waiting" data-icon="⚑" href={href("workspace", { mid: m.matter_id, tab: "decisions" })}
                      aria-label={`${m.outstanding_approvals} pending on ${m.title || m.matter_id}`} onClick={(e) => e.stopPropagation()}>{m.outstanding_approvals}</a>
                    : "—"}</td>
                  <td className={`title${next?.status === "overdue" ? " due-late" : ""}`}>
                    {next ? <><b>{next.status === "overdue" ? `⚠ overdue · ${fmtDate(next.due)}` : fmtDate(next.due)}</b><span>{next.what}</span></> : orGap(dl, null)}</td>
                  <td className="wrap">{lawyer?.state && lawyer.state !== "clear" ? `⛔ Lawyer now: ${lawyer.triggers.map((t) => LAWYER_NOW_SHORT[t] || t).join(", ")}` : orGap(ln, null)}</td>
                  <td className="num">{fmtTokens(m.tokens_total)}</td>
                  <td>{fmtAgo(m.last_activity_at || m.updated_at || m.created_at)}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <Btn why={why} disabled={st.busy} onClick={() => remove([m.matter_id])}>Delete</Btn></td>
                </tr>); }}</RowExtras>))}
          </tbody>
        </table>
      )}
      {next ? <p><button type="button" className="btn" disabled={st.busy} onClick={loadMore}>Load more matters</button></p> : null}
      <p className="foot" id="board-keys">{live === "live" ? "Updating live" : live === "reconnecting" ? "Reconnecting…" : "Connecting…"}
        {" "}· <kbd>j</kbd> <kbd>k</kbd> to move, <kbd>Enter</kbd> to open</p>
    </section>
  );
}
