// S1 global shell (05 §1): top bar (⌘K, health dot, token meter, user), left rail,
// mode/theme/plain toggles, the SSE fan-out, and the hash router's outlet.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { getToken, post, setToken } from "./api.js";
import { href, parseRoute } from "./router.js";
import { subscribe } from "./sse.js";
import { EVENT, useApi } from "./useApi.js";
import { Meter } from "./ui.jsx";
import Board from "./screens/Board.jsx";
import NewMatter from "./screens/NewMatter.jsx";
import Workspace from "./screens/Workspace.jsx";
import Approvals from "./screens/Approvals.jsx";
import RunPage from "./screens/RunPage.jsx";
import CaseScreens from "./screens/CaseScreens.jsx";

export const Ctx = createContext(null);
export const useCtx = () => useContext(Ctx);

// shortcut: mode/theme/plain are per-browser (localStorage); move mode to a matter field with multi-user (M10)
function usePref(key, initial) {
  const [v, setV] = useState(() => localStorage.getItem(`ironfleet.${key}`) ?? initial);
  useEffect(() => { localStorage.setItem(`ironfleet.${key}`, v); }, [key, v]);
  return [v, setV];
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

function Login({ onDone }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState(null);
  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    try {
      const r = await post("/auth/login", { username: u, password: p });
      setToken(r.data.token);
      onDone();
    } catch (x) { setErr(x); }
  };
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
  const ctx = { me, perms, mode, setMode, theme, plain: plainOn, route };
  const name = me.user?.username || "";
  const nav = (name2, label, extra) => (
    <a href={href(name2)} aria-current={route.name === name2 ? "page" : undefined}><span>{label}</span>{extra}</a>);

  let screen;
  switch (route.name) {
    case "home":
    case "board": screen = <Board />; break;
    case "new": screen = <NewMatter />; break;
    case "workspace": screen = <Workspace mid={mid} tab={route.params.tab} />; break;
    case "approvals": screen = <Approvals />; break;
    case "run": screen = <RunPage rid={route.params.rid} />; break;
    case "case": screen = <CaseScreens mid={mid} view={route.params.view} />; break;
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
          {live === "live" ? "● Live" : live === "reconnecting" ? "◐ Reconnecting…" : "○ Connecting…"}
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
          <h2>Recent matters</h2>
          {(recent.data?.items || []).slice(0, 6).map((m) => (
            <a key={m.matter_id} href={href("workspace", { mid: m.matter_id })}
              aria-current={mid === m.matter_id ? "page" : undefined}><span>{m.title || m.matter_id}</span></a>))}
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
  return <Shell me={me.data} onLogout={logout} />;
}
