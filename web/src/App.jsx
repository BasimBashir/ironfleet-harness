// S1 global shell (05 §1): top bar (⌘K, health dot, token meter, user), left rail,
// mode/theme/plain toggles, the SSE fan-out, and the hash router's outlet.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getToken, post, setToken } from "./api.js";
import { href, parseRoute } from "./router.js";
import { subscribe } from "./sse.js";
import { EVENT, useApi } from "./useApi.js";
import { Meter, allowed } from "./ui.jsx";
import Board from "./screens/Board.jsx";
import NewMatter from "./screens/NewMatter.jsx";
import Workspace, { TABS } from "./screens/Workspace.jsx";
import Approvals from "./screens/Approvals.jsx";
import RunPage from "./screens/RunPage.jsx";
import CaseScreens, { NAV as CASE_NAV } from "./screens/CaseScreens.jsx";
import Users from "./screens/Users.jsx";
import Settings from "./screens/Settings.jsx";
import Oversight from "./screens/Oversight.jsx";

export const Ctx = createContext(null);
export const useCtx = () => useContext(Ctx);

// shortcut: mode/theme/plain are per-browser (localStorage); move mode to a matter field with multi-user (M10)
function usePref(key, initial) {
  const [v, setV] = useState(() => localStorage.getItem(`ironfleet.${key}`) ?? initial);
  useEffect(() => { localStorage.setItem(`ironfleet.${key}`, v); }, [key, v]);
  return [v, setV];
}

const TITLES = { home: "Matters", board: "Matters", new: "New matter", approvals: "Approvals",
  users: "Users & roles", settings: "Model settings", oversight: "Audit & metrics", notfound: "Page not found" };
export function pageTitle({ name, params: p }) {
  const what = name === "workspace" ? `${(TABS.find(([k]) => k === p.tab) || [, "Overview"])[1]} · ${p.mid}`
    : name === "run" ? `Run ${p.rid}`
      : name === "case" ? `${(CASE_NAV.find(([k]) => k === p.view) || [, "Case home"])[1]} · ${p.mid}`
        : TITLES[name] || TITLES.notfound;
  return `${what} — IronFleet`;
}

function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(location.hash));
  useEffect(() => {
    const on = () => setRoute(parseRoute(location.hash));
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function Login({ onDone, initialView = "signin" }) {
  const [view, setView] = useState(initialView); // signin | signup | sent
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      if (view === "signup") {
        await post("/auth/signup", { username: u, password: p });
        setView("sent");
        return;
      }
      const r = await post("/auth/login", { username: u, password: p });
      setToken(r.data.token);
      onDone();
    } catch (x) { setErr(x); }
  };
  if (view !== "signin") return (
    <main>
      <form className="card login" onSubmit={submit} aria-labelledby="login-h">
        {view === "signup" ? (
          <>
            <h1 id="login-h">Request an account</h1>
            <label htmlFor="u">Username</label>
            <input id="u" type="text" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required />
            <label htmlFor="p">Password</label>
            <input id="p" type="password" autoComplete="new-password" value={p}
              onChange={(e) => setP(e.target.value)} required aria-describedby={err ? "login-err" : undefined} />
            {err ? <p className="field-error" id="login-err" role="alert">{err.message}</p> : null}
            <p><button className="btn btn--primary" type="submit">Send request</button></p>
          </>
        ) : (
          <>
            <h1 id="login-h">Request sent</h1>
            <p role="status">✓ Request sent. An administrator must approve it before you can sign in.</p>
          </>
        )}
        <p><button type="button" className="btn" onClick={() => { setView("signin"); setErr(null); }}>← Back to sign in</button></p>
      </form>
    </main>
  );
  return (
    <main>
      <form className="card login" onSubmit={submit} aria-labelledby="login-h">
        <h1 id="login-h">Sign in to IronFleet</h1>
        <label htmlFor="u">Username</label>
        <input id="u" type="text" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required />
        <label htmlFor="p">Password</label>
        <input id="p" type="password" autoComplete="current-password" value={p}
          onChange={(e) => setP(e.target.value)} required aria-describedby={err ? "login-err" : undefined} />
        {err ? <p className="field-error" id="login-err" role="alert">{err.message}</p> : null}
        <p><button className="btn btn--primary" type="submit">Sign in</button></p>
        <p><button type="button" className="btn" onClick={() => { setView("signup"); setErr(null); }}>Request an account →</button></p>
      </form>
    </main>
  );
}

