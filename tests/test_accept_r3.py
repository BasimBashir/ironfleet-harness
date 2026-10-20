# tests/test_accept_r3.py
"""Task 14: the scripted acceptance driver's pure assembly — argv shapes and the
checkpoint-row matcher. The LIVE checks (spawns, ingest, kill/resume) are the
driver's job on a quiet box and never run in the suite (house rule)."""
from __future__ import annotations

import pytest

from scripts.accept_r3 import (
    anchor_regex,
    is_checkpoint_row,
    turn_argv_for_check,
)


def test_anchor_regex_extracts_the_canary_token():
    """The acceptance task plants a token the agent must echo — the matcher must
    find it in a JSON-escaped stream (p3's logs show text parts are JSON)."""
    import re
    rx = anchor_regex("R3-ANCHOR-7Q")
    assert rx.search('{"part":{"type":"text","text":"here: R3-ANCHOR-7Q\\\\n"}')
    assert re.search(rx, "plain R3-ANCHOR-7Q in body")
    assert not rx.search("nothing here")
    # token-shaped: a bare regex must not match a truncated prefix
    assert not rx.search("R3-ANCHOR-")


def test_is_checkpoint_row_matches_the_marker():
    from harness.session.store import TurnRow
    ok = TurnRow(ts="t", session_id="s", matter_ref="m", display="/compact note",
                 agent="compact", tools_used=[], output_summary="", docs_touched=[],
                 trace_refs=[])
    assert is_checkpoint_row(ok)
    plain = TurnRow(ts="t", session_id="s", matter_ref="m", display="task",
                    agent="hunter", tools_used=[], output_summary="", docs_touched=[],
                    trace_refs=[])
    assert not is_checkpoint_row(plain)


def test_turn_argv_is_the_proven_shape():
    argv = turn_argv_for_check("hunter", "R3-ANCHOR-7Q")
    assert argv[:4] == ["run", "--agent", "hunter", "--model"]
    assert argv[-1] == "Reply with exactly R3-ANCHOR-7Q and nothing else."
    assert "--session" not in argv                        # a fresh turn continues nothing


def test_turn_argv_carries_the_continuation():
    argv = turn_argv_for_check("hunter", "R3-ANCHOR-7Q",
                               continue_session="ses-opencode-continue-x")
    i = argv.index("--session")
    assert argv[i + 1] == "ses-opencode-continue-x"
    assert argv[-1] == "Reply with exactly R3-ANCHOR-7Q and nothing else."
