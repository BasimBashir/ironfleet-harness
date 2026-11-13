from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel
from harness.providers.config import ProviderConfig, ProviderRegistry

Classification = Literal["LOCAL_ONLY", "LOCAL_PREFERRED", "CLOUD_PERMITTED"]
MECHANICAL_TASKS = {"extraction", "classification", "embedding", "redaction", "grounding_check",
                    "rerank"}
# A-4: embedding privileged text via a cloud API is an egress event. These classes are
# structurally LOCAL_ONLY — the routing table cannot relax this, because an operator
# editing YAML is not the same authority as the confidentiality rule. See spec §2.
# R1 D3: rerank joins the set — it scores the DRAFT against PASSAGES, privileged on
# both sides, and is mechanical work like embedding.
LOCAL_ONLY_TASKS = frozenset({"embedding", "rerank"})

class MatterPolicy(BaseModel):
    matter_ref: str
    classification: Classification

class RoutingTable:
    def __init__(self, rules: dict, defaults: dict) -> None:
        self._rules, self._defaults = rules, defaults
        self.assign: dict[str, str] = {}   # M13.7 admin pick per task class: any provider, leads

    @classmethod
    def from_yaml(cls, path: Path) -> "RoutingTable":
        doc = yaml.safe_load(Path(path).read_text())
        if not isinstance(doc, dict) or "defaults" not in doc:
            raise ValueError(f"routing table {path}: missing 'defaults' section — refusing to route")
        return cls(doc.get("rules", []), doc["defaults"])

    def _pref(self, task_class: str, classification: str) -> list[str]:
        prefs = list(self._defaults.get(classification.lower(), []))
        for r in self._rules:
            if r.get("task_class") == task_class and r.get(classification.lower()) is not None:
                prefs = list(r[classification.lower()])
                break                                 # else: fall through to defaults
        first = self.assign.get(task_class)
        # the assigned provider leads even if the YAML never listed it; route() still filters it
        return [first] + [n for n in prefs if n != first] if first else prefs

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
            # A-4: a LOCAL_ONLY_TASKS class never dispatches to a cloud-tier provider,
            # whatever the routing table or matter classification says (spec §2).
            if task_class in LOCAL_ONLY_TASKS and cfg.tier != "local":
                continue
            out.append(cfg)
        return out
