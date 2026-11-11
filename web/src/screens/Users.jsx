// M10 T5 — users & roles admin (user.admin) + the matter membership editor (matter.write).
// 05 §12: without the permission the mutation controls are hidden; the reason stays visible.
import { useState } from "react";
import { del, patch, post, put } from "../api.js";
import { useCtx } from "../App.jsx";
import { useApi } from "../useApi.js";
import { ErrorLine, Loading, allowed } from "../ui.jsx";
import { CommandError, useCommand } from "./Workspace.jsx";

export function UsersView({ users, roles, canAdmin, st, onCreate, onPatch }) {
  const [f, setF] = useState({ username: "", password: "", role_id: "reader" });
  if (!canAdmin) return <p className="table__empty">🔒 User administration requires the user.admin permission.</p>;
  const roleIds = (roles || []).map((r) => r.role_id);
  const stateLabel = (u) => u.state === "pending" ? "Pending" : u.state === "rejected" ? "Rejected"
    : u.must_change_password ? "Must set password" : u.is_active ? "Active" : "Deactivated";
  const submit = async (e) => {
    e.preventDefault();
    if (await onCreate(f)) setF({ username: "", password: "", role_id: f.role_id });
  };
  return (
    <div className="stack">
      <CommandError error={st.error} />
      <table className="table" aria-label="Users">
        <thead><tr><th scope="col">User</th><th scope="col">Role</th><th scope="col">State</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{(users || []).map((u) => (
          <tr key={u.user_id}>
            <td>{u.username} <span className="id">{u.user_id}</span></td>
            <td>{u.state === "pending" ? "reader" : <select aria-label={`Role for ${u.username}`} value={u.role_id} disabled={st.busy}
              onChange={(e) => onPatch(u.user_id, { role_id: e.target.value })}>
              {roleIds.map((r) => <option key={r} value={r}>{r}</option>)}</select>}</td>
            <td>{stateLabel(u)}</td>
            <td>{u.state === "pending" ? (
              <>
                <button type="button" className="btn" disabled={st.busy}
                  onClick={() => onPatch(u.user_id, { state: "active" })}>Approve</button>{" "}
                <button type="button" className="btn" disabled={st.busy}
                  onClick={() => onPatch(u.user_id, { state: "rejected" })}>Reject</button>
              </>
            ) : (
              <button type="button" className="btn" disabled={st.busy}
                onClick={() => onPatch(u.user_id, { is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Reactivate"}</button>
            )}</td>
          </tr>))}</tbody>
      </table>
      <form className="card qcard" onSubmit={submit}>
        <h2>New user</h2>
        <label htmlFor="nu-name">Username</label>
        <input id="nu-name" type="text" required autoComplete="off" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        <label htmlFor="nu-pw">Password</label>
        <input id="nu-pw" type="password" required autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <label htmlFor="nu-role">Role</label>
        <select id="nu-role" value={f.role_id} onChange={(e) => setF({ ...f, role_id: e.target.value })}>
          {roleIds.map((r) => <option key={r} value={r}>{r}</option>)}</select>
        <p><button type="submit" className="btn btn--primary" disabled={st.busy}>Create user</button></p>
      </form>
      <table className="table" aria-label="Roles">
        <thead><tr><th scope="col">Role</th><th scope="col">Permissions</th></tr></thead>
        <tbody>{(roles || []).map((r) => (
          <tr key={r.role_id}><td>{r.name || r.role_id} <span className="id">{r.role_id}</span></td>
            <td className="mono wrap">{r.permissions.join(", ")}</td></tr>))}</tbody>
      </table>
    </div>
  );
}

export default function Users() {
  const { perms } = useCtx();
  const can = allowed(perms, "user.admin");
  const us = useApi(can ? "/users" : null);
  const rs = useApi(can ? "/roles" : null);
  const [st, cmd] = useCommand();
  const done = (fn) => cmd(async () => { await fn(); us.reload(); return true; });
  return (
    <section aria-labelledby="users-h">
      <div className="hdr"><h1 id="users-h">Users &amp; roles</h1>
        <span className="sub">Matter access is still per matter — set it on each matter's Overview.</span></div>
      <ErrorLine error={us.error || rs.error} onRetry={() => { us.reload(); rs.reload(); }} />
      {can && (us.loading || rs.loading) ? <Loading /> : (
        <UsersView users={us.data} roles={rs.data} canAdmin={can} st={st}
          onCreate={(b) => done(() => post("/users", b))}
          onPatch={(uid, b) => done(() => patch(`/users/${encodeURIComponent(uid)}`, b))} />)}
    </section>
  );
}

export function MembersView({ members, roleIds, canWrite, st, onPut, onRemove }) {
  const [f, setF] = useState({ user_id: "", role_id: "reader" });
  return (
    <div className="stack">
      <CommandError error={st.error} />
      <table className="table" aria-label="Matter members">
        <thead><tr><th scope="col">Member</th><th scope="col">Role on this matter</th>
          {canWrite ? <th scope="col"><span className="sr-only">Actions</span></th> : null}</tr></thead>
        <tbody>{(members || []).map(({ user: u, role }) => (
          <tr key={u.user_id}>
            <td>{u.username} <span className="id">{u.user_id}</span></td>
            <td>{canWrite
              ? <select aria-label={`Role for ${u.username} on this matter`} value={role} disabled={st.busy}
                  onChange={(e) => onPut(u.user_id, e.target.value)}>
                  {roleIds.map((r) => <option key={r} value={r}>{r}</option>)}</select>
              : role}</td>
            {canWrite ? <td><button type="button" className="btn" disabled={st.busy} onClick={() => onRemove(u.user_id)}>Remove</button></td> : null}
          </tr>))}</tbody>
      </table>
      {canWrite ? (
        <form className="card qcard" onSubmit={async (e) => { e.preventDefault(); if (await onPut(f.user_id.trim(), f.role_id)) setF({ ...f, user_id: "" }); }}>
          <h2>Add a member</h2>
          <label htmlFor="am-uid">User ID <span className="hint">(from Users &amp; roles)</span></label>
          <input id="am-uid" type="text" required autoComplete="off" value={f.user_id} onChange={(e) => setF({ ...f, user_id: e.target.value })} />
          <label htmlFor="am-role">Role</label>
          <select id="am-role" value={f.role_id} onChange={(e) => setF({ ...f, role_id: e.target.value })}>
            {roleIds.map((r) => <option key={r} value={r}>{r}</option>)}</select>
          <p><button type="submit" className="btn btn--primary" disabled={st.busy}>Add member</button></p>
        </form>) : null}
    </div>
  );
}

// shortcut: GET /roles needs user.admin, so matter writers without it get the seeded role ids (db.py:118); fetch when a role catalogue opens up
const SEEDED_ROLES = ["admin", "editor", "reader"];

export function Members({ mid }) {
  const { perms } = useCtx();
  const ms = useApi(`/matters/${encodeURIComponent(mid)}/members`, { matter: mid });
  const rs = useApi(allowed(perms, "user.admin") ? "/roles" : null);
  const [st, cmd] = useCommand();
  const done = (fn) => cmd(async () => { await fn(); ms.reload(); return true; });
  const enc = encodeURIComponent;
  if (ms.error) return <ErrorLine error={ms.error} onRetry={ms.reload} />;
  if (!ms.data) return <Loading />;
  return <MembersView members={ms.data} roleIds={rs.data ? rs.data.map((r) => r.role_id) : SEEDED_ROLES}
    canWrite={allowed(perms, "matter.write")} st={st}
    onPut={(uid, role_id) => done(() => put(`/matters/${enc(mid)}/members/${enc(uid)}`, { role_id }))}
    onRemove={(uid) => done(() => del(`/matters/${enc(mid)}/members/${enc(uid)}`))} />;
}
