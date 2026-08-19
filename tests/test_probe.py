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
