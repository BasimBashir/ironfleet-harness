# tests/test_mount_a1.py
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "opencode-a1"

def test_mount_has_exactly_one_provider():
    cfg = json.loads((DATA / "opencode.json").read_text())
    providers = cfg["provider"]
    assert list(providers) == ["gate-local"], \
        f"OpenCode must have exactly one provider; found {list(providers)}"

def test_mount_provider_points_at_loopback_proxy():
    cfg = json.loads((DATA / "opencode.json").read_text())
    p = cfg["provider"]["gate-local"]
    # baseURL is only valid under "options"; a top-level key is ignored at runtime and the
    # SDK requests "undefined/chat/completions" (opencode 1.18.25, ProviderConfig schema).
    assert p["options"]["baseURL"] == "http://127.0.0.1:7373/v1"
    assert "baseURL" not in p
    assert p["npm"] == "@ai-sdk/openai-compatible"

def test_mount_hardens_egress():
    cfg = json.loads((DATA / "opencode.json").read_text())
    assert cfg["share"] == "disabled"
    assert cfg["autoupdate"] is False
    # No builtin cloud provider may carry a key — a builtin with no credential fails closed.
    for name, spec in cfg["provider"].items():
        assert "apiKey" not in spec and spec.get("options", {}).get("apiKey") is None

def test_mount_models_match_routing_aliases():
    from harness.alias import load_aliases
    aliases = load_aliases(Path(__file__).resolve().parent.parent / "data" / "routing-a1.yaml")
    cfg = json.loads((DATA / "opencode.json").read_text())
    assert set(cfg["provider"]["gate-local"]["models"]) == set(aliases)

def test_mount_disables_title_generation():
    # opencode fires a separate "title generator" LLM call per session — a second dispatch
    # the caller never asked for (observed live: extraction landed as 2 rows, one of them a
    # ~4k-token title-gen prompt with a 22-token reply). The mount must turn it off.
    cfg = json.loads((DATA / "opencode.json").read_text())
    assert cfg["agent"]["title"]["disable"] is True


def test_matter_example_shape():
    m = json.loads((DATA / "matter.example.json").read_text())
    assert set(m) >= {"matter_ref", "classification"}
    assert m["classification"] in ("LOCAL_ONLY", "LOCAL_PREFERRED", "CLOUD_PERMITTED")
