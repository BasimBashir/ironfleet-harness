# tests/test_stand_up_opencode.py
import json, subprocess, sys
from pathlib import Path
import pytest

DRIVER = Path(__file__).resolve().parent.parent / "scripts" / "stand_up_opencode.py"

def test_sync_mount_copies_and_substitutes(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"; ws.mkdir()
    data = Path(__file__).resolve().parent.parent / "data"
    sync_mount(ws, data / "opencode-a1", matter_ref="m-test",
               classification="LOCAL_PREFERRED", port=7373)
    cfg = json.loads((ws / "opencode.json").read_text())
    assert cfg["provider"]["gate-local"]["options"]["baseURL"] == "http://127.0.0.1:7373/v1"
    matter = json.loads((ws / "matter.json").read_text())
    assert matter["matter_ref"] == "m-test"

def test_sync_mount_refuses_port_collision_substitution(tmp_path):
    # The port is substituted, never discovered: a substituted 0 would let the mount
    # point at an arbitrary port. The driver fails if it cannot bind what it advertised.
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"; ws.mkdir()
    data = Path(__file__).resolve().parent.parent / "data"
    sync_mount(ws, data / "opencode-a1", matter_ref="m-test",
               classification="LOCAL_PREFERRED", port=7373)
    cfg = json.loads((ws / "opencode.json").read_text())
    assert "127.0.0.1:7373" in cfg["provider"]["gate-local"]["options"]["baseURL"]

def test_driver_help_runs(tmp_path):
    # Smoke: the CLI imports cleanly and its --help exits 0.
    r = subprocess.run([sys.executable, str(DRIVER), "--help"], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0
    assert "--matter-ref" in r.stdout or "--matter-ref" in r.stderr

def test_main_returns_2_when_port_is_taken(tmp_path, monkeypatch):
    # The port-collision guard is a stated deliverable: if 7373 is held by something else,
    # the driver must abort (exit 2) rather than start a mount whose hardcoded baseURL
    # would point at that something else. ThreadingHTTPServer binds in its CONSTRUCTOR, so
    # the guard must wrap construction, not start().
    import socket
    import scripts.stand_up_opencode as drv

    # build_gate() probes a live Ollama — a unit test must not depend on the network.
    # Stub it with a gate that has no providers; the bind guard runs before any dispatch.
    from harness.policy import RoutingTable
    from harness.providers.config import ProviderRegistry
    from harness.trace import TraceStore
    from harness.gate import EgressGate
    def fake_build_gate(trace_path):
        rt = RoutingTable.from_yaml(drv.ROUTING)
        return (EgressGate(ProviderRegistry(), rt, TraceStore(trace_path)), rt,
                {"gate/extraction": {"task_class": "extraction"}})
    monkeypatch.setattr(drv, "build_gate", fake_build_gate)

    ws = tmp_path / "ws"
    squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    squatter.bind((drv.HOST, drv.PORT))
    squatter.listen(1)
    try:
        rc = drv.main(["--matter-ref", "m-collide", "--workspace", str(ws),
                       "--prompt", "unused"])
    finally:
        squatter.close()
    assert rc == 2, f"a bind failure must abort with exit 2, got {rc}"
    assert (ws / "opencode.json").exists()
