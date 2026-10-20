# tests/test_session_tui.py
"""The shell skeleton (spec 17 s5.5): three panes, a status bar that ALWAYS shows
the active orchestration mode (the user's D-T2 ruling), and shift+TAB cycling the
three modes. The pure parts are tested here; the live app is smoke-run by a human
against a real terminal (Textual needs one) — never in the suite."""
from __future__ import annotations

import pytest

from harness.session.tui import MODES, IronFleetApp, cycle_mode, render_status

textual = pytest.importorskip("textual")


# -- the mode cycle (D-T2: all three, user-switchable) ------------------------

def test_cycle_mode_wraps_all_three():
    assert cycle_mode("agent-os") == "shell-drives"
    assert cycle_mode("shell-drives") == "hybrid"
    assert cycle_mode("hybrid") == "agent-os"


def test_cycle_mode_rejects_unknown():
    with pytest.raises(ValueError, match="unknown mode"):
        cycle_mode("nonsense")


def test_modes_are_the_three_ratified_ones():
    assert MODES == ("agent-os", "shell-drives", "hybrid")


# -- the status bar (always visible: mode + session + the D-T3 meter) ---------

def test_render_status_shows_mode_session_and_tokens():
    s = render_status(mode="hybrid", session_id="ses-1", used=1200, window=128000)
    assert "hybrid" in s          # the active mode is ALWAYS shown
    assert "ses-1" in s
    # thousands-separated (the readable form for six-figure windows)
    assert "1,200" in s
    assert "128,000" in s


def test_render_status_copes_with_no_session_and_no_window():
    s = render_status(mode="agent-os", session_id=None, used=0, window=0)
    assert "agent-os" in s
    assert "—" in s               # no session, no declared window: honest dashes


def test_render_status_percent_uses_the_declared_window():
    s = render_status(mode="agent-os", session_id="ses-1", used=64_000, window=128_000)
    assert "50%" in s


# -- the app object -----------------------------------------------------------

def test_app_constructs_with_a_store(tmp_path):
    from harness.session.store import SessionStore
    app = IronFleetApp(SessionStore(tmp_path))
    assert app.mode == "agent-os"             # the ratified default
    assert app.session_id is None


def test_app_set_mode_validates_and_rebuilds(tmp_path):
    from harness.session.store import SessionStore
    app = IronFleetApp(SessionStore(tmp_path))
    app.set_mode("shell-drives")
    assert app.mode == "shell-drives"
    with pytest.raises(ValueError, match="unknown mode"):
        app.set_mode("nonsense")


# -- Task 9: cycling REBUILDS the runner with the new mode ---------------------

class _StubRunner:
    def __init__(self, mode: str):
        self.mode = mode


def test_cycle_rebuilds_the_runner_with_the_new_mode(tmp_path):
    """D-T2: the active mode is not a label — the shell's runner is rebuilt so the
    NEXT task executes under the newly selected orchestration."""
    from harness.session.store import SessionStore
    made: list[str] = []

    def factory(mode: str) -> _StubRunner:
        made.append(mode)
        return _StubRunner(mode)

    app = IronFleetApp(SessionStore(tmp_path), runner_factory=factory)
    app.action_cycle_mode()
    assert app.mode == "shell-drives"
    assert isinstance(app.runner, _StubRunner) and app.runner.mode == "shell-drives"
    app.action_cycle_mode()
    assert app.mode == "hybrid" and app.runner.mode == "hybrid"
    assert made == ["shell-drives", "hybrid"]


def test_cycle_without_a_factory_keeps_a_none_runner(tmp_path):
    from harness.session.store import SessionStore
    app = IronFleetApp(SessionStore(tmp_path))
    app.action_cycle_mode()
    assert app.mode == "shell-drives" and app.runner is None


def test_slash_mode_with_a_name_sets_it_explicitly(tmp_path):
    from harness.session.store import SessionStore
    app = IronFleetApp(SessionStore(tmp_path))
    app._apply_mode_command("hybrid")
    assert app.mode == "hybrid"
    # an unknown name: recorded and echoed, never a crash of the submit handler
    app._apply_mode_command("nope")            # must not raise
    assert app.mode == "hybrid"                # unchanged


# -- the global view pane: the session's tasks (the jobs table) ----------------

def test_render_jobs_shows_stage_agent_status():
    from harness.session.tui import render_jobs
    rows = [{"stage": "gather", "agent": "hunter", "status": "running", "detail": ""},
            {"stage": "gather", "agent": "hunter", "status": "done",
             "detail": "found A and B"}]
    s = render_jobs(rows)
    assert "gather" in s and "hunter" in s
    assert "running" in s and "done" in s
    assert "found A and B" in s
    # the status column is readable at a glance — one line per job
    assert len(s.strip().splitlines()) == 2


def test_render_jobs_empty_is_honest():
    from harness.session.tui import render_jobs
    assert "no jobs" in render_jobs([])


def test_refresh_view_renders_the_sessions_jobs(tmp_path):
    """The pane reads the S7f jobs table through the store — visibility from the
    substrate, no new seam. Returns the rendered text (and updates the pane when
    mounted; unmounted is the expected NoMatches, recorded not raised)."""
    from harness.session.store import SessionStore
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    store.add_job(sid, "gather", "hunter", "running")
    store.add_job(sid, "draft", "clerk", "done", detail="handoff.md")
    app = IronFleetApp(store, session_id=sid)
    text = app.refresh_view()
    assert "gather" in text and "hunter" in text
    assert "done" in text and "handoff.md" in text


