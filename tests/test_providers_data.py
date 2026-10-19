# tests/test_providers_data.py
"""data/providers.yaml is the R3 provider-registry-as-data: one row = url + model +
engine + kind, so a user swapping provider/model/url edits DATA, never code. These
tests lock the coupling (url travels with the provider), the env-override escape
hatch, and the fail-loud contract."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from harness.bootstrap import _provider_specs

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "providers.yaml"


def test_every_row_carries_url_model_engine_together():
    """The 'url changes with the provider' directive, asserted structurally: no row
    can name a model without its base_url and engine — a swap is one row edit."""
    specs = _provider_specs(REGISTRY)
    assert {"ollama-local", "ollama-embed", "qwen-local", "llama-rerank",
            "nvidia-nim"} == {s["name"] for s in specs}
    for s in specs:
        assert s["base_url"].startswith("http"), s
        assert s["model"], s
        assert s["engine"], s
    nim = next(s for s in specs if s["name"] == "nvidia-nim")
    assert nim["engine"] == "cloud"
    assert nim["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert nim["model"] == "stepfun-ai/step-5-preview"
    # declared revision travels in the row (the verified rule's pin)
    assert nim["declared"]["weights_revision"] == "stepfun-ai/step-5-preview"


def test_env_override_swaps_model_and_url_without_a_file_edit(monkeypatch):
    """The quick-swap surface: IRONFLEET_<NAME>_MODEL / _URL override the row — a user
    swapping provider AND model AND target url in one shot, no code touched."""
    monkeypatch.setenv("IRONFLEET_NVIDIA_NIM_MODEL", "moonshotai/kimi-k2-thinking")
    monkeypatch.setenv("IRONFLEET_NVIDIA_NIM_URL", "https://example.invalid/v1")
    nim = next(s for s in _provider_specs(REGISTRY) if s["name"] == "nvidia-nim")
    assert nim["model"] == "moonshotai/kimi-k2-thinking"
    assert nim["base_url"] == "https://example.invalid/v1"


def test_missing_registry_file_fails_loud(tmp_path):
    """Never silently probe nothing — a stranded distribution must fail at build,
    exactly like cli.default_routing's routing-YAML check."""
    with pytest.raises(FileNotFoundError):
        _provider_specs(tmp_path / "absent.yaml")


def test_empty_registry_fails_loud(tmp_path):
    bad = tmp_path / "empty.yaml"
    bad.write_text("providers: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'providers' rows"):
        _provider_specs(bad)


def test_repo_registry_parses_as_yaml():
    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(doc.get("providers"), list) and doc["providers"]
