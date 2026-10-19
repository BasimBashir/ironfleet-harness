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
