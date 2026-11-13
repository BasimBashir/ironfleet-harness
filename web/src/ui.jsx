// Shared UI pieces, 1:1 onto design/system/components.css (D-4). No inline colours.
import { useId, useState } from "react";

// [css class, icon, word] — the D-4 gallery's mapping (02 §4 matter, 02 §5 agent)
export const MATTER_STATES = {
  waiting_on_you: ["waiting", "⚑", "Waiting on you"],
  running: ["running", "●", "Running"],
  blocked: ["blocked", "■", "Blocked"],
  failed: ["failed", "✕", "Failed"],
  review_required: ["review", "◆", "Review required"],
  completed: ["done", "✓", "Completed"],
  draft: ["idle", "○", "Draft"],
  queued: ["idle", "◌", "Queued"],
  archived: ["idle", "▫", "Archived"],
};
export const AGENT_STATES = {
  created: ["idle", "○", "Created"],
  queued: ["idle", "◌", "Queued"],
  pending: ["idle", "◌", "Queued"],
  running: ["running", "●", "Running"],
  executing: ["running", "●", "Running"],
  waiting: ["waiting", "⏸", "Waiting"],
  paused: ["waiting", "⏸", "Paused"],
  waiting_human: ["waiting", "⚑", "Awaiting approval"],
  completed: ["done", "✓", "Completed"],
  failed: ["failed", "✕", "Failed"],
  timed_out: ["failed", "⏱", "Timed out"],
  cancelled: ["idle", "⊘", "Cancelled"],
  // UX-2 run overview, derived from persisted state only (see RunPage stageState)
  interrupted: ["blocked", "↻", "Interrupted"],
  not_run: ["idle", "—", "Not run"],
};

export function StatusChip({ state, kind = "matter" }) {
  const map = kind === "agent" ? AGENT_STATES : MATTER_STATES;
  const [cls, icon, word] = map[state] || ["idle", "○", String(state || "unknown").replace(/_/g, " ")];
  return <span className={`chip chip--${cls}`} data-icon={icon}>{word}</span>;
}

export const allowed = (perms, p) => !!perms && (perms.includes("*") || perms.includes(p));

// disabled-with-reason (05 §12): stays focusable, says why; never an enabled control that will fail
export function Btn({ why = "", primary = false, onClick, children, className = "", ...rest }) {
  const id = useId();
  const cls = `btn${primary ? " btn--primary" : ""} ${className}`.trim();
  if (why) {
    const { disabled: _focusable, ...r } = rest;  // aria-disabled only: a disabled button leaves the tab order
    return (
      <span>
        <button type="button" className={cls} aria-disabled="true" aria-describedby={id}
          onClick={(e) => e.preventDefault()} {...r}>{children}</button>
        <span className="btn__why" id={id}>{why}</span>
      </span>
    );
  }
  return <button type="button" className={cls} onClick={onClick} {...rest}>{children}</button>;
}

// row selection for "Delete selected" (Board, Documents, Drafts, added providers)
export function useSelect() {
  const [sel, setSel] = useState(() => new Set());
  const toggle = (id) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const all = (ids) => setSel((s) => (ids.every((i) => s.has(i)) ? new Set() : new Set(ids)));
  return { sel, toggle, all, clear: () => setSel(new Set()) };
}

export const confirmDelete = (n, noun) =>
  !!globalThis.confirm?.(`Delete ${n} ${noun}${n === 1 ? "" : "s"}? This cannot be undone.`);

export function SelectAll({ ids, s }) {
  return <th scope="col"><input type="checkbox" aria-label="Select all"
    checked={ids.length > 0 && ids.every((i) => s.sel.has(i))} onChange={() => s.all(ids)} /></th>;
}

export function SelectCell({ id, label, s }) {
  // stopPropagation: rows that open on click must not open when ticking the box
  return <td onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${label}`}
    checked={s.sel.has(id)} onChange={() => s.toggle(id)} /></td>;
}

export function BulkBar({ s, why = "", busy = false, onDelete }) {
  if (!s.sel.size) return null;
  return (
    <p role="group" aria-label="Selected rows">{s.sel.size} selected{" "}
      <Btn why={why} disabled={busy} onClick={onDelete}>Delete selected</Btn>{" "}
      <button type="button" className="btn" onClick={s.clear}>Clear selection</button></p>);
}

export function fmtTokens(n) {
  n = n || 0;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

const DATE = new Intl.DateTimeFormat("en-NZ", { day: "numeric", month: "short", year: "numeric" });
export const fmtDate = (iso) => (iso ? DATE.format(new Date(iso)) : "—");

export function fmtAgo(iso, now = Date.now()) {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

// "14 November 2026 (in 10 days)" — both forms, always (08 §1.4)
const LONG = new Intl.DateTimeFormat("en-NZ", { day: "numeric", month: "long", year: "numeric" });
export function fmtDue(iso, now = new Date()) {
  if (!iso) return "—";
  const d = new Date(iso);
  const days = Math.round((Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
    - Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  const rel = days === 0 ? "today" : days > 0 ? `in ${days} day${days === 1 ? "" : "s"}`
    : `${-days} day${days === -1 ? "" : "s"} ago`;
  return `${LONG.format(d)} (${rel})`;
}

// S10 states (05 §10): skeleton, actionable error, one-line empty + its one action
export function Loading({ rows = 3 }) {
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) =>
    <p key={i}><span className="skeleton" /></p>)}</div>;
}

// stale: the last good values stay on screen beneath this line (05 §10)
export function ErrorLine({ error, onRetry, stale = false }) {
  if (!error) return null;
  return (
    <div className="banner banner--flag" role="alert">
      <p className="banner__title">{stale ? "Couldn't refresh — showing the last loaded values" : "Couldn't load this"}</p>{" "}
      <span>{error.message}{error.code ? <span className="id"> ({error.code})</span> : null}</span>{" "}
      {onRetry ? <button type="button" className="btn" onClick={onRetry}>Try again</button> : null}
    </div>
  );
}

// 05 §10: SSE dropped → values on screen may be behind the server; say so, keep them
export function LiveNote({ live }) {
  return live === "reconnecting"
    ? <p className="stale" role="status">◐ Live updates paused — values may be out of date. Reconnecting…</p>
    : live === "unavailable"
      ? <p className="stale" role="status">○ Live updates unavailable — the server refused the event stream; values may be out of date. Retrying…</p> : null;
}

export function Empty({ children, action }) {
  return <div className="table__empty">{children} {action}</div>;
}

export function Meter({ label, used, max }) {
  const pct = max ? Math.min(100, Math.round((used / max) * 100)) : null;
  const level = pct == null ? undefined : pct >= 100 ? "over" : pct >= 80 ? "warn" : undefined;
  return (
    <span className="meter" role="meter" aria-label={label} aria-valuemin={0}
      aria-valuemax={max || undefined} aria-valuenow={used} data-level={level}>
      Tokens{pct != null ? <span className="meter__bar"><i style={{ width: `${pct}%` }} /></span> : null}
      <b>{fmtTokens(used)}</b>{max ? <> / {fmtTokens(max)}</> : null}
    </span>
  );
}
