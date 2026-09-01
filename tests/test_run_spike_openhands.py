# tests/test_run_spike_openhands.py
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_spike_openhands.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_spike_openhands", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_allowed_file_roundtrip(tmp_path):
    mod = _load()
    import json
    mod.write_allowed(tmp_path, ["Companies Act 1993, s 135"], block=True)
    assert json.loads((tmp_path / "allowed.json").read_text(encoding="utf-8")) == {
        "allowed": ["Companies Act 1993, s 135"], "block": True}


def test_guard_annotate_uses_handler_adapter_shape():
    """The OpenHands mount must drive OpenHandsHandlerAdapter (event dict in, mutated
    event out) — the adapter contract from guard_port.py, not a re-implementation."""
    mod = _load()
    event = {"observation": "Threshold per [Imaginary Act 2026, s 9] applies.",
             "allowed": ["Real Authority Act 1908"]}
    out = mod.guard_annotate(event)
    assert "[UNGROUNDED — not confirmed]" in out["observation"]
    assert out["_spike"]["guard_blocked"] == ["[Imaginary Act 2026, s 9]"]
    grounded = {"observation": "Per [Real Authority Act 1908] it applies.",
                "allowed": ["Real Authority Act 1908"]}
    assert mod.guard_annotate(grounded)["observation"] == grounded["observation"]
