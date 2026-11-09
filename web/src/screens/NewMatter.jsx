// "+ New matter" (firm) / "Start a new case" (self-rep, N1 entry): POST /matters, then
// firm -> the workspace, self-rep -> the intake interview.
import { useState } from "react";
import { post } from "../api.js";
import { useCtx } from "../App.jsx";
import { href } from "../router.js";

export default function NewMatter() {
  const { mode } = useCtx();
  const self = mode === "self-rep";
  const [f, setF] = useState({ title: "", matter_type: "", jurisdiction: "NZ" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await post("/matters", f);
      const mid = r.data.matter_id;
      location.hash = self ? href("case", { mid, view: "intake" }) : href("workspace", { mid });
    } catch (x) { setErr(x); setBusy(false); }
  };
  return (
    <form className="form" onSubmit={submit} aria-labelledby="new-h">
      <div className="hdr"><h1 id="new-h">{self ? "Start a new case" : "New matter"}</h1></div>
      <div className="card qcard">
        <label htmlFor="nm-title">{self ? "Give your case a short name" : "Title"}
          {self ? <span className="hint"> For example: Me v Fleetwood Plumbing</span> : null}</label>
        <input id="nm-title" type="text" required value={f.title} onChange={set("title")}
          aria-describedby={err ? "nm-err" : undefined} />
        {!self ? (<>
          <label htmlFor="nm-type">Type</label>
          <input id="nm-type" type="text" value={f.matter_type} onChange={set("matter_type")} placeholder="Debt recovery" />
        </>) : null}
        <label htmlFor="nm-j">{self ? "Country" : "Jurisdiction"}</label>
        <select id="nm-j" value={f.jurisdiction} onChange={set("jurisdiction")}>
          <option value="NZ">New Zealand</option><option value="AU">Australia</option><option value="UK">United Kingdom</option>
        </select>
        {err ? <p className="field-error" id="nm-err" role="alert">{err.message}</p> : null}
      </div>
      <button className="btn btn--primary btn--big" type="submit" disabled={busy}>
        {busy ? "Creating…" : self ? "Start my case" : "Create matter"}</button>
    </form>
  );
}
