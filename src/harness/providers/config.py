from __future__ import annotations
from pydantic import BaseModel

class ProviderConfig(BaseModel):
    name: str
    base_url: str                       # OpenAI-compatible endpoint
    model: str = ""                     # default serving LLM (endpoints serve multiple models — nl-dev req)
    models: list[str] = []              # discovered model list (probe fills; informational)
    engine: str | None = None           # mlx-lm | vllm | llamacpp | ollama | cloud | None
    tier: str = "cloud"                 # local | cloud
    admitted: str = "refused"           # full | mechanical-only | refused — only the probe upgrades (S6-1, CR-3 fail-closed)
    declared_provenance: dict[str, str] = {}   # describes `model`: {"weights_revision": "...", "quant": "4bit"}
    discovered_backend: str = ""        # S7d: what the probe OBSERVED executing — never
                                        # operator-declared; separate field so discovery
                                        # cannot be laundered into declaration
    max_output_tokens: int | None = None       # S6-4: provider output ceiling — the gate clamps
                                               # request.max_tokens to it (strict APIs 400 on the
                                               # 128k default); None = provider enforces its own

class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
    def upsert(self, cfg: ProviderConfig) -> None:
        self._providers[cfg.name] = cfg
    def get(self, name: str) -> ProviderConfig:
        return self._providers[name]
    def list(self) -> list[ProviderConfig]:
        return list(self._providers.values())
