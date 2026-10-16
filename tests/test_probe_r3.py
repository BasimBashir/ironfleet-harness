# tests/test_probe_r3.py
"""Unit tests for probe_r3_tui pure helpers. Live probes never run here (house rule)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.probe_r3_tui import (  # noqa: E402
    PROBES, evidence_dir, pin_check, require_pin)


def test_evidence_dir_colonfree_and_dated():
    d = evidence_dir(ROOT / "data" / "eval")
    assert d.name.startswith("R3-RESEARCH-")
    assert ":" not in d.name and len(d.name) == len("R3-RESEARCH-YYYY-MM-DD")
    assert d.is_dir()


def test_evidence_dir_explicit_root(tmp_path):
    d = evidence_dir(tmp_path)
    assert d.parent == tmp_path and d.is_dir()


def test_pin_check_reports_not_ok_on_wrong_version(monkeypatch):
    monkeypatch.setattr("scripts.probe_r3_tui._opencode_version", lambda: "9.9.9")
    report = pin_check()
    assert report["ok"] is False and report["found"] == "9.9.9"


def test_pin_check_ok_on_pinned_version(monkeypatch):
    from harness.packaging.macdist import PINS
    monkeypatch.setattr("scripts.probe_r3_tui._opencode_version", lambda: PINS["opencode"])
    monkeypatch.setattr("scripts.probe_r3_tui._autoupdate_global", lambda: True)
    assert pin_check()["ok"] is True


def test_require_pin_exits_3_on_drift(monkeypatch, capsys):
    monkeypatch.setattr("scripts.probe_r3_tui._opencode_version", lambda: "9.9.9")
    with pytest.raises(SystemExit) as ei:
        require_pin()
    assert ei.value.code == 3
    err = capsys.readouterr().err
    assert "REFUSING TO MEASURE" in err and "9.9.9" in err  # drift report stays in the message


def test_registry_has_seven_probes():
    assert set(PROBES) == {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}
