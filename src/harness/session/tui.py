# src/harness/session/tui.py
"""The IronFleet shell: a Textual app with three panes (chat + global view + docs)
and a status bar that ALWAYS shows the active orchestration mode — the user's D-T2
ruling. shift+TAB cycles the three modes.

This is the FOREMAN, not the brain: it never calls a model itself. It starts
opencode sessions (harness.session.workspace.spawn_session), reads visibility from
trace.db / guard-log.jsonl / the workspace git tree, and everything it drives goes
through the egress gate. No new egress seam, ever.

The pure functions (cycle_mode, render_status) are unit-tested; the live app needs
a real terminal, so it is smoke-run by a human, never by the suite.
"""
from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
# NoMatches is query_one's failure when a widget is not mounted yet (tests build
# the app without a pilot) — the ONE expected exception in this module.
from textual.css.query import NoMatches
# Textual 8.x: TabPane wraps a pane's widget and NAMES its tab (ContentTab exists
# but referencing bare sibling widgets auto-creates "Tab N" headers for each —
# verified by pilot against the installed 8.2.8).
from textual.widgets import Footer, Input, Static, TabbedContent, TabPane

from harness.session.store import SessionStore

# -- error policy ---------------------------------------------------------------
# A caught exception in this app is RECORDED (harness.session.errors), never
# swallowed: the TUI cannot propagate — it would die mid-flight and take the user's
# session with it — but a silently-swallowed failure is a shell that stops working
# with nothing to find in the logs. NoMatches (widget not mounted yet) is the one
# expected case; everything else is recorded so it is locatable later.
from harness.session.errors import record_error


def _tui_error(where: str, exc: BaseException, *, root=None, **context) -> None:
    """Record a TUI failure unless it is the expected not-mounted condition.
    `root` is the store root so the row lands in the durable error log (stderr
    only as the fallback before a store exists)."""
    if not isinstance(exc, NoMatches):
        record_error(exc, where=f"session.tui.{where}", root=root, context=context)

# The three ratified orchestration modes (D-T2). shift+TAB cycles them; the active
# one is always visible in the status bar.
MODES: tuple[str, ...] = ("agent-os", "shell-drives", "hybrid")


def cycle_mode(current: str) -> str:
    """The shift+TAB cycle, wrapped — pure so the bar and the binding can't drift."""
    if current not in MODES:
        raise ValueError(f"unknown mode: {current!r} (expected one of {MODES})")
    return MODES[(MODES.index(current) + 1) % len(MODES)]


def render_status(*, mode: str, session_id: str | None, used: int, window: int) -> str:
    """The status bar's text. The D-T3 meter shows used vs remaining against the
    user-declared window; honest dashes when either is absent (no session yet, or a
    provider row that declares no window)."""
    if session_id is None:
        sess = "—"
    else:
        sess = session_id
    if window > 0:
        pct = round(100 * used / window)
        tokens = f"{used:,}/{window:,} ({pct}%)"
    else:
        tokens = f"{used:,}/—"
    # ASCII separators: the box-drawing │ mojibakes in a cp1252 Windows console,
    # and this bar is the first thing a user reads.
    return f" mode: {mode} | session: {sess} | tokens: {tokens}"


