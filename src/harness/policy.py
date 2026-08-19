from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel
from harness.providers.config import ProviderConfig, ProviderRegistry

Classification = Literal["LOCAL_ONLY", "LOCAL_PREFERRED", "CLOUD_PERMITTED"]
MECHANICAL_TASKS = {"extraction", "classification", "embedding", "redaction", "grounding_check"}

class MatterPolicy(BaseModel):
    matter_ref: str
    classification: Classification

class RoutingTable:
    def __init__(self, rules: dict, defaults: dict) -> None:
        self._rules, self._defaults = rules, defaults

    @classmethod
    def from_yaml(cls, path: Path) -> "RoutingTable":
        doc = yaml.safe_load(Path(path).read_text())
        if not isinstance(doc, dict) or "defaults" not in doc:
            raise ValueError(f"routing table {path}: missing 'defaults' section — refusing to route")
        return cls(doc.get("rules", []), doc["defaults"])

    def _pref(self, task_class: str, classification: str) -> list[str]:
        for r in self._rules:
            if r.get("task_class") == task_class:
                prefs = r.get(classification.lower())
                if prefs is not None:
                    return list(prefs)                # else: fall through to defaults
        return list(self._defaults.get(classification.lower(), []))

    def route(self, task_class: str, policy: MatterPolicy, registry: ProviderRegistry) -> list[ProviderConfig]:
        by_name = {c.name: c for c in registry.list()}
        out: list[ProviderConfig] = []
        for name in self._pref(task_class, policy.classification):
            cfg = by_name.get(name)
            if cfg is None or cfg.admitted == "refused":
                continue
            mechanical_ok = task_class in MECHANICAL_TASKS
            if cfg.admitted == "mechanical-only" and not mechanical_ok:
                continue
            out.append(cfg)
        return out
