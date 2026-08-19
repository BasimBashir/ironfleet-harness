from __future__ import annotations
from pydantic import BaseModel

class ProviderConfig(BaseModel):
    name: str
    base_url: str                       # OpenAI-compatible endpoint
    engine: str | None = None           # mlx-lm | vllm | llamacpp | ollama | cloud | None
    tier: str = "cloud"                 # local | cloud
    admitted: str = "full"              # full | mechanical-only | refused  (set by probe, CR-3)
    declared_provenance: dict[str, str] = {}   # {"weights_revision": "...", "quant": "4bit"}

class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
    def upsert(self, cfg: ProviderConfig) -> None:
        self._providers[cfg.name] = cfg
    def get(self, name: str) -> ProviderConfig:
        return self._providers[name]
    def list(self) -> list[ProviderConfig]:
        return list(self._providers.values())
