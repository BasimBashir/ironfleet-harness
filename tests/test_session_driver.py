# tests/test_session_driver.py
"""The session driver (spec 17 s5.1/slice 2): the non-TUI path that starts a
session, runs ONE agent turn through the proven substrate, and lands a TurnRow in
the JSONL. Pure parts (row assembly, resume resolution, the CLI argv) are tested
here; the live spawn is exercised by the acceptance drivers, never the suite."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.session.driver import build_turn_row, resolve_resume_target, session_cli_argv
from harness.session.store import SessionStore, TurnRow


# -- the turn row (the JSONL's one shape) -------------------------------------

def test_build_turn_row_from_events():
    """A turn row carries what the acceptance checks read by name: the tools the
    agent used, the final text, and the trace rows this turn produced."""
    events = [
        {"type": "tool_use", "part": {"type": "tool", "tool": "read"}},
        {"type": "text", "part": {"type": "text", "text": "ignored mid-stream"}},
        {"type": "tool_use", "part": {"type": "tool", "tool": "write"}},
        {"type": "text", "part": {"type": "text", "text": "the final answer"}},
    ]
    row = build_turn_row(session_id="ses-1", matter_ref="m1", agent="hunter",
                         events=events, trace_refs=[7], ts="2026-10-19T00:00:00Z")
    assert row.agent == "hunter"
    assert row.tools_used == ["read", "write"]        # in call order, both levels
    assert row.output_summary == "the final answer"   # the LAST text part wins
    assert row.trace_refs == [7]
    assert row.session_id == "ses-1" and row.matter_ref == "m1"


def test_build_turn_row_tolerates_no_events():
    """An empty/failed turn still records — an honest row beats a missing one."""
    row = build_turn_row(session_id="ses-1", matter_ref="m1", agent="hunter",
                         events=[], trace_refs=[], ts="2026-10-19T00:00:00Z")
    assert row.tools_used == [] and row.output_summary == ""


# -- resume resolution (P3: --continue is dead; we own last-session mapping) --

def test_resolve_resume_target_last_and_id(tmp_path):
    s = SessionStore(tmp_path)
    a = s.new_session("m1")
    b = s.new_session("m2")
    assert resolve_resume_target(s, "last") == s.last()
    assert resolve_resume_target(s, a) == a
    assert resolve_resume_target(s, b) == b


def test_resolve_resume_target_unknown_fails_loud(tmp_path):
    s = SessionStore(tmp_path)
    with pytest.raises(ValueError, match="unknown session"):
        resolve_resume_target(s, "ses-nope")
    with pytest.raises(ValueError, match="colon-free"):
        resolve_resume_target(s, "bad:ref")           # the registry-name rule bites first


# -- the CLI argv assembly (the non-TUI entry point) --------------------------

def test_session_cli_argv_shapes():
    assert session_cli_argv(["--new", "--matter", "m1"]) == ["--new", "--matter", "m1"]
    turn = session_cli_argv(["--turn", "--agent", "hunter", "--prompt", "x"])
    assert turn == ["--turn", "--agent", "hunter", "--prompt", "x"]
    assert session_cli_argv(["--list"]) == ["--list"]
    assert session_cli_argv(["--resume", "last"]) == ["--resume", "last"]


def test_session_cli_rejects_colons_in_matter():
    with pytest.raises(ValueError, match="colon-free"):
        session_cli_argv(["--new", "--matter", "bad:ref"])


def test_run_turn_abandons_a_wedged_spawn_instead_of_freezing(tmp_path):
    """The 2026-10-21 live freeze: one wedged stage (orphaned grandchild holding
    the stdout pipe) froze the TUI's event loop for ~an hour. run_turn now bounds
    the spawn: a turn that outlives TURN_TIMEOUT_S FAILS RECORDED and the row
    lands — the shell carries on."""
    import asyncio
    from harness.session.driver import SessionDriver
    from harness.session.store import SessionStore

    store = SessionStore(tmp_path)
    drv = SessionDriver(store, tmp_path / "workspaces")
    drv.TURN_TIMEOUT_S = 1                      # the test's own bound
    sid = store.new_session("m1")

    class _Wedged:
        """A spawn that never returns — the pipe-deadlock signature."""
        def workspace_for(self, *a, **kw):
            return tmp_path / "ws"
        def spawn_env(self, ws):
            return {}
        def _trace_ids(self, p):
            return set()
    # patch the module-level pieces run_turn uses
    import harness.session.driver as drv_mod

    async def never(*a, **kw):
        await asyncio.sleep(30)

    # patch asyncio.to_thread (the REAL seam run_turn calls) — a patch of
    # spawn_session alone would miss a broken to_thread reference, which is
    # exactly how the 2026-10-21 NameError slipped past this test once.
    orig_tt, drv_mod.asyncio.to_thread = drv_mod.asyncio.to_thread, never
    orig, drv_mod.spawn_session = drv_mod.spawn_session, never
    orig_ids, drv_mod._trace_ids = drv_mod._trace_ids, lambda p: set()
    orig_ws, drv.workspace_for = drv.workspace_for, lambda *a, **k: tmp_path / "ws"
    try:
        row = asyncio.run(asyncio.wait_for(
            drv.run_turn(sid, "m1", "clerk", "do it"), timeout=10))
        assert row.output_summary == "" and row.agent == "clerk"
        turns = store.turns(sid)
        assert len(turns) == 1                   # the row LANDED either way
    finally:
        drv_mod.asyncio.to_thread = orig_tt      # global module: MUST restore
        drv_mod.spawn_session = orig
        drv_mod._trace_ids = orig_ids
        drv.workspace_for = orig_ws


def test_run_turn_happy_path_records_no_error(tmp_path):
    """The catch-all except means ANY reference slip in the spawn block lands as
    a silent recorded failure and '9 stages done'. The happy path must complete
    with ZERO error-log entries — that is what proves the block is clean."""
    import asyncio
    from harness.session.driver import SessionDriver
    from harness.session.store import SessionStore
    import harness.session.driver as drv_mod

    store = SessionStore(tmp_path)
    drv = SessionDriver(store, tmp_path / "workspaces")
    sid = store.new_session("m1")

    async def fast_spawn(*a, **kw):
        return 0, [{"type": "text", "part": {"type": "text", "text": "ok"}}], "ses_x"

    orig_tt = drv_mod.asyncio.to_thread
    orig_ws = drv.workspace_for
    orig_ids = drv_mod._trace_ids
    drv_mod.asyncio.to_thread = fast_spawn
    drv.workspace_for = lambda *a, **k: tmp_path / "ws"
    drv_mod._trace_ids = lambda p: set()
    try:
        row = asyncio.run(drv.run_turn(sid, "m1", "clerk", "do it"))
        assert row.output_summary == "ok"
        err = tmp_path / "errors.jsonl"
        assert not err.exists() or "run_turn.spawn" not in err.read_text(encoding="utf-8"), \
            "a happy-path turn must not record a spawn error — some reference slipped"
    finally:
        drv_mod.asyncio.to_thread = orig_tt
        drv_mod._trace_ids = orig_ids
        drv.workspace_for = orig_ws
