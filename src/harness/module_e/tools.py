# src/harness/module_e/tools.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class ToolEntry:
    name: str
    description: str
    entry: str
    status: str
    source: str
    reason: str = ""
    aliases: list[str] = None
    # F3 (spec 17 §5.7): optional JSON Schema the shim renders into the model-facing
    # tool definition, so a model can discover the fields. None = the proven passthrough.
    parameters: dict | None = None

def load_manifest(path: Path) -> dict[str, ToolEntry]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, ToolEntry] = {}
    for row in doc["tools"]:
        t = ToolEntry(**row)
        if t.name in out:
            raise ValueError(f"duplicate tool name {t.name}")
        out[t.name] = t
    return out

def ported_tools(manifest: dict[str, ToolEntry]) -> set[str]:
    """Rows with a real tool ID the mount can enable: the guard's annotation whitelist, the TS
    plugin's tool list, and the generator's enablement set."""
    return {t.name for t in manifest.values() if t.status == "ported"}

def declared_tools(manifest: dict[str, ToolEntry]) -> set[str]:
    """Every name the manifest knows, any status. The generator validates persona `allowed_tools`
    against THIS set — a deferred tool (e.g. auditor's six kernel tools) is a legitimate reference
    that gets recorded in the agent's `# deferred` ledger, not an error. A name in neither set is
    the error (UnknownTool)."""
    return set(manifest)
