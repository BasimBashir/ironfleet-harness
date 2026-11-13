// M13.7 — model settings admin (user.admin): provider rows (URL / model / write-only
// API key), per-stage assignment, Test probe. Dispatch fallback is gate.py's
// availability walk; an assignment lands on the next gate build (restart/session).
import { useState } from "react";
import { del, post, put } from "../api.js";
import { useCtx } from "../App.jsx";
import { useApi } from "../useApi.js";
import { BulkBar, ErrorLine, Loading, SelectAll, SelectCell, allowed, confirmDelete, useSelect } from "../ui.jsx";
import { CommandError, useCommand } from "./Workspace.jsx";

function ProviderRow({ p, st, tested, onSave, onTest, sel, onDelete }) {
  const [f, setF] = useState({ base_url: p.base_url, model: p.model });
  const [key, setKey] = useState("");
  return (
    <tr>
      {p.custom ? <SelectCell id={p.name} label={p.name} s={sel} /> : <td />}
      <td>{p.name} <span className="id">{p.tier}{p.has_key ? " · key set" : " · no key"}</span></td>
      <td><input aria-label={`Model for ${p.name}`} value={f.model} disabled={st.busy}
        onChange={(e) => setF({ ...f, model: e.target.value })} /></td>
      <td><input aria-label={`URL for ${p.name}`} value={f.base_url} disabled={st.busy}
        onChange={(e) => setF({ ...f, base_url: e.target.value })} /></td>
      <td><input type="password" autoComplete="new-password" placeholder={p.has_key ? "replace key" : "paste key"}
        aria-label={`API key for ${p.name}`} value={key} disabled={st.busy}
        onChange={(e) => setKey(e.target.value)} /></td>
      <td>
        <button type="button" className="btn btn--primary" disabled={st.busy}
          onClick={() => { onSave(p.name, f, key); setKey(""); }}>Save</button>{" "}
        <button type="button" className="btn" disabled={st.busy}
          onClick={() => onTest(p.name)}>Test</button>
        {p.custom ? <>{" "}<button type="button" className="btn" disabled={st.busy}
          onClick={() => onDelete([p.name])}>Delete</button></> : null}
        {tested[p.name] ? <span role="status"> {tested[p.name]}</span> : null}
      </td>
    </tr>
  );
}

const ENGINES = ["cloud", "ollama", "llamacpp", "vllm", "mlx-lm"];
const BLANK = { name: "", engine: "cloud", base_url: "", model: "", api_key: "" };

function AddProviderRow({ st, onAdd }) {
  const [f, setF] = useState(null);
  if (!f) return (
    <tr><td colSpan={6}><button type="button" className="btn" disabled={st.busy}
      onClick={() => setF(BLANK)}>+ Add provider</button></td></tr>);
  const field = (k, label, extra = {}) => (
    <input aria-label={label} placeholder={label} value={f[k]} disabled={st.busy}
      onChange={(e) => setF({ ...f, [k]: e.target.value })} {...extra} />);
  return (
    <tr>
      <td />
      <td>{field("name", "New provider name")}{" "}
        <select aria-label="Engine" value={f.engine} disabled={st.busy}
          onChange={(e) => setF({ ...f, engine: e.target.value })}>
          {ENGINES.map((e) => <option key={e} value={e}>{e}</option>)}
        </select></td>
      <td>{field("model", "New provider model")}</td>
      <td>{field("base_url", f.engine === "cloud" ? "Base URL (https)" : "Base URL (this machine, e.g. 127.0.0.1)")}</td>
      <td>{field("api_key", "API key (optional)", { type: "password", autoComplete: "new-password" })}</td>
      <td>
        <button type="button" className="btn btn--primary" disabled={st.busy || !f.name || !f.model || !f.base_url}
          onClick={async () => { if (await onAdd(f)) setF(null); }}>Add</button>{" "}
        <button type="button" className="btn" disabled={st.busy} onClick={() => setF(null)}>Cancel</button>
      </td>
    </tr>
  );
}