def render_jobs(rows: list[dict], spin: int = 0) -> str:
    """The stage ledger, COLLAPSED to the latest row per (stage, agent): the
    table is append-only (a running row, then its done/failed row), and the raw
    stream read as "running 749:06" for stages that finished yesterday. A stage
    still running shows the spinner + live elapsed; a finished one shows its
    total duration. Pure so tests and the timer share one truth."""
    if not rows:
        return "no jobs yet — give the shell a task"
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    spinner = "|/-\\"[spin % 4]
    latest: dict[tuple[str, str], dict] = {}
    started: dict[tuple[str, str], str] = {}
    for r in rows:
        key = (r["stage"], r["agent"])
        if r["status"] == "running":
            started[key] = r.get("ts") or ""    # OVERWRITE: the latest start,
        latest[key] = r                          # never a prior run's start ts
    lines = []

    def _mins_secs(seconds: float) -> str:
        m, s = divmod(max(0, int(seconds)), 60)
        return f"{m:02d}:{s:02d}"

    for (stage, agent), r in latest.items():
        detail = f" — {r['detail']}" if r.get("detail") else ""
        start_ts = started.get((stage, agent)) or r.get("ts") or ""
        try:
            began = datetime.fromisoformat(start_ts)
        except ValueError:
            began = None
        if r["status"] == "running" and began is not None:
            lines.append(f"[{spinner} running {_mins_secs((now - began).total_seconds())}"
                         f"] {stage} ({agent}){detail}")
        elif r["status"] in ("done", "failed") and began is not None:
            took = _mins_secs((datetime.fromisoformat(r["ts"]) - began).total_seconds())
            lines.append(f"[{r['status']:>7} {took}] {stage} ({agent}){detail}")
        else:
            lines.append(f"[{r['status']:>7}] {stage} ({agent}){detail}")
    return "\n".join(lines)


def split_plan(text: str) -> tuple[str, str]:
    """A typed task may carry a ```plan fenced block — the factory's stage script
    (stage|agent|prompt per line), the same shape the acceptance driver feeds
    run_task. The block moves to plan_text verbatim; the rest stays the task.
    Pure so tests and the dispatch worker share one rule."""
    import re
    m = re.search(r"```plan\s*\n.*?```", text, re.S)
    if not m:
        return text, ""
    prose = (text[:m.start()] + text[m.end():]).strip()
    return (prose or "(run the plan)"), m.group(0)


def render_agents(rows: list[dict], jobs: list[dict] | None = None,
                  spin: int = 0) -> str:
    """The agent table: one line per agent — LIVE status (the jobs ledger), the
    honest serving tier (whatever the trace recorded), token spend in/out plus
    THINKING, guard activity, last dispatch status. A RUNNING agent with no
    trace rows yet (its first turn is still in flight) still shows, with the
    spinner — the user must see WHO is working before its dispatch lands."""
    spinner = "|/-\\"[spin % 4]
    # collapse to the LATEST row per (stage, agent) — the raw ledger spams every
    # past run's start rows as "in flight" forever otherwise
    latest: dict[tuple[str, str], dict] = {}
    for j in (jobs or []):                      # jobs() is oldest-first: last wins
        latest[(j["stage"], j["agent"])] = j
    status_by_agent: dict[str, str] = {}
    running: set[str] = set()
    for (stage, agent), j in latest.items():
        status_by_agent[agent] = f"{j['status']} {stage}"
        if j["status"] == "running":
            running.add(agent)
    lines = []
    for r in rows:
        v = "verified" if r.get("verified") else "unverified"
        st = status_by_agent.get(r["agent"], "idle")
        mark = f"{spinner} {st}" if r["agent"] in running else st
        think = r.get("tokens_reasoning") or 0
        lines.append(f"[{mark}] {r['agent']}: {r['provider']}/{r['model']} [{v}] "
                     f"in {r['tokens_in']:,} out {r['tokens_out']:,}"
                     + (f" think {think:,}" if think else "")
                     + f" guard {r['guard_flags']} last {r['last_status']}")
    # In-flight agents the trace cannot see yet — the waiting indicator, from
    # the COLLAPSED view only (latest row per stage+agent actually running).
    traced = {r["agent"] for r in rows}
    for (stage, agent), j in latest.items():
        if j["status"] == "running" and agent not in traced:
            lines.append(f"[{spinner} running {stage}] {agent}: "
                         "first turn in flight — waiting for its model …")
    if not lines:
        return "no agents yet"
    return "\n".join(lines)


