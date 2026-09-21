# tests/test_verify_opencode_mount.py
import subprocess, sys
from pathlib import Path
import pytest

RIG = Path(__file__).resolve().parent.parent / "scripts" / "verify_opencode_mount.py"

def test_rig_reports_pin_and_expected_version():
    from scripts.verify_opencode_mount import EXPECTED_VERSION, FALLBACK
    assert EXPECTED_VERSION == "1.18.25"
    assert FALLBACK == "pin-hold"

def test_version_match_passes(monkeypatch):
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    assert rig.verify_version() == []

def test_version_drift_is_reported(monkeypatch):
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.19.0")
    problems = rig.verify_version()
    assert problems and "1.19.0" in problems[0]

def test_guard_hook_names_present():
    # The seam list the guard will hang on — checked now so S7c inherits a verified mount.
    from scripts.verify_opencode_mount import GUARD_SEAMS
    assert set(GUARD_SEAMS) >= {"tool.execute.before", "tool.execute.after",
                                "experimental.text.complete"}

def test_rig_cli_runs(monkeypatch):
    # Never touch the real opencode in a unit test — stub the version probe.
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    rc = rig.main([])
    assert rc == 0
