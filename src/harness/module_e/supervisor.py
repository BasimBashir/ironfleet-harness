# src/harness/module_e/supervisor.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

@dataclass
class SupervisorRoutes:
    default_route: list[str]
    routes: dict[str, list[str]]
    complex_intents: list[str] = field(default_factory=list)
    add_on_medium_high: list[str] = field(default_factory=list)
    add_on_high: dict[str, list[str]] = field(default_factory=dict)

    def resolve(self, intent: str, complexity: str = "LOW") -> list[str]:
        agents = list(self.routes.get(intent, self.default_route))
        if complexity in ("MEDIUM", "HIGH"):
            for a in self.add_on_medium_high:
                if a not in agents:
                    agents.append(a)
        if complexity == "HIGH":
            for a in self.add_on_high.get(intent, []):
                if a not in agents:
                    agents.append(a)
        return list(dict.fromkeys(agents))

_DEFAULTED = "defaulted"

def route_tool(args: dict) -> dict:
    """The manifest's `route` entry: resolve an intent to its ordered persona list. Reads the
    shipped routing data — every routing decision stays a thing a test can read."""
    intent = args["intent"]
    complexity = args.get("complexity", "LOW")
    data = Path(__file__).resolve().parents[3] / "data" / "module-e" / "supervisor.yaml"
    routes = load_routes(data)
    known = intent in routes.routes
    return {"intent": intent, "complexity": complexity, "defaulted": not known,
            "personas": routes.resolve(intent, complexity)}

def load_routes(path: Path) -> SupervisorRoutes:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return SupervisorRoutes(
        default_route=doc["default_route"],
        routes=doc["routes"],
        complex_intents=doc.get("complex_intents", []),
        add_on_medium_high=doc.get("complexity", {}).get("add_strat_on_medium_or_high", []),
        add_on_high=doc.get("complexity", {}).get("add_on_high", {}),
    )
