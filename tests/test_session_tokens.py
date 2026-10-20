# tests/test_session_tokens.py
"""Task 10 (spec 17 s5.5, D-T3): the token meter reads trace.db (P5 measured the
event stream's token counts as ZEROS — the trace carries the real ones), aggregates
ROWS by session (F7: opencode emits 1-2 dispatches per run, so counting rows lies),
splits per agent (F1's identity columns), and compacts at the provider row's
safe_fill — the model's measured reliability, never a round number."""
from __future__ import annotations

import pytest

from harness.session.tokens import (
    COMPACT_MARKER,
    COMPACT_MODEL,
    build_checkpoint_row,
    should_compact,
    usage_for_session,
    window_for,
)


# -- the compact trigger (safe_fill, not 80%) -----------------------------------

def test_should_compact_uses_safe_fill_not_a_round_number():
    assert should_compact(102_400, 128_000, 0.8) is True      # exactly at the fill
    assert should_compact(102_300, 128_000, 0.8) is False     # just under it
    assert should_compact(5, 0, 0.8) is False                 # no declared window -> never
    assert should_compact(200, 100, 0.8) is True              # past it stays True


# -- the provider row is the window's source ------------------------------------

def test_window_for_reads_the_provider_row():
    w, fill = window_for("nvidia-nim")
    assert w == 128000 and fill == 0.8


def test_window_for_unknown_or_undeclared_is_honest_zero():
    assert window_for("no-such-provider") == (0, 0.8)         # meter shows used/—


# -- the per-session, per-agent ledger (F7 aggregate, F1 split) -----------------

def _rec(**kw):
    from harness.trace import DispatchRecord
    base = dict(matter_ref="m1", task_class="extraction", classification="LOCAL_PREFERRED",
                provider="nvidia-nim", model="step-5", tokens_in=10, tokens_out=5)
    base.update(kw)
    return DispatchRecord(**base)


def test_usage_aggregates_rows_and_splits_per_agent(tmp_path):
    from harness.trace import TraceStore
    trace = TraceStore(tmp_path / "t.db")
    trace.append(_rec(session_id="ses-1", agent="hunter", tokens_in=100, tokens_out=50))
    trace.append(_rec(session_id="ses-1", agent="hunter", tokens_in=30, tokens_out=20))
    trace.append(_rec(session_id="ses-1", agent="clerk", tokens_in=7, tokens_out=3,
                      tokens_cache=9))
    trace.append(_rec(session_id="ses-2", agent="hunter", tokens_in=999, tokens_out=999))
    u = usage_for_session(trace, "ses-1")
    assert u["in"] == 137 and u["out"] == 73 and u["cache"] == 9
    assert u["per_agent"]["hunter"] == {"in": 130, "out": 70, "cache": 0}
    assert u["per_agent"]["clerk"] == {"in": 7, "out": 3, "cache": 9}
    assert "hunter" not in {a for a in u["per_agent"] if u["per_agent"][a]["in"] == 999}


def test_usage_of_an_empty_session_is_zeros(tmp_path):
    from harness.trace import TraceStore
    u = usage_for_session(TraceStore(tmp_path / "t.db"), "ses-none")
    assert u == {"in": 0, "out": 0, "cache": 0, "per_agent": {}}


# -- the checkpoint row (/compact's JSONL shape) ---------------------------------

def test_checkpoint_row_carries_the_marker_and_note():
    row = build_checkpoint_row(session_id="ses-1", matter_ref="m1",
                               summary="the handoff summary", note="after drafting",
                               ts="2026-10-20T00:00:00Z")
    assert row.display.startswith(COMPACT_MARKER) and "after drafting" in row.display
    assert row.output_summary == "the handoff summary"
    assert row.session_id == "ses-1" and row.matter_ref == "m1"


def test_compact_dispatches_through_the_summarization_alias():
    """The compaction turn rides the gate's summarization class — a typo in this
    alias would 403 at dispatch, but only live; the constant is the lock."""
    assert COMPACT_MODEL == "gate-local/gate/summarization"
    assert COMPACT_MARKER == "/compact"


# -- maybe_compact: the shell's pre-dispatch gate (Task 11) ----------------------

class _StubDriver:
    """Records whether the real compaction ran; the injectable seam the plan
    names — the shell never compacts directly, it asks this helper."""

    def __init__(self):
        self.calls: list[str] = []


def test_maybe_compact_fires_only_past_the_fill(monkeypatch):
    import asyncio
    import harness.session.tokens as tokens

    async def fake_compact(driver, session_id, note=""):
        driver.calls.append(session_id)
        return "checkpoint"

    monkeypatch.setattr(tokens, "compact_session", fake_compact)
    driver = _StubDriver()
    out = asyncio.run(tokens.maybe_compact(driver, "ses-1", used=102_400,
                                           window=128_000, safe_fill=0.8))
    assert out == "checkpoint" and driver.calls == ["ses-1"]
    out = asyncio.run(tokens.maybe_compact(driver, "ses-1", used=1_000,
                                           window=128_000, safe_fill=0.8))
    assert out is None and driver.calls == ["ses-1"]      # not called again
    out = asyncio.run(tokens.maybe_compact(driver, "ses-1", used=999_999,
                                           window=0, safe_fill=0.8))
    assert out is None                                    # no window -> never