export function ChangePassword({ onDone }) {
  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (p1 !== p2) { setErr({ message: "Passwords do not match" }); return; }
    try {
      await post("/auth/password", { password: p1 });
      onDone();
    } catch (x) { setErr(x); }
  };
  return (
    <main>
      <form className="card login" onSubmit={submit} aria-labelledby="cp-h">
        <h1 id="cp-h">Set a new password</h1>
        <p>This account still uses its default password — choose a new one to continue.</p>
        <label htmlFor="cp1">New password</label>
        <input id="cp1" type="password" autoComplete="new-password" value={p1}
          onChange={(e) => setP1(e.target.value)} required />
        <label htmlFor="cp2">Repeat new password</label>
        <input id="cp2" type="password" autoComplete="new-password" value={p2}
          onChange={(e) => setP2(e.target.value)} required aria-describedby={err ? "cp-err" : undefined} />
        {err ? <p className="field-error" id="cp-err" role="alert">{err.message}</p> : null}
        <p><button className="btn btn--primary" type="submit">Save and continue</button></p>
      </form>
    </main>
  );
}

function Palette({ onClose, mode, setMode, theme, setTheme }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef(null);
  const { data } = useApi(`/matters?q=${encodeURIComponent(q)}`);
  const items = useMemo(() => {
    const cmds = [
      { label: "Go to Matters board", go: href("board") },
      { label: "Go to Approvals", go: href("approvals") },
      { label: mode === "firm" ? "New matter" : "Start a new case", go: href("new") },
      { label: `Switch to ${mode === "firm" ? "self-represented" : "firm"} mode`, run: () => setMode(mode === "firm" ? "self-rep" : "firm") },
      { label: `Switch to ${theme === "light" ? "dark" : "light"} theme`, run: () => setTheme(theme === "light" ? "dark" : "light") },
    ].filter((c) => c.label.toLowerCase().includes(q.toLowerCase()));
    const ms = (data?.items || []).map((m) => ({ label: m.title || m.matter_id, hint: m.matter_id,
      go: mode === "firm" ? href("workspace", { mid: m.matter_id }) : href("case", { mid: m.matter_id }) }));
    return [...ms, ...cmds];
  }, [data, q, mode, theme, setMode, setTheme]);
  useEffect(() => {  // focus in on open; back to whatever opened it on close
    const back = document.activeElement;
    input.current?.focus();
    return () => back?.focus?.();
  }, []);
  const pick = (it) => { onClose(); if (it.go) location.hash = it.go; else it.run(); };
  const onKey = (e) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "Tab") e.preventDefault();  // aria-modal: the input is the only stop
    else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    // preventDefault: else the same Enter's keypress lands on the restored trigger and reopens us
    else if (e.key === "Enter" && items[sel]) { e.preventDefault(); pick(items[sel]); }
  };
  return (
    <div className="palette-back" onClick={onClose}>
      <div className="card palette" role="dialog" aria-modal="true" aria-label="Command palette"
        onClick={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <input ref={input} type="text" role="combobox" aria-expanded="true" aria-controls="pal-list"
          aria-activedescendant={items[sel] ? `pal-${sel}` : undefined}
          aria-label="Search matters or run a command" placeholder="Search matters or run a command…"
          value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }} />
        <ul id="pal-list" role="listbox">
          {items.map((it, i) => (
            <li key={i} id={`pal-${i}`} role="option" aria-selected={i === sel} onClick={() => pick(it)}>
              <span>{it.label}</span>{it.hint ? <span className="id">{it.hint}</span> : null}
            </li>))}
        </ul>
      </div>
    </div>
  );
}

