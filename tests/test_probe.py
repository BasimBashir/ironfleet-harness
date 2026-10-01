import pytest
from harness.providers.probe import register_provider, ProbeResult
from harness.providers.config import ProviderRegistry

@pytest.mark.asyncio
async def test_register_full_admission():
    reg = ProviderRegistry(); keys: dict[str, str] = {}
    async def fetch(url, headers):
        if url.endswith("/models"): return {"data": [{"id": "qwen-30b"}]}
        if url.endswith("/health"): return {"model": "qwen-30b", "revision": "rev-1"}
        return None
    res = await register_provider("mini1", "http://mini1:8080/v1", "sk", model="qwen-30b",
                                  engine="mlx-lm", declared={"weights_revision": "rev-1"},
                                  registry=reg, fetch=fetch, keychain_set=keys)
    assert isinstance(res, ProbeResult)
    assert res.reachable and res.auth_ok and res.models == ["qwen-30b"]
    assert res.provenance.verified and res.admission == "full"
    assert reg.get("mini1").admitted == "full" and reg.get("mini1").model == "qwen-30b" and reg.get("mini1").models == ["qwen-30b"]
    assert keys["mini1"] == "sk"

@pytest.mark.asyncio
async def test_register_unreachable_reports_and_does_not_store_key():
    reg = ProviderRegistry(); keys: dict[str, str] = {}
    async def fetch(url, headers): return None
    res = await register_provider("dead", "http://dead:9/v1", "sk", engine="mlx-lm",
                                  registry=reg, fetch=fetch, keychain_set=keys)
    assert not res.reachable and res.admission == "refused"
    assert "dead" not in keys and reg.list() == []

@pytest.mark.asyncio
async def test_register_remembers_discovered_backend():
    # llamacpp branch: /props build_info is a real executing backend — the probe's finding
    # must survive onto the registry entry instead of being dropped at upsert (S7d).
    reg = ProviderRegistry(); keys: dict[str, str] = {}
    async def fetch(url, headers):
        if url.endswith("/models"): return {"data": [{"id": "qwen-30b"}]}
        if url.endswith("/props"): return {"build_info": "b1234"}
        return None
    await register_provider("mini1", "http://mini1:8080/v1", "sk", model="qwen-30b",
                            engine="llamacpp", declared={"weights_revision": "rev-1"},
                            registry=reg, fetch=fetch, keychain_set=keys)
    assert reg.get("mini1").discovered_backend == "b1234"

@pytest.mark.asyncio
async def test_register_engine_that_cannot_report_leaves_backend_empty():
    # ollama branch: details carries no engine field on silent fallback -> backend ''.
    # Admission is mechanical-only (local tier, unverifiable) but the provider still
    # registers — '' is the honest value, not an error.
    reg = ProviderRegistry(); keys: dict[str, str] = {}
    async def fetch(url, headers):
        if url.endswith("/models"): return {"data": [{"id": "thomson1-chat:latest"}]}
        if url.endswith("/api/show"): return {"details": {}}
        return None
    res = await register_provider("oll", "http://o:11434/v1", "", model="thomson1-chat:latest",
                                  engine="ollama", declared={"weights_revision": "rev-1"},
                                  registry=reg, fetch=fetch, keychain_set=keys)
    assert res.admission == "mechanical-only"
    assert reg.get("oll").discovered_backend == ""
