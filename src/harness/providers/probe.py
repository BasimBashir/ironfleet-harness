from __future__ import annotations
from typing import Awaitable, Callable
from pydantic import BaseModel
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.providers.provenance import ProvenanceReport, check_provenance, admission_for

Fetch = Callable[[str, dict], Awaitable[dict | None]]

class ProbeResult(BaseModel):
    reachable: bool
    auth_ok: bool
    models: list[str]
    provenance: ProvenanceReport
    admission: str            # full | mechanical-only | refused

async def register_provider(
    name: str, base_url: str, api_key: str, model: str = "", engine: str | None = None,
    declared: dict[str, str] | None = None,
    registry: ProviderRegistry | None = None,
    fetch: Fetch | None = None,
    keychain_set: dict[str, str] | None = None,
) -> ProbeResult:
    """D4 + CR-3: 'correct inputs' = reachable + authed + model list + VERIFIABLE provenance.
    The key is stored only when the probe admits the provider."""
    if fetch is None:
        from harness.providers.http_fetch import openai_fetch   # real transport (Task 7 extracts)
        fetch = openai_fetch
    # Empty key (local servers) -> no Authorization header; "Bearer " alone is an illegal value.
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    models_payload = await fetch(f"{base_url.rstrip('/')}/models", headers)
    reachable, auth_ok = models_payload is not None, models_payload is not None
    models = [m.get("id", "") for m in (models_payload or {}).get("data", [])]
    cfg = ProviderConfig(name=name, base_url=base_url, model=model, models=models, engine=engine,
                         tier="local" if engine in ("mlx-lm", "vllm", "llamacpp", "ollama") else "cloud",
                         declared_provenance=declared or {})
    prov = await check_provenance(cfg, fetch)
    admission = admission_for(prov, cfg) if (reachable and auth_ok) else "refused"
    if admission != "refused":
        cfg.admitted = admission
        if isinstance(keychain_set, dict): keychain_set[name] = api_key
        else:
            from harness.keychain import set_key; set_key(name, api_key)
        if registry is not None: registry.upsert(cfg)
    return ProbeResult(reachable=reachable, auth_ok=auth_ok, models=models,
                       provenance=prov, admission=admission)
