# tests/test_crashlog.py — M11 T4: crash logs land under <store-root>/crash/.
"""Contract: capture() writes one UTF-8 log carrying the version, component,
store provenance and traceback, never raises, and trims to KEEP; the launcher's
guard writes a log when its startup dies (HARNESS_HOME redirected so the test
never touches the real store)."""
from __future__ import annotations

import harness
from harness.crashlog import KEEP, capture, run_guarded


def test_run_guarded_captures_then_reraises(tmp_path):
    import pytest

    def boom():
        raise ValueError("the drill blew up")

    with pytest.raises(ValueError):
        run_guarded(tmp_path, "launcher", boom)
    logs = list((tmp_path / "crash").glob("*.log"))
    assert len(logs) == 1
    body = logs[0].read_text(encoding="utf-8")
    assert harness.__version__ in body
    assert "component: launcher" in body
    assert "ValueError" in body and "the drill blew up" in body
    assert str(tmp_path) in body


def test_capture_survives_store_root_problems(tmp_path):
    # a Path whose crash/ cannot be created (a FILE where the dir should be):
    # capture must never raise on top of the crash it is recording
    blocker = tmp_path / "store"
    blocker.write_text("i am a file", encoding="utf-8")
    assert capture(blocker, "x") == blocker / "crash"


def test_capture_trims_to_keep(tmp_path):
    last = None
    for i in range(KEEP + 5):
        last = capture(tmp_path, f"c{i}")
    logs = list((tmp_path / "crash").glob("*.log"))
    assert len(logs) == KEEP
    # a crash loop (all inside one clock tick) may trim any but the newest:
    # the log just written always survives, that is the only per-file contract
    assert last.exists()


def test_launcher_startup_crash_writes_log(tmp_path, monkeypatch):
    from harness.ops.ironfleet_launcher import main as launcher_main

    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "home"))
    missing = tmp_path / "no-such-routing.yaml"
    try:
        launcher_main(["--routing", str(missing)])
    except Exception:
        pass  # the crash itself is expected; the log is the assertion
    logs = list((tmp_path / "home" / "crash").glob("*.log"))
    assert len(logs) == 1, "launcher startup crash must leave a local crash log"
    body = logs[0].read_text(encoding="utf-8")
    assert "component: launcher" in body and harness.__version__ in body
