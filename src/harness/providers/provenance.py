from __future__ import annotations
from typing import Awaitable, Callable
from pydantic import BaseModel
from harness.providers.config import ProviderConfig

Fetch = Callable[[str, dict], Awaitable[dict | None]]

class ProvenanceReport(BaseModel):
    engine: str = ""
    weights_revision: str = ""
    backend: str = ""
    verified: bool = False
    raw: dict = {}

async def check_provenance(cfg: ProviderConfig, fetch: Fetch) -> ProvenanceReport:
    """CR-3: the endpoint must VERIFIABLY report weights revision + actual executing backend.
    Engines that cannot (Ollama's silent MLX/llama.cpp fallback is the live example) come back
    unverified — admission_for() then refuses or restricts them. Never fabricate evidence."""
    headers = {"Authorization": "Bearer dummy"}   # probe auth handled by caller
    declared_rev = cfg.declared_provenance.get("weights_revision", "")

    if cfg.engine == "cloud":
        return ProvenanceReport(engine="cloud", weights_revision=declared_rev, backend="saas",
                                verified=bool(declared_rev), raw={"basis": "declared+saas"})
    if cfg.engine == "mlx-lm":
        health = await fetch(f"{cfg.base_url.removesuffix('/v1')}/health", headers)
        rev = (health or {}).get("revision", "")
        return ProvenanceReport(engine="mlx-lm", weights_revision=rev, backend=(health or {}).get("engine", ""),
                                verified=bool(rev) and rev == declared_rev, raw={"health": health or {}})
    if cfg.engine == "vllm":
        ver = await fetch(f"{cfg.base_url.removesuffix('/v1')}/version", headers)
        rev = (ver or {}).get("version", "")
        return ProvenanceReport(engine="vllm", weights_revision=declared_rev, backend=f"vllm-{rev}",
                                verified=bool(declared_rev) and bool(rev), raw={"version": ver or {}})
    if cfg.engine == "llamacpp":
        props = await fetch(f"{cfg.base_url.removesuffix('/v1')}/props", headers)
        backend = (props or {}).get("build_info", "")
        return ProvenanceReport(engine="llamacpp", weights_revision=declared_rev, backend=backend,
                                verified=bool(declared_rev) and bool(backend), raw={"props": props or {}})
    if cfg.engine == "ollama":
        show = await fetch(f"{cfg.base_url.removesuffix('/v1')}/api/show", headers)
        details = (show or {}).get("details", {})
        backend = details.get("engine") or details.get("backend") or ""   # absent on silent fallback
        return ProvenanceReport(engine="ollama", weights_revision=declared_rev, backend=backend,
                                verified=bool(declared_rev) and bool(backend), raw={"show": show or {}})
    return ProvenanceReport(engine=cfg.engine or "unknown", weights_revision=declared_rev,
                            backend="", verified=False, raw={"basis": "unknown-engine"})

def admission_for(report: ProvenanceReport, cfg: ProviderConfig) -> str:
    if report.verified:
        return "full"
    if not cfg.engine:
        return "refused"          # unknown engine: we cannot even know what is running (CR-3)
    # Unverifiable: locals may serve the mechanical tier (deterministic, low-stakes) only;
    # unverifiable clouds are refused outright — the gate must never carry privilege on trust.
    return "mechanical-only" if cfg.tier == "local" else "refused"
