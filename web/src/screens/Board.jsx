// S2 Matter Board (05 §2; mockup B): portfolio table, "Needs you" loudest, live via the
// board SSE channel, j/k + Enter. Firm-only (§9A.2): self-rep sees a pointer to its case.
import { useEffect, useState } from "react";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";
import { useApi } from "../useApi.js";
import { Empty, ErrorLine, Loading, StatusChip, fmtAgo, fmtDate, fmtTokens } from "../ui.jsx";
import { LAWYER_NOW_SHORT } from "./CaseScreens.jsx";

const FILTERS = [["", "All"], ["running", "Running"], ["review_required", "Review"], ["blocked", "Blocked"]];

// shortcut: three reads per row (stage, next deadline, lawyer-now) — fine for a firm's
// open matters on loopback; fold them into the matter row if boards pass ~50 rows
function RowExtras({ mid, children }) {
  const lc = useApi(`/matters/${mid}/lifecycle`, { matter: mid });
  const dl = useApi(`/matters/${mid}/deadlines`, { matter: mid });
  const ln = useApi(`/matters/${mid}/lawyer-now`, { matter: mid });
  const next = (dl.data?.items || []).filter((d) => d.status !== "met")
    .sort((a, b) => (a.due || "").localeCompare(b.due || ""))[0];
  return children({ stage: lc.data?.stage, next, lawyer: ln.data });
}

export default function Board() {
  const { mode } = useCtx();
  const [state, setState] = useState("");
  const [sel, setSel] = useState(0);
  const list = useApi("/matters" + (state ? `?state=${state}` : ""));
  const needs = useApi("/matters?state=waiting_on_you");
  const rows = list.data?.items || [];
  const nNeeds = needs.data?.items?.length ?? 0;

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
        <span className="sub">{list.data ? `${rows.length} open` : ""}</span>
        <span className="act"><a className="btn btn--primary" href={href("new")}
          style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}>New matter</a></span></div>
      <div className="filters" role="group" aria-label="Filter matters">
        <button type="button" className="filter filter--loud" aria-pressed={state === "waiting_on_you"}
          onClick={() => setState("waiting_on_you")}>⚑ Needs you · {nNeeds}</button>
        {FILTERS.map(([v, label]) => (
          <button key={v} type="button" className="filter" aria-pressed={state === v}
            onClick={() => setState(v)}>{label}</button>))}
      </div>
      <ErrorLine error={list.error} onRetry={list.reload} />
      {list.loading ? <Loading /> : rows.length === 0 ? (
        <Empty action={<a href={href("new")}>Create your first matter</a>}>
          {state ? "No matters in this state." : "No matters yet."}</Empty>
      ) : (
        <table className="table" aria-label="Matters" aria-describedby="board-keys">
          <thead><tr><th scope="col">Matter</th><th scope="col">State</th><th scope="col">Stage</th>
            <th scope="col">Approvals</th><th scope="col">Due</th><th scope="col">Risk</th>
            <th scope="col" className="num">Tokens</th><th scope="col">Last activity</th></tr></thead>
          <tbody tabIndex={0} onKeyDown={onKey} aria-label="Matter rows">
            {rows.map((m, i) => (
              <RowExtras key={m.matter_id} mid={m.matter_id}>{({ stage, next, lawyer }) => (
                <tr aria-selected={i === sel} onClick={() => open(m)}>
                  <td className="title"><b><a href={href("workspace", { mid: m.matter_id })}>{m.title || m.matter_id}</a></b>
                    <span><span className="id">{m.matter_id}</span>{m.matter_type ? ` · ${m.matter_type}` : ""}</span></td>
                  <td><StatusChip state={m.state} /></td>
                  <td>{stage ? stage.toLowerCase().replace(/_/g, " ") : "—"}</td>
                  <td>{m.outstanding_approvals || "—"}</td>
                  <td className={next?.status === "overdue" ? "due-late" : undefined}>
                    {next ? (next.status === "overdue" ? `⚠ overdue · ${fmtDate(next.due)}` : fmtDate(next.due)) : "—"}</td>
                  <td className="wrap">{lawyer?.state && lawyer.state !== "clear" ? `⛔ Lawyer now: ${lawyer.triggers.map((t) => LAWYER_NOW_SHORT[t] || t).join(", ")}` : "—"}</td>
                  <td className="num">{fmtTokens(m.tokens_total)}</td>
                  <td>{fmtAgo(m.updated_at || m.created_at)}</td>
                </tr>)}</RowExtras>))}
          </tbody>
        </table>
      )}
      <p className="foot" id="board-keys">Updating live · {nNeeds} need you · <kbd>j</kbd> <kbd>k</kbd> to move, <kbd>Enter</kbd> to open</p>
    </section>
  );
}
