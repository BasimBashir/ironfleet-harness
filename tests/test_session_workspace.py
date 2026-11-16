# tests/test_session_workspace.py
"""Per-agent workspace isolation (R3 finding F4) + the supervised spawn helper
(F8 watchdog, F9 colon-free). The pure path/id parts are tested here; the live
spawn is exercised by later tasks' acceptance drivers, never in the suite."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.session.workspace import (
    agent_workspace,
    opencode_data_dir,
    spawn_env,
)


def test_agent_workspace_rejects_colons(tmp_path):
    with pytest.raises(ValueError, match="colon-free"):
        agent_workspace(tmp_path, "ses:1", "hunter", "m1")


def test_agent_workspace_rejects_colon_in_agent_name(tmp_path):
    with pytest.raises(ValueError, match="colon-free"):
        agent_workspace(tmp_path, "ses-1", "bad:agent", "m1")


def test_agent_workspace_rejects_colon_in_matter(tmp_path):
    with pytest.raises(ValueError, match="colon-free"):
        agent_workspace(tmp_path, "ses-1", "hunter", "m:1")


def test_agent_workspace_shape_and_creation(tmp_path):
    ws = agent_workspace(tmp_path, "ses-20261019-abcd1234", "hunter", "m1")
    assert ws == tmp_path / "ses-20261019-abcd1234" / "hunter"
    assert ws.is_dir()


def test_agent_workspace_refuses_a_session_dir_holding_another_matter(tmp_path):
    """The 2026-11-16 leak: one shared session dir served two matters. A dir whose
    workspaces carry another matter's record is refused, not adopted."""
    import json
    a = agent_workspace(tmp_path, "api-admin", "ingestor-stage-intake", "m-a")
    (a / "matter.json").write_text(json.dumps({"matter_ref": "m-a"}), encoding="utf-8")
    assert agent_workspace(tmp_path, "api-admin", "hunter-stage-research", "m-a").is_dir()
    with pytest.raises(PermissionError, match="m-a"):
        agent_workspace(tmp_path, "api-admin", "strategist", "m-b")
    assert not (tmp_path / "api-admin" / "strategist").exists()


def test_opencode_data_dir_shape_and_creation(tmp_path):
    dd = opencode_data_dir(tmp_path, "ses-20261019-abcd1234", "hunter")
    assert dd == tmp_path / "ses-20261019-abcd1234" / "hunter" / ".opencode-data"
    assert dd.is_dir()


def test_opencode_data_dir_rejects_colons(tmp_path):
    with pytest.raises(ValueError, match="colon-free"):
        opencode_data_dir(tmp_path, "ses:1", "hunter")


def test_turn_argv_carries_the_continuation_session():
    """F6's consuming end: a resume turn drives --session <id> (P3-proven seam).
    Without it the stored opencode_session id is printed by --resume and used by
    nothing — /resume would fork a contextless session every time."""
    from harness.session.workspace import turn_argv
    fresh = turn_argv("hunter", "gate-local/gate/extraction", "hello", None)
    assert "--session" not in fresh
    assert fresh[:4] == ["run", "--agent", "hunter", "--model"]
    cont = turn_argv("hunter", "gate-local/gate/extraction", "hello",
                     "ses_eac83f117ffelNO1uBTK8B52hb")
    i = cont.index("--session")
    assert cont[i + 1] == "ses_eac83f117ffelNO1uBTK8B52hb"
    assert cont[-1] == "hello"                            # flatten_prompt last, always


def test_spawn_env_scrubs_bearers_and_pins_pwd():
    """F8/S7b finding S1: the child must run without provider credentials (a dirty
    env lights up opencode's builtin providers — 275 foreign models observed live)
    and with PWD re-pinned to the workspace (instance resolution reads PWD).

    Asserts the load-bearing discriminations, not tautologies: a planted bearer
    key is genuinely absent while a planted non-bearer marker survives, so the
    test fails if the scrub ever stops biting."""
    import os

    planted = ("ANTHROPIC_API_KEY", "dirty", True)      # scrub list
    marker = ("IRONFLEET_TEST_MARKER", "kept", False)   # must survive
    for name, val, _ in (planted, marker):
        os.environ[name] = val
    try:
        env = spawn_env(Path("C:/ws"))
        # the bearer key is GONE (this is the assertion that matters)
        assert planted[0] not in env
        # a non-bearer key survives — proves the scrub is selective, not blanket
        assert env.get(marker[0]) == marker[1]
        assert env["PWD"] == str(Path("C:/ws"))
        assert env["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
        assert env["OPENCODE_DISABLE_TELEMETRY"] == "1"
        assert "DO_NOT_TRACK" in env
    finally:
        del os.environ[planted[0]]
        del os.environ[marker[0]]
