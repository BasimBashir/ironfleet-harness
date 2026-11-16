// M13.3 — admin oversight: firm-wide metrics + the audit chain across every matter (audit.read).
import { useCtx } from "../App.jsx";
import { useApi } from "../useApi.js";
import { ErrorLine, Loading, allowed, fmtTokens } from "../ui.jsx";
import { fmtMs } from "./Live.jsx";
import { Audit } from "./Workspace.jsx";

// as GET /metrics returns it (service/usage.py metrics())
export function MetricsView({ m }) {
  const d = m.dispatches;
  const kv = (o) => Object.entries(o || {}).map(([k, v]) => `${k || "—"}: ${v}`).join(" · ") || "none";
  return (
    <div className="stack">
      <table className="table" aria-label="Totals">
        <tbody>
          <tr><th scope="row">Model dispatches</th><td>{d.total} ({d.errors} errors)</td></tr>
          <tr><th scope="row">By engine</th><td>{kv(d.by_engine)}</td></tr>
          <tr><th scope="row">Tasks</th><td>{m.tasks.pending} pending · {m.tasks.running} running</td></tr>
          <tr><th scope="row">Executions</th><td>{kv(m.executions)}</td></tr>
        </tbody>
      </table>
      <table className="table" aria-label="Model latency">
        <thead><tr><th scope="col">Provider</th><th scope="col">Model</th><th scope="col" className="num">Calls</th>
          <th scope="col" className="num">p50 ms</th><th scope="col" className="num">p95 ms</th></tr></thead>
        <tbody>{m.latency.map((r) => (
          <tr key={`${r.provider}/${r.model}`}><td>{r.provider}</td><td className="mono">{r.model}</td>
            <td className="num">{r.n}</td><td className="num">{r.p50_ms}</td><td className="num">{r.p95_ms}</td></tr>))}</tbody>
      </table>
    </div>
  );
}

// as GET /usage returns it (service/usage.py account_usage()): one row per LLM account / user
export function UsageView({ u }) {
  const cols = (r) => (<>
    <td className="num">{r.calls}</td><td className="num">{r.errors}</td><td className="num">{fmtTokens(r.in)}</td>
    <td className="num">{fmtTokens(r.out)}</td><td className="num">{fmtTokens(r.thinking)}</td>
    <td className="num">{fmtTokens(r.all)}</td><td className="num">{fmtMs(r.ms)}</td></>);
  const head = (<><th scope="col" className="num">Calls</th><th scope="col" className="num">Errors</th>
    <th scope="col" className="num">In</th><th scope="col" className="num">Out</th><th scope="col" className="num">Thinking</th>
    <th scope="col" className="num">Total tokens</th><th scope="col" className="num">Model time</th></>);
  return (
    <div className="stack">
      <p>{`All time: ${u.total.calls} model calls · ${fmtTokens(u.total.all)} tokens · ${fmtMs(u.total.ms)} model time`}</p>
      <table className="table" aria-label="Usage by provider and model">
        <thead><tr><th scope="col">Provider</th><th scope="col">Model</th>{head}</tr></thead>
        <tbody>{u.by_model.map((r) => (
          <tr key={`${r.provider}/${r.model}`}><td>{r.provider}</td><td className="mono">{r.model}</td>{cols(r)}</tr>))}</tbody>
      </table>
      <table className="table" aria-label="Usage by user">
        <thead><tr><th scope="col">User (matter owner)</th>{head}</tr></thead>
        <tbody>{u.by_user.map((r) => <tr key={r.user}><td>{r.user}</td>{cols(r)}</tr>)}</tbody>
      </table>
      {u.by_user.some((r) => r.user === "(no matter)") ? <p className="small muted">(no matter): calls whose matter
        was deleted, or test and acceptance runs that never had a matter here. They still count in the totals above.</p> : null}
    </div>
  );
}

export default function Oversight() {
  const { perms } = useCtx();
  const can = allowed(perms, "audit.read");
  const mt = useApi(can ? "/metrics" : null);
  const us = useApi(can ? "/usage" : null);
  return (
    <section aria-labelledby="ov-h">
      <div className="hdr"><h1 id="ov-h">Audit &amp; metrics</h1>
        <span className="sub">Every matter, every user. Matter content: open it from Matters.</span></div>
      {!can ? <p className="table__empty">🔒 Oversight needs the audit.read permission.</p> : (
        <>
          <h2>Metrics</h2>
          <ErrorLine error={mt.error} onRetry={mt.reload} />
          {mt.data ? <MetricsView m={mt.data} /> : mt.error ? null : <Loading />}
          <h2>Usage per account</h2>
          <ErrorLine error={us.error} onRetry={us.reload} />
          {us.data ? <UsageView u={us.data} /> : us.error ? null : <Loading />}
          <h2>Audit chain — all matters</h2>
          <Audit />
        </>)}
    </section>
  );
}
