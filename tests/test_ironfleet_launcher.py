"""Launcher tests: store resolution + bind, bind-failure exit 2, interrupt exits 0.

build_gate is stubbed (house rule: the suite never probes real Ollama); the proxy is
real, on an ephemeral port.
"""
from __future__ import annotations

import socket
import threading

import pytest

import harness.bootstrap
import harness.ops.ironfleet_launcher as launcher


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def stub_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(harness.bootstrap, "build_gate",
                        lambda trace, routing: (object(), {}, {}))
    monkeypatch.setattr(launcher, "build_scheduler", lambda: object())
    routing = tmp_path / "routing.yaml"
    routing.write_text("aliases: {}", encoding="utf-8")
    return routing


def _run_until_interrupt(monkeypatch):
    def _raise(_s):
        raise KeyboardInterrupt
    monkeypatch.setattr(launcher.time, "sleep", _raise)


def test_launcher_resolves_store_binds_then_exits_0(monkeypatch, tmp_path, stub_gate,
                                                    capsys):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "store"))
    _run_until_interrupt(monkeypatch)
    rc = launcher.main(["--routing", str(stub_gate), "--port", str(_free_port())])
    assert rc == 0
    assert (tmp_path / "store" / "matters").is_dir()
    assert "(source: HARNESS_HOME)" in capsys.readouterr().err


def test_launcher_bind_failure_returns_2(monkeypatch, tmp_path, stub_gate):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "store"))
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        rc = launcher.main(["--routing", str(stub_gate),
                            "--port", str(blocker.getsockname()[1])])
    finally:
        blocker.close()
    assert rc == 2


def test_launcher_requires_routing(monkeypatch, tmp_path, stub_gate):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "store"))
    monkeypatch.delenv("IRONFLEET_ROUTING", raising=False)
    with pytest.raises(SystemExit):
        launcher.main([])


def test_launcher_two_instances_do_not_share_a_port(tmp_path, stub_gate, monkeypatch):
    # The real contract the bind guard protects: a second launcher on a taken port
    # refuses instead of silently sharing it (SO_REUSEADDR double-bind — the defect
    # this test caught in _ExclusiveBindServer's absence).
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path / "store"))
    port = _free_port()
    stop = threading.Event()

    def _sleep(_s):
        if stop.wait(5):
            raise KeyboardInterrupt
    monkeypatch.setattr(launcher.time, "sleep", _sleep)
    first = threading.Thread(
        target=lambda: launcher.main(["--routing", str(stub_gate), "--port", str(port)]),
        daemon=True)
    first.start()
    stop.wait(5)
    try:
        assert launcher.main(["--routing", str(stub_gate), "--port", str(port)]) == 2
    finally:
        stop.set()
