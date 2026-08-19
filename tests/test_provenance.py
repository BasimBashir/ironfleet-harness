import pytest
from harness.providers.config import ProviderConfig
from harness.providers.provenance import check_provenance, admission_for

def _cfg(engine="mlx-lm", declared=None):
    return ProviderConfig(name="p", base_url="http://x:1/v1", engine=engine, tier="local",
                          declared_provenance=declared or {"weights_revision": "rev-1"})

@pytest.mark.asyncio
async def test_mlx_verified_when_server_report_matches():
    async def fetch(url, headers):
        if url.endswith("/v1/models"):
            return {"data": [{"id": "qwen-30b"}]}
        if url.endswith("/health"):
            return {"model": "qwen-30b", "revision": "rev-1"}     # server-side evidence
        return None
    rep = await check_provenance(_cfg(), fetch)
    assert rep.verified and rep.weights_revision == "rev-1"

@pytest.mark.asyncio
async def test_ollama_silent_fallback_is_mechanical_only():
    # Ollama /api/show present but carries NO engine/backend field → unverifiable (CR-3 live example)
    async def fetch(url, headers):
        if "/api/show" in url:
            return {"details": {"family": "qwen2"}}               # no engine/backend evidence
        return None
    cfg = _cfg(engine="ollama")
    rep = await check_provenance(cfg, fetch)
    assert not rep.verified
    assert admission_for(rep, cfg) == "mechanical-only"

@pytest.mark.asyncio
async def test_cloud_engine_gets_declared_provenance_full_cloud():
    async def fetch(url, headers): return None                     # nothing to check
    cfg = ProviderConfig(name="c", base_url="https://api.x/v1", engine="cloud", tier="cloud",
                         declared_provenance={"weights_revision": "glm-5.2@2026-08"})
    rep = await check_provenance(cfg, fetch)
    assert rep.verified and rep.weights_revision == "glm-5.2@2026-08" and rep.engine == "cloud"

@pytest.mark.asyncio
async def test_unknown_local_engine_is_refused():
    async def fetch(url, headers): return None
    cfg = _cfg(engine=None, declared={})
    rep = await check_provenance(cfg, fetch)
    assert admission_for(rep, cfg) == "refused"