export function SettingsView({ data, canAdmin, st, tested, onSave, onTest, onAssign, onAdd, onDelete = async () => {} }) {
  const sel = useSelect();
  if (!canAdmin) return <p className="table__empty">🔒 Model settings requires the user.admin permission.</p>;
  const cands = (s) => [...new Set([...s.local_only, ...s.local_preferred, ...s.cloud_permitted])];
  // every stage can take any provider; embedding/rerank stay on-box (A-4)
  const pick = (s) => (data?.providers || []).filter((p) => !s.local_only_task || p.tier === "local");
  return (
    <div className="stack">
      <CommandError error={st.error} />
      <BulkBar s={sel} busy={st.busy} onDelete={async () => { await onDelete([...sel.sel]); sel.clear(); }} />
      <table className="table" aria-label="Providers">
        <thead><tr><SelectAll ids={(data?.providers || []).filter((p) => p.custom).map((p) => p.name)} s={sel} /><th scope="col">Provider</th><th scope="col">Model</th><th scope="col">URL</th><th scope="col">API key</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{(data?.providers || []).map((p) => (
          <ProviderRow key={p.name} p={p} st={st} tested={tested} onSave={onSave} onTest={onTest}
            sel={sel} onDelete={onDelete} />))}
          <AddProviderRow st={st} onAdd={onAdd} />
        </tbody>
      </table>
      <table className="table" aria-label="Stage assignment">
        <thead><tr><th scope="col">Stage</th><th scope="col">Fallback order</th><th scope="col">Assigned</th></tr></thead>
        <tbody>{(data?.stages || []).map((s) => (
          <tr key={s.task_class}>
            <td>{s.task_class}{s.local_only_task ? <span className="id"> local-only</span> : null}</td>
            <td className="mono wrap">{cands(s).join(", ") || "—"}</td>
            <td><select aria-label={`Assign for ${s.task_class}`} value={s.assign || ""} disabled={st.busy}
              onChange={(e) => onAssign(s.task_class, e.target.value || null)}>
              <option value="">auto</option>
              {pick(s).map((p) => <option key={p.name} value={p.name}>{`${p.name} · ${p.model}`}</option>)}
            </select></td>
          </tr>))}</tbody>
      </table>
      <p className="muted">Keys are write-only — the harness never shows one back. Dispatch walks the candidates
        and falls back to the local model when a provider is down; an assignment applies on the next run.</p>
    </div>
  );
}

export default function Settings() {
  const { perms } = useCtx();
  const can = allowed(perms, "user.admin");
  const sv = useApi(can ? "/settings/providers" : null);
  const [st, cmd] = useCommand();
  const [tested, setTested] = useState({});
  const save = (name, f, key) => cmd(async () => {
    const body = { base_url: f.base_url, model: f.model };
    if (key) body.api_key = key;
    await put(`/settings/providers?name=${encodeURIComponent(name)}`, body);
    sv.reload();
    return true;
  });
  const probe = (name) => cmd(async () => {
    const { data: r } = await post(`/settings/providers/test?name=${encodeURIComponent(name)}`, {});
    setTested((t) => ({ ...t, [name]: r.reachable
      ? `reachable · ${r.admission}${r.verified ? " · verified" : ""}`
      : "unreachable" }));
    return true;
  });
  const add = (f) => cmd(async () => {
    const body = { name: f.name.trim(), engine: f.engine, base_url: f.base_url.trim(), model: f.model.trim() };
    if (f.api_key) body.api_key = f.api_key;
    await post("/settings/providers", body);
    sv.reload();
    return true;
  });
  const remove = async (names) => {
    if (!confirmDelete(names.length, "provider")) return;
    await cmd(async () => {
      for (const n of names) await del(`/settings/providers?name=${encodeURIComponent(n)}`);
    });
    sv.reload();
  };
  const assign = (tc, provider) => cmd(async () => {
    await put(`/settings/assign?task_class=${encodeURIComponent(tc)}`, { provider });
    sv.reload();
    return true;
  });
  return (
    <section aria-labelledby="settings-h">
      <div className="hdr"><h1 id="settings-h">Model settings</h1>
        <span className="sub">Providers, keys and per-stage routing.</span></div>
      <ErrorLine error={sv.error} onRetry={sv.reload} />
      {can && sv.loading ? <Loading /> : (
        <SettingsView data={sv.data} canAdmin={can} st={st} tested={tested}
          onSave={save} onTest={probe} onAssign={assign} onAdd={add} onDelete={remove} />)}
    </section>
  );
}