def test_refresh_view_with_no_session_is_empty(tmp_path):
    from harness.session.store import SessionStore
    app = IronFleetApp(SessionStore(tmp_path))
    assert "no jobs" in app.refresh_view()


# -- Task 11: the meter fills from live trace rows on the poll -------------------

def _trace_fixture(tmp_path, session_id, store=None):
    """Trace rows + the session's JSONL turns carrying their trace_refs — the
    shell's real join key (the live mount does not carry session identity to the
    gate, so by_session would read empty; the refs are the meter's key)."""
    from harness.session.store import TurnRow
    from harness.trace import DispatchRecord, TraceStore
    trace = TraceStore(tmp_path / "trace.db")
    rec = lambda agent, i, o: DispatchRecord(          # noqa: E731 — fixture shape
        matter_ref="m1", task_class="extraction", classification="LOCAL_PREFERRED",
        provider="nvidia-nim", model="step-5", tokens_in=i, tokens_out=o,
        agent=agent, session_id=session_id)
    id1 = trace.append(rec("hunter", 1000, 500))
    id2 = trace.append(rec("clerk", 250, 100))
    if store is not None:
        for rid in (id1, id2):
            store.append_turn(TurnRow(ts="t", session_id=session_id, matter_ref="m1",
                                      display="", agent="hunter", tools_used=[],
                                      output_summary="", docs_touched=[],
                                      trace_refs=[rid]))
    return trace


def test_tick_fills_the_meter_from_the_trace(tmp_path):
    """The poll reads trace.db (F2: never the event stream) joined on the
    session's own recorded refs, and the window from the provider row."""
    from harness.session.store import SessionStore
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    trace = _trace_fixture(tmp_path, sid, store=store)
    app = IronFleetApp(store, session_id=sid, trace=trace, provider_name="nvidia-nim")
    app._tick()
    assert app.tokens_used == 1000 + 500 + 250 + 100
    assert app.context_window == 128_000
    assert "1,850" in app.render_status_text() and "128,000" in app.render_status_text()


def test_tick_without_trace_or_session_stays_at_zero(tmp_path):
    from harness.session.store import SessionStore
    app = IronFleetApp(SessionStore(tmp_path))
    app._tick()
    assert app.tokens_used == 0 and app.context_window == 0


# -- Task 12: the view pane shows the agents, the doc pane shows the diff -------

def test_render_agents_one_line_per_agent():
    from harness.session.tui import render_agents
    rows = [{"agent": "hunter", "provider": "nvidia-nim", "model": "step-5",
             "verified": 1, "tokens_in": 100, "tokens_out": 50,
             "guard_flags": 3, "last_status": "ok"},
            {"agent": "clerk", "provider": "ollama-local",
             "model": "thomson1-chat:latest", "verified": 0, "tokens_in": 37,
             "tokens_out": 23, "guard_flags": 0, "last_status": "refused"}]
    s = render_agents(rows)
    assert "hunter" in s and "clerk" in s
    assert "nvidia-nim" in s and "ollama-local" in s      # the honest tier read
    assert "refused" in s
    assert len(s.strip().splitlines()) == 2


def test_render_agents_empty():
    from harness.session.tui import render_agents
    assert "no agents" in render_agents([])


def test_tick_renders_agents_into_the_view_text(tmp_path):
    from harness.session.store import SessionStore
    from harness.session.tui import IronFleetApp
    store = SessionStore(tmp_path)
    sid = store.new_session("m1")
    trace = _trace_fixture(tmp_path, sid, store=store)    # turns carry the refs
    app = IronFleetApp(store, session_id=sid, trace=trace,
                       provider_name="nvidia-nim")
    text = app.refresh_view()
    assert "hunter" in text and "clerk" in text           # agents, not just jobs


def test_docs_text_shows_the_diff_when_a_workspace_is_set(tmp_path):
    """The doc pane reads the injected workspace's git diff (the acceptance
    driver injects the workspace it watches); none set -> an honest dash. The
    watched file must be TRACKED and modified — ls-files and plain git diff are
    the substrate, and an untracked file is invisible to both."""
    import subprocess
    from harness.session.store import SessionStore
    from harness.session.tui import IronFleetApp
    app = IronFleetApp(SessionStore(tmp_path))
    assert "no workspace" in app._docs_text()
    ws = tmp_path / "ws"
    ws.mkdir()
    def git(*args):
        subprocess.run(["git", *args], cwd=str(ws), check=True, capture_output=True)
    git("-c", "user.email=t@t", "-c", "user.name=t", "init", "-q")
    (ws / "draft.md").write_text("v1\n", encoding="utf-8")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1")
    (ws / "draft.md").write_text("v2 — agent edit\n", encoding="utf-8")
    app2 = IronFleetApp(SessionStore(tmp_path), docs_ws=ws)
    text = app2._docs_text()
    assert "draft.md" in text and "v2 — agent edit" in text


def test_split_plan_moves_the_fenced_block_to_plan_text():
    from harness.session.tui import split_plan
    text = ("Run the full case crew.\n```plan\n"
            "research|hunter|map the precedent\n"
            "draft|clerk|write the memo\n```\nGo.")
    task, plan = split_plan(text)
    assert task == "Run the full case crew.\n\nGo."
    assert plan.startswith("```plan") and "b|clerk" not in plan
    assert "draft|clerk|write the memo" in plan


def test_split_plan_without_a_block_is_the_task_verbatim():
    from harness.session.tui import split_plan
    assert split_plan("just process the docs") == ("just process the docs", "")
