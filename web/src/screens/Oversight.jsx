// M13.3 — admin oversight: firm-wide metrics + the audit chain across every matter (audit.read).
import { useCtx } from "../App.jsx";
import { useApi } from "../useApi.js";
import { ErrorLine, Loading, allowed } from "../ui.jsx";
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

export default function Oversight() {
  const { perms } = useCtx();
  const can = allowed(perms, "audit.read");
  const mt = useApi(can ? "/metrics" : null);
  return (
    <section aria-labelledby="ov-h">
      <div className="hdr"><h1 id="ov-h">Audit &amp; metrics</h1>
        <span className="sub">Every matter, every user. Matter content: open it from Matters.</span></div>
      {!can ? <p className="table__empty">🔒 Oversight needs the audit.read permission.</p> : (
        <>
          <h2>Metrics</h2>
          <ErrorLine error={mt.error} onRetry={mt.reload} />
          {mt.data ? <MetricsView m={mt.data} /> : mt.error ? null : <Loading />}
          <h2>Audit chain — all matters</h2>
          <Audit />
        </>)}
    </section>
  );
}