function Shell({ me, onLogout }) {
  const route = useRoute();
  const [mode, setMode] = usePref("mode", "firm");
  const [theme, setTheme] = usePref("theme", "light");
  const [plain, setPlain] = usePref("plain", "");
  const [live, setLive] = useState("connecting");
  const [palette, setPalette] = useState(false);
  const mid = route.params.mid;
  const plainOn = plain === "" ? mode === "self-rep" : plain === "on";   // N9: on by default in self-rep

  useEffect(() => {
    document.documentElement.dataset.mode = mode;
    document.documentElement.dataset.theme = theme;
  }, [mode, theme]);

  useEffect(() => {
    const chans = [...(mode === "firm" ? ["board"] : []), ...(mid ? [`matter:${mid}`] : [])];
    if (!chans.length) return undefined;
    return subscribe(chans, (e) => dispatchEvent(new CustomEvent(EVENT, { detail: e })),
      { onStatus: setLive });
  }, [mode, mid]);

  useEffect(() => { document.title = pageTitle(route); }, [route]);   // 2.4.2: each view names itself

  // 2.4.3: a new screen takes focus at its start (keyboard + screen-reader users otherwise stay on
  // the rail link). A screen that placed focus itself (intake question, lawyer-now banner) keeps it.
  const firstScreen = useRef(true);
  const rid = route.params.rid;
  useEffect(() => {
    if (firstScreen.current) { firstScreen.current = false; return; }
    const main = document.getElementById("main");
    if (main && !main.contains(document.activeElement)) main.focus();
  }, [route.name, mid, rid]);

  useEffect(() => {
    const on = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(true); }
    };
    addEventListener("keydown", on);
    return () => removeEventListener("keydown", on);
  }, []);

  const pending = useApi("/approvals?state=pending");
  const recent = useApi(mode === "firm" ? "/matters" : null);
  const tokens = useApi(mid ? `/matters/${mid}/tokens` : null, { matter: mid });
  const nPending = pending.data?.items?.length ?? 0;
  const perms = me.permissions || [];
  const ctx = { me, perms, mode, setMode, theme, plain: plainOn, route, live };
  const name = me.user?.username || "";
  // "page" on the screen itself; "true" on its section, so a matter or run still shows where it lives
  const at = route.name === "home" ? "board" : route.name;
  const section = { workspace: "board", run: "board", case: "board" }[at] || at;
  const nav = (name2, label, extra) => (
    <a href={href(name2)} aria-current={at === name2 ? "page" : section === name2 ? "true" : undefined}><span>{label}</span>{extra}</a>);

  let screen;
  switch (route.name) {
    case "home":
    case "board": screen = <Board />; break;
    case "new": screen = <NewMatter />; break;
    case "workspace": screen = <Workspace mid={mid} tab={route.params.tab} item={route.params.item} part={route.params.part} />; break;
    case "approvals": screen = <Approvals />; break;
    case "run": screen = <RunPage rid={route.params.rid} node={route.params.node} />; break;
    case "case": screen = <CaseScreens mid={mid} view={route.params.view} />; break;
    case "users": screen = <Users />; break;
    case "settings": screen = <Settings />; break;
    case "oversight": screen = <Oversight />; break;
    default: screen = <section><h1>Page not found</h1><p>That page does not exist. <a href={href("board")}>Go to the board</a></p></section>;
  }

  return (
    <Ctx.Provider value={ctx}>
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to content</a>
      <header className="top">
        <a className="brand" href={href(mode === "firm" ? "board" : "new")}>IronFleet</a>
        {mode === "firm"
          ? <button type="button" className="search" onClick={() => setPalette(true)}>Search matters, documents, runs… <kbd>⌘K</kbd></button>
          : <span style={{ flex: 1 }} className="muted">My case</span>}
        {mid && mode === "firm" ? <Meter label={`Tokens used on ${mid}`} used={tokens.data?.total?.all || 0} /> : null}
        <span className="toggles" role="group" aria-label="Display">
          <button type="button" className="toggle" aria-pressed={mode === "self-rep"}
            onClick={() => setMode(mode === "firm" ? "self-rep" : "firm")}>Self-rep mode</button>
          <button type="button" className="toggle" aria-pressed={plainOn}
            onClick={() => setPlain(plainOn ? "off" : "on")}>Reading level: {plainOn ? "Plain" : "Legal"}</button>
          <button type="button" className="toggle" aria-pressed={theme === "dark"}
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}>Dark</button>
        </span>
        <span className="health" data-state={live === "live" ? "live" : live === "reconnecting" ? "reconnecting" : "down"}
          role="status" aria-live="polite">
          {live === "live" ? "● Live" : live === "reconnecting" ? "◐ Reconnecting…" : live === "unavailable" ? "○ Live updates unavailable" : "○ Connecting…"}
        </span>
        <span className="user"><span className="av" aria-hidden="true">{name.slice(0, 2).toUpperCase()}</span>
          <span>{name}</span>
          <button type="button" className="btn" onClick={onLogout}>Sign out</button></span>
      </header>
      <div className="shell">
        <nav className="rail" aria-label="Main">
          {nav("board", "Matters")}
          {nav("approvals", "Approvals", nPending ? <span className="pill" aria-label={`${nPending} waiting`}>{nPending}</span> : null)}
          {nav("new", "+ New matter")}
          {allowed(perms, "user.admin") ? nav("users", "Users & roles") : null}
          {allowed(perms, "user.admin") ? nav("settings", "Model settings") : null}
          {allowed(perms, "audit.read") ? nav("oversight", "Audit & metrics") : null}
          <h2>Recent matters</h2>
          {(recent.data?.items || []).slice(0, 6).map((m) => (
            <a key={m.matter_id} href={href("workspace", { mid: m.matter_id })}
              aria-current={mid === m.matter_id ? "true" : undefined}><span>{m.title || m.matter_id}</span></a>))}
        </nav>
        <main id="main" tabIndex={-1}>{screen}</main>
      </div>
      {palette ? <Palette onClose={() => setPalette(false)} mode={mode} setMode={setMode} theme={theme} setTheme={setTheme} /> : null}
    </Ctx.Provider>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const me = useApi(authed ? "/auth/me" : null);
  const logout = useCallback(() => { setToken(""); setAuthed(false); }, []);
  useEffect(() => {
    addEventListener("ironfleet:logout", logout);
    return () => removeEventListener("ironfleet:logout", logout);
  }, [logout]);
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  if (!me.data) return me.error ? <Login onDone={() => { setAuthed(true); me.reload(); }} /> : null;
  if (me.data.must_change_password) return <ChangePassword onDone={me.reload} />;
  return <Shell me={me.data} onLogout={logout} />;
}
