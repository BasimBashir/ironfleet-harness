"""S7i acceptance checks — offline parts only (house rule: drivers' main() never runs in the
suite; the live layer C2/C5 is proven by running the driver)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys_path = Path(__file__).resolve().parents[1] / "scripts"
if str(sys_path) not in sys.path:
    sys.path.insert(0, str(sys_path))

import accept_s7i  # noqa: E402


@pytest.fixture()
def run_dir(tmp_path):
    """A run dir shaped like the driver writes it: results.json with every check's evidence."""
    rd = tmp_path / "run"
    rd.mkdir(parents=True)
    (rd / "results.json").write_text(json.dumps({
        "genesis": {"agents": 13, "suites": 13, "marker_less_mount": True},
        "screen_outcome": {"status": "rolled_back"},
        "proposals": [{"agent": "adversary", "status": "rolled_back"}],
        "rejections": [{"reason": "delimiter: rejected"}, {"reason": "oversize: rejected"},
                       {"reason": "malformed: rejected"}],
        "reverts": [{"agent": "adversary", "version": 1, "bytes_match": True}],
        "trace_matters": ["agent-memory:adversary"],
        "providers_seen": ["ollama-local"],
    }), encoding="utf-8")
    return rd


def _bad(tmp_path, **overrides):
    rd = tmp_path / "bad"
    rd.mkdir(parents=True, exist_ok=True)
    doc = {"genesis": {"agents": 13, "suites": 13, "marker_less_mount": True},
           "proposals": [{"agent": "a", "status": "kept"}], "rejections": [],
           "reverts": [], "trace_matters": ["agent-memory:a"],
           "providers_seen": ["ollama-local"]}
    doc.update(overrides)
    (rd / "results.json").write_text(json.dumps(doc), encoding="utf-8")
    return rd


def test_c1_genesis_ok_and_fail(run_dir, tmp_path):
    assert accept_s7i.check_c1(run_dir) == []
    assert accept_s7i.check_c1(_bad(tmp_path, genesis={"agents": 12, "suites": 13})) != []
    assert accept_s7i.check_c1(_bad(tmp_path, genesis={"agents": 13, "suites": 13,
                                                       "marker_less_mount": False})) != []


def test_c3_rejections_recorded(run_dir, tmp_path):
    assert accept_s7i.check_c3(run_dir) == []
    assert accept_s7i.check_c3(_bad(tmp_path, rejections=[])) != []


def test_c4_revert_bytes_match(run_dir, tmp_path):
    assert accept_s7i.check_c4(run_dir) == []
    assert accept_s7i.check_c4(_bad(tmp_path, reverts=[{"agent": "x", "version": 1,
                                                        "bytes_match": False}])) != []


def test_c6_local_only(run_dir, tmp_path):
    assert accept_s7i.check_c6(run_dir) == []
    assert accept_s7i.check_c6(_bad(tmp_path, providers_seen=["ollama-local", "atria-cloud"])) != []
    assert accept_s7i.check_c6(_bad(tmp_path, trace_matters=[])) != []


def test_c3_c4_c6_composed_on_real_shape(run_dir):
    problems = (accept_s7i.check_c3(run_dir) + accept_s7i.check_c4(run_dir)
                + accept_s7i.check_c6(run_dir))
    assert problems == []


def test_main_skip_live_writes_no_verdict(run_dir, monkeypatch):
    monkeypatch.setattr(accept_s7i, "RUN_DIR", run_dir)
    rc = accept_s7i.main(["--skip-live"])
    assert rc == 0
    assert not (run_dir / "VERDICT.txt").exists()   # no verdict from the offline layer