class IronFleetApp(App):
    """The shell. One window: chat, the global view, live docs, and the status bar.

    The factory runner is injected (None until Task 7 lands) so the shell is
    constructible and mode-cyclable before the factory exists — the skeleton is
    reviewable on its own."""

    TITLE = "IronFleet"

    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #chat-scroll { width: 2fr; height: 1fr; border: round $primary; }
    #side { width: 3fr; }
    /* height:auto (no max-height clamp): the Static must GROW past the
       viewport for the VerticalScroll around it to have anything to scroll —
       max-height:100% flattened every pane to the viewport (the non-scroll
       bug the live session hit) */
    #view { height: auto; }
    #docs { height: auto; }
    #mind { height: auto; }
    #corpus { height: auto; }
    #status { dock: bottom; height: 1; background: $panel; color: $text; }
    #prompt { dock: bottom; height: 3; margin-bottom: 1; }
    TabPane { height: 1fr; }
    .pane-scroll { height: 1fr; }
    """

    BINDINGS = [
        # priority=True: without it, the focused TabbedContent consumes shift+tab
        # for its OWN next-tab cycle and this App-level binding never fires
        # (observed in the headless smoke: the key pressed, the mode unchanged).
        # Textual 8.x: the tuple form accepts only 2-3 strings, so a priority
        # binding must be a Binding instance with priority=True.
        Binding("shift+tab", "cycle_mode", "Cycle mode", priority=True),
        ("ctrl+q", "quit", "Quit"),
        # Textual's mouse capture eats drag-selection; ctrl+o hands the whole chat
        # pane to the Windows clipboard (SHIFT+drag selects a region natively).
        ("ctrl+o", "copy_chat", "Copy chat"),
        # ctrl+c is Textual's own quit (App default, system binding) — the user's
        # ruling: NOTHING quits the shell but ctrl+q, not even the reflex ctrl+c
        # (a mis-key would kill a stage mid-flight). Shadow it with a no-op.
        Binding("ctrl+c", "noop", show=False, priority=True),
    ]

    def __init__(self, store: SessionStore, session_id: str | None = None,
                 mode: str = "agent-os", runner: object | None = None,
                 runner_factory=None, trace=None, provider_name: str = "",
                 base: Path | None = None, docs_ws: Path | None = None) -> None:
        super().__init__()
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r} (expected one of {MODES})")
        self.store = store
        self.session_id = session_id
        self.mode = mode
        self.runner = runner
        # D-T2: cycling the mode REBUILDS the runner (the active mode is not a
        # label — the next task must execute under the newly selected mode).
        self._runner_factory = runner_factory
        # D-T3: the meter's live numbers, refreshed from trace.db by the timer
        # (F2: the TRACE carries the real token counts, never the event stream).
        self.trace = trace
        self.provider_name = provider_name
        # Task 12: `base` is the session-workspace root (the guard-log read);
        # `docs_ws` is the workspace the doc pane watches (injected — the factory
        # or the acceptance driver names the workspace whose edits matter).
        self.base = base
        self.docs_ws = docs_ws
        self.tokens_used = 0
        self.context_window = 0
        self._spin = 0                       # the ASCII spinner frame (|/-\)
        self._doc_links: dict[str, str] = {}  # link token -> file path
        self._echoed_docs: set[str] = set()   # deliverables already announced

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            # The chat scrolls and FOLLOWS the tail: panes update from _echo and
            # _tick, then scroll_end keeps the newest line visible (the user's
            # Claude-Code-style follow).
            with VerticalScroll(id="chat-scroll"):
                yield Static("", id="chat")
            # Textual 8.x: TabPane wraps each pane's widget and names the tab —
            # bare siblings inside TabbedContent auto-tab as "Tab 1..N".
            with TabbedContent(id="side"):
                yield TabPane("Jobs", VerticalScroll(Static("", id="view"),
                                                     classes="pane-scroll"))
                yield TabPane("Docs", VerticalScroll(Static("", id="docs"),
                                                     classes="pane-scroll"))
                yield TabPane("Corpus", VerticalScroll(Static("", id="corpus"),
                                                       classes="pane-scroll"))
                yield TabPane("Thinking", VerticalScroll(Static("", id="mind"),
                                                         classes="pane-scroll"))
        yield Static(self.render_status_text(), id="status")
        yield Input(placeholder="prompt an agent, or /ingest /plan <file> /compact /mode",
                    id="prompt")
        yield Footer()

    def action_noop(self) -> None:
        """The ctrl+c trap (see BINDINGS): swallow the reflex, quit nothing."""

    def _link(self, path: Path) -> str:
        """A clickable Textual action link for a file. The token keeps paths
        (spaces, backslashes) out of the action markup's quoting hell."""
        token = f"d{len(self._doc_links)}"
        self._doc_links[token] = str(path)
        return f"[@click=app.open_doc('{token}')]{path.name}[/]"

    def action_open_doc(self, token: str) -> None:
        """Click a linked deliverable — the OS default handler opens it (no ctrl
        needed: Textual action links route inside the app)."""
        import os
        path = self._doc_links.get(token)
        if not path or not Path(path).is_file():
            self._echo("(that link is stale — the file moved or predates this run)")
            return
        try:
            os.startfile(path)                 # Windows default handler
        except OSError as exc:                 # noqa: BLE001
            _tui_error("open_doc", exc, root=self.store.root)
            self._echo(f"(could not open {path}: {exc})")

    def _echo_deliverables(self) -> None:
        """Announce every doc an agent wrote as a clickable line (once per file)."""
        if not (self.session_id and self.base):
            return
        for f in sorted((Path(self.base) / self.session_id).glob("*/*.md")):
            if ".opencode" in f.parts or str(f) in self._echoed_docs:
                continue
            self._echoed_docs.add(str(f))
            self._echo(f"deliverable: {self._link(f)}")

    # -- the status bar (the D-T3 meter + the always-visible mode) -------------

    def render_status_text(self) -> str:
        return render_status(mode=self.mode, session_id=self.session_id,
                             used=self.tokens_used, window=self.context_window)

    def refresh_status(self) -> None:
        if not self.is_running:
            return            # not mounted (tests/acceptance build the app headless)
        try:
            self.query_one("#status", Static).update(self.render_status_text())
        except Exception as exc:                              # noqa: BLE001
            # Anything past a running app is recorded so the bar going stale is
            # diagnosable.
            _tui_error("refresh_status", exc)

    # -- the mode cycle (D-T2) -------------------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r} (expected one of {MODES})")
        self.mode = mode
        if self._runner_factory is not None:
            self.runner = self._runner_factory(mode)
        self.refresh_status()

    def action_cycle_mode(self) -> None:
        self.set_mode(cycle_mode(self.mode))

    def _apply_mode_command(self, name: str) -> None:
        """/mode <name>: the typed form of shift+TAB. An unknown name is recorded
        and echoed — the submit handler must never crash on a typo."""
        try:
            self.set_mode(name)
        except ValueError as exc:
            _tui_error("mode_command", exc)
            self._echo(f"/mode: {exc}")

    # -- the global view pane (the session's tasks: the S7f jobs table) --------

    def refresh_view(self) -> str:
        """Render this session's jobs AND agents into the view pane. Returns the
        text (the unmounted case — tests, early compose — still gets an honest
        return). Both halves read the substrate: the store's jobs table and
        trace.db via view.agent_status (F1 columns + the guard-log count)."""
        rows = self.store.jobs(self.session_id) if self.session_id else []
        text = render_jobs(rows, self._spin)
        if self.trace is not None and self.session_id:
            from harness.session.tokens import session_trace_refs
            from harness.session.view import agent_status
            agents = agent_status(self.trace, self.session_id, self.base,
                                  refs=session_trace_refs(self.store, self.session_id))
            text = f"{text}\n---\n{render_agents(agents, rows, self._spin)}"
        if self.is_running:               # headless callers just take the text
            try:
                self.query_one("#view", Static).update(text)
            except Exception as exc:                          # noqa: BLE001
                _tui_error("refresh_view", exc)
        return text

    def _docs_text(self) -> str:
        """The doc pane's text: the ACTIVE stage workspace's changed files as
        CLICKABLE links (git status — a NEW doc is untracked and invisible to
        ls-files/diff) + the diff body. The watched workspace follows the crew:
        the latest job's `<agent>-stage-<stage>` directory, falling back to the
        injected docs_ws."""
        ws = self._active_ws()
        if ws is None:
            return "no workspace watched"
        from harness.session.view import doc_changes, doc_diff
        changes = doc_changes(ws)
        if changes:
            linked = ", ".join(self._link(ws / c) if not c.endswith("/") else c
                               for c in changes[:8])
            head = (f"watching {ws.name} — changed: {linked}"
                    f"{' …' if len(changes) > 8 else ''}")
        else:
            head = f"watching {ws.name} — changed: (nothing yet)"
        diff = doc_diff(ws)
        return f"{head}\n{diff}" if diff else head

    def _active_ws(self) -> Path | None:
        if not (self.session_id and self.base):
            return self.docs_ws
        rows = self.store.jobs(self.session_id)
        if rows:
            j = rows[-1]                          # jobs() is oldest-first
            cand = Path(self.base) / self.session_id / f"{j['agent']}-stage-{j['stage']}"
            if cand.is_dir():
                return cand
        return self.docs_ws

    def _tick(self) -> None:
        """The poll: meter, status bar, view pane (jobs + agents), doc, corpus and
        thinking panes — one timer, all substrate reads. The spinner advances so
        RUNNING rows visibly move: the shell is alive, not idle."""
        self._spin += 1
        if self.trace is not None and self.session_id:
            from harness.session.tokens import (session_trace_refs,
                                                usage_for_refs, window_for)
            # F2: the TRACE carries the real numbers; the join key is the shell's
            # OWN record (TurnRow.trace_refs) — the live mount does not carry
            # session identity to the gate, so by_session would read empty.
            usage = usage_for_refs(
                self.trace, session_trace_refs(self.store, self.session_id))
            self.tokens_used = usage["in"] + usage["out"]
            self.context_window = window_for(self.provider_name)[0]
        self.refresh_status()
        self.refresh_view()
        for pane_id, text in (("#docs", self._docs_text()),
                              ("#corpus", self._corpus_text()),
                              ("#mind", self._thinking_text())):
            try:
                self.query_one(pane_id, Static).update(text)
            except Exception as exc:                          # noqa: BLE001
                _tui_error(f"refresh{pane_id}", exc)
        self._follow()

    def _follow(self) -> None:
        """Keep the chat pinned to its tail (the follow as contents arrive)."""
        if self.is_running:
            try:
                self.query_one("#chat-scroll", VerticalScroll).scroll_end(
                    animate=False, duration=0.0)
            except Exception:                                 # noqa: BLE001
                pass

    def _corpus_text(self) -> str:
        """The Corpus pane: what is ACTUALLY in the matter's store — one row per
        ingested document (name, words, chunks) under the chunk total."""
        if not self.session_id:
            return "(no session yet)"
        try:
            from harness.corpus import CorpusStore
            matter = next((r.get("matter_ref") for r in self.store.sessions()
                           if r["session_id"] == self.session_id), None)
            if not matter:
                return "(no matter for this session)"
            store = CorpusStore(self.store.root / "corpus.sqlite3")
            docs = store.docs(matter)
            if not docs:
                return (f"matter {matter}: nothing ingested yet — /ingest <path>")
            lines = [f"matter {matter}: {store.doc_count(matter)} docs, "
                     f"{store.count(matter):,} chunks"]
            lines += [f"  {d['name']} — {d['words'] or 0:,} words, {d['chunks']} chunks"
                      for d in docs[:40]]
            if len(docs) > 40:
                lines.append(f"  … {len(docs) - 40} more")
            return "\n".join(lines)
        except Exception as exc:                              # noqa: BLE001
            _tui_error("corpus_pane", exc, root=self.store.root)
            return "(corpus read failed — see errors.jsonl)"

    def _thinking_text(self) -> str:
        """The Thinking pane: each turn's captured reasoning stream (opencode
        'reasoning' parts, capped per turn), newest last — the expandable view of
        WHAT the agents were thinking while they worked. Empty until a model that
        reasons actually runs."""
        if not self.session_id:
            return "(no session yet)"
        rows = [r for r in self.store.turns(self.session_id)
                if (getattr(r, "thinking", "") or "").strip()]
        if not rows:
            return "(no thinking captured yet — reasoning parts land here per turn)"
        lines: list[str] = []
        for r in rows[-8:]:
            head = (r.output_summary or "").replace("\n", " ")[:60]
            lines.append(f"―― {r.agent} · {r.ts[11:19]} · then said: {head}")
            lines.append(r.thinking.strip()[-2000:])
        return "\n".join(lines)

    def on_mount(self) -> None:
        self.set_interval(2.0, self._tick)
        if self.session_id:
            self._echo(f"session {self.session_id} ready — type a task, or "
                       "/ingest <path> · /plan <file> · /compact · /doctor · "
                       "/provider · shift+TAB mode · ctrl+o copy · ctrl+q quit")

    # -- the prompt line --------------------------------------------------------

    @on(Input.Submitted, "#prompt")
    def _submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            return
        # Claude-Code behaviour: the line LEAVES the box and lands in the chat as
        # the record of what the user asked, in order, whatever it was.
        event.input.value = ""
        self._echo(f"> {text}")
        if text == "/mode":
            self.action_cycle_mode()
        elif text.startswith("/mode "):
            self._apply_mode_command(text.split(maxsplit=1)[1])
        elif text == "/doctor":
            self.run_worker(self._doctor(), exclusive=False)
        elif text.startswith("/ingest "):
            self.run_worker(self._ingest(text.split(maxsplit=1)[1]), exclusive=False)
        elif text.startswith("/plan "):
            # The kickoff message lives in a FILE: the prompt line is one line
            # tall, and a pasted multi-line ```plan block dies in it (the live
            # session proved it — the crew fell back to two route stages).
            body = self._read_plan(text.split(maxsplit=1)[1])
            if body:
                self.run_worker(self._dispatch_task(body), exclusive=False)
        elif text.startswith("/persona new "):
            self._persona_new(text.split(maxsplit=2)[2])
        elif text == "/provider" or text.startswith("/provider "):
            self._providers()
        else:
            # A task for the factory — auto-/compact fires FIRST if the meter is
            # past safe_fill (Claude-Code behaviour, visible line), then the
            # runner's plan executes under the CURRENT mode.
            self.run_worker(self._dispatch_task(text), exclusive=False)

    def action_copy_chat(self) -> None:
        """ctrl+o: the whole chat pane to the Windows clipboard (clip.exe, UTF-16
        with a BOM so unicode survives) — Textual's mouse capture eats drag-selection."""
        import subprocess
        try:
            text = str(self.query_one("#chat", Static).render() or "")
        except Exception as exc:                              # noqa: BLE001
            _tui_error("copy_chat", exc, root=getattr(self.store, "root", None))
            return
        try:
            subprocess.run("clip", input=b"\xff\xfe" + text.encode("utf-16-le"),
                           check=False)
            self._echo("(chat copied to the clipboard)")
        except Exception as exc:                              # noqa: BLE001
            _tui_error("copy_chat", exc, root=getattr(self.store, "root", None))

    def _read_plan(self, path: str) -> str:
        """/plan <file>: read the kickoff message (prose + ```plan block) from a
        file. A missing file or a plan-less file is echoed, never a silent run."""
        p = Path(path.strip().strip('"'))
        if not p.is_file():
            self._echo(f"/plan: no such file: {path}")
            return ""
        body = p.read_text(encoding="utf-8", errors="replace")
        if "```plan" not in body:
            self._echo("/plan: no ```plan block in the file — running it as a "
                       "plain task (routes fallback)")
        return body

    async def _doctor(self) -> None:
        """/doctor: the honest state, one screen. The provider rows show what the
        REGISTRY declares (tier, window) — the probe verdict lands at registration
        (harness providers / stack start); re-probing every provider on a slash
        command would re-key the world for a view."""
        import json as _json
        from pathlib import Path as _Path
        from harness.bootstrap import _provider_specs
        from harness.packaging.macdist import PINS
        from harness.session.commands import doctor_lines
        try:
            from scripts.verify_opencode_mount import installed_version
            installed = installed_version()
        except Exception as exc:                              # noqa: BLE001
            _tui_error("doctor_version", exc)
            installed = None
        cfg = _Path.home() / ".config" / "opencode" / "opencode.jsonc"
        autoupdate = None
        if cfg.is_file():
            try:
                body = cfg.read_text(encoding="utf-8")
                autoupdate = '"autoupdate": false' in body or '"autoupdate":false' in body
            except Exception as exc:                          # noqa: BLE001
                _tui_error("doctor_cfg", exc)
        provs = [(s["name"], f"declared {s.get('tier', '?')},"
                 f" window {s.get('context_window') or '—'}")
                 for s in _provider_specs()]
        self._echo("\n".join(doctor_lines(
            installed=installed, pin=str(PINS["opencode"]),
            autoupdate=autoupdate, providers=provs)))

    async def _ingest(self, source: str) -> None:
        """/ingest <path>: corpus_ingest into THIS session's matter, in a thread
        (sha256 resume, batches of 64, LOCAL_ONLY embeddings — the substrate), each
        doc's verdict echoed as it lands."""
        import asyncio
        import json as _json
        from pathlib import Path as _Path
        driver = getattr(self.runner, "driver", None)
        if driver is None or not self.session_id:
            self._echo("(no session — /new --matter <ref> first)")
            return
        matter_ref = driver.resume(self.session_id)["matter_ref"]
        self._echo(f"ingesting {source} into {matter_ref}…")

        def _run() -> dict:
            from scripts.corpus_ingest import (build_live_stack, ingest_dir,
                                               make_embed_fn)
            gate, store = build_live_stack("corpus_ingest_trace.sqlite3",
                                           matter_ref)
            return ingest_dir(matter_ref, [_Path(source)], store,
                              make_embed_fn(gate, matter_ref))

        try:
            report = await asyncio.to_thread(_run)
        except Exception as exc:                              # noqa: BLE001
            _tui_error("ingest", exc, root=self.store.root)
            self._echo(f"/ingest failed: {exc}")
            return
        for name in report["ingested"]:
            self._echo(f"  ingested: {name}")
        for s in report["skipped"]:
            self._echo(f"  SKIPPED: {s}")
        for s in report.get("skipped_by_resume", []):
            self._echo(f"  already in corpus: {s}")
        report_path = self.store.root / "ingest-report.json"
        report_path.write_text(_json.dumps(report, indent=2, ensure_ascii=False),
                               encoding="utf-8")
        self._echo(f"ingest done — {report['chunks']} chunks for {matter_ref}"
                   f" (report {report_path})")

    def _persona_new(self, args: str) -> None:
        """/persona new name|description|tools|prompt — the old agent-authoring
        CLI, folded in. Appends the validated row to personas.yaml; the mount
        regen rides the next sync_mount."""
        import yaml as _yaml
        from harness.session.commands import build_persona_row, parse_persona_new
        try:
            name, desc, allowed, prompt = parse_persona_new(args)
            row = build_persona_row(name, desc, allowed, prompt)
        except ValueError as exc:
            _tui_error("persona_new", exc)
            self._echo(f"/persona new: {exc}")
            return
        target = Path(__file__).resolve().parents[3] / "data" / "module-e" / "personas.yaml"
        doc = _yaml.safe_load(target.read_text(encoding="utf-8"))
        doc["personas"].append(row)
        target.write_text(_yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")
        self._echo(f"persona {name} added to personas.yaml — mounts pick it up at"
                   " the next sync (the S7i canon then improves it).")

    def _providers(self) -> None:
        """/provider: the registry as data — rows, tiers, windows. Switching a
        class's provider is a routing-table edit (data/, by ruling); the shell
        shows, it does not secretly rewire."""
        from harness.bootstrap import _provider_specs
        lines = [f"{s['name']}: {s['model']} @ {s['base_url']}"
                 f" (tier {s.get('tier', '?')}, window {s.get('context_window') or '—'})"
                 for s in _provider_specs()]
        self._echo("\n".join(lines) +
                   "\n(route edits are data edits in data/routing-a1.yaml)")

    def _session_digest(self) -> str:
        """Run-2+'s memory: the last checkpoint's summary (or the last two turn
        summaries) plus the deliverables already produced — seeded into stage 1
        so a follow-up prompt continues from the last checkpoint."""
        rows = self.store.turns(self.session_id) if self.session_id else []
        if not rows:
            return ""
        parts: list[str] = []
        checkpoints = [r for r in rows if (r.display or "").startswith("/compact")]
        if checkpoints:
            parts.append("Last checkpoint: " + (checkpoints[-1].output_summary or "")[:600])
        else:
            for r in rows[-2:]:
                if r.output_summary:
                    parts.append(f"{r.agent} reported: {r.output_summary[:300]}")
        if self.base and self.session_id:
            names = [f"{f.parent.name}/{f.name}"
                     for f in (Path(self.base) / self.session_id).glob("*/*.md")
                     if ".opencode" not in f.parts]
            if names:
                parts.append("Files already produced: " + ", ".join(names[-12:]))
        return " | ".join(parts)[:2000]

    async def _dispatch_task(self, text: str) -> None:
        from harness.session.tokens import maybe_compact, window_for
        driver = getattr(self.runner, "driver", None)
        if driver is None or not self.session_id:
            self._echo("(no session to run this in — /new --matter <ref> first)")
            return
        try:
            cp = await maybe_compact(driver, self.session_id,
                                     used=self.tokens_used,
                                     window=self.context_window,
                                     safe_fill=window_for(self.provider_name)[1])
            if cp is not None:
                self._echo("auto-compacting…")
            matter_ref = driver.resume(self.session_id)["matter_ref"]
            # The chaired shell runs the FULL crew at the corpus's best serving
            # tier: a typed ```plan block scripts the stages exactly; a plain
            # goal gets the legal pipeline (data/module-e/legal_pipeline.yaml)
            # with the session digest seeded, so follow-ups continue from the
            # last checkpoint; CLOUD_PERMITTED lets the routing table send
            # analysis classes to the full-tier provider.
            task, plan_text = split_plan(text)
            rows = await self.runner.run_task(self.session_id, matter_ref, task,
                                              plan_text=plan_text,
                                              complexity="HIGH",
                                              classification="CLOUD_PERMITTED",
                                              session_digest=self._session_digest())
            self._echo(f"factory: {len(rows)} stage(s) done")
            self._echo_deliverables()
            self._echo("continue: type a follow-up (explain, change, refine — the "
                       "crew starts from the last checkpoint). If fact-questions.md "
                       "was written, answer it and ask again.")
        except Exception as exc:                              # noqa: BLE001
            _tui_error("dispatch_task", exc, root=self.store.root,
                       session=self.session_id)
            self._echo(f"task failed: {exc}")

    def _echo(self, text: str) -> None:
        try:
            pane = self.query_one("#chat", Static)
            # render() is the value accessor in Textual 8.x (there is no
            # `.renderable` attribute on Static — the smoke proved it).
            pane.update((pane.render() or "") + f"\n> {text}")
        except Exception as exc:                              # noqa: BLE001
            _tui_error("echo", exc, root=getattr(self.store, "root", None))
            return
        self._follow()
