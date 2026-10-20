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
from textual.containers import Horizontal
# NoMatches is query_one's failure when a widget is not mounted yet (tests build
# the app without a pilot) — the ONE expected exception in this module.
from textual.css.query import NoMatches
# Textual 8.x: TabPanel is gone; the tab-panel class is ContentTab, and it is NOT
# re-exported from textual.widgets — import from its submodule (verified against
# the installed 8.2.8: dir(textual.widgets.tabbed_content) -> ['ContentTab', ...]).
from textual.widgets import Footer, Input, Static, TabbedContent
from textual.widgets.tabbed_content import ContentTab

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


def render_jobs(rows: list[dict]) -> str:
    """The global view's text: one line per factory job — the stage ledger the
    runner writes into S7f's jobs table (spec 17 §5.4's thin slice: the pane reads
    the substrate, it adds no seam). Pure so tests and the timer share one truth."""
    if not rows:
        return "no jobs yet — give the shell a task"
    lines = []
    for r in rows:
        detail = f" — {r['detail']}" if r.get("detail") else ""
        lines.append(f"[{r['status']:>7}] {r['stage']} ({r['agent']}){detail}")
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
    #chat { width: 2fr; border: round $primary; }
    #side { width: 3fr; }
    #view { height: 1fr; border: round $accent; }
    #docs { height: 1fr; border: round $success; }
    #status { dock: bottom; height: 1; background: $panel; color: $text; }
    #prompt { dock: bottom; height: 3; }
    """

    BINDINGS = [
        # priority=True: without it, the focused TabbedContent consumes shift+tab
        # for its OWN next-tab cycle and this App-level binding never fires
        # (observed in the headless smoke: the key pressed, the mode unchanged).
        # Textual 8.x: the tuple form accepts only 2-3 strings, so a priority
        # binding must be a Binding instance with priority=True.
        Binding("shift+tab", "cycle_mode", "Cycle mode", priority=True),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, store: SessionStore, session_id: str | None = None,
                 mode: str = "agent-os", runner: object | None = None,
                 runner_factory=None) -> None:
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
        # D-T3: the meter's live numbers, refreshed from trace.db by the timer.
        self.tokens_used = 0
        self.context_window = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield Static("", id="chat")
            # Textual 8.x: ContentTab(label, content_id) REFERENCES a content widget
            # by id — it does not wrap one. The panes are declared as siblings and
            # the tabs point at them.
            with TabbedContent(id="side"):
                yield Static("", id="view")
                yield Static("", id="docs")
                yield ContentTab("Agents", "view")
                yield ContentTab("Docs", "docs")
        yield Static(self.render_status_text(), id="status")
        yield Input(placeholder="prompt an agent, or /ingest /resume /compact /mode",
                    id="prompt")
        yield Footer()

    # -- the status bar (the D-T3 meter + the always-visible mode) -------------

    def render_status_text(self) -> str:
        return render_status(mode=self.mode, session_id=self.session_id,
                             used=self.tokens_used, window=self.context_window)

    def refresh_status(self) -> None:
        try:
            self.query_one("#status", Static).update(self.render_status_text())
        except Exception as exc:                              # noqa: BLE001
            # Not mounted yet is expected (tests build the app without a pilot);
            # anything else is recorded so the bar going stale is diagnosable.
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
        """Render this session's jobs into the Agents pane. Returns the text (the
        unmounted case — tests, early compose — still gets an honest return)."""
        rows = self.store.jobs(self.session_id) if self.session_id else []
        text = render_jobs(rows)
        try:
            self.query_one("#view", Static).update(text)
        except Exception as exc:                              # noqa: BLE001
            _tui_error("refresh_view", exc)
        return text

    def _tick(self) -> None:
        """The poll: status bar + jobs pane, on one timer. Task 10 adds the trace
        read that fills the meter; Task 12 adds guard/doc reads to this hook."""
        self.refresh_status()
        self.refresh_view()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._tick)

    # -- the prompt line --------------------------------------------------------

    @on(Input.Submitted, "#prompt")
    def _submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            return
        if text == "/mode":
            self.action_cycle_mode()
        elif text.startswith("/mode "):
            self._apply_mode_command(text.split(maxsplit=1)[1])
        else:
            self._echo(text)   # the factory wiring lands with Task 7

    def _echo(self, text: str) -> None:
        try:
            pane = self.query_one("#chat", Static)
            # render() is the value accessor in Textual 8.x (there is no
            # `.renderable` attribute on Static — the smoke proved it).
            pane.update((pane.render() or "") + f"\n> {text}")
        except Exception as exc:                              # noqa: BLE001
            _tui_error("echo", exc, root=getattr(self.store, "root", None))
