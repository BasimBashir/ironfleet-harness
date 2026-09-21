# src/harness/alias.py
from __future__ import annotations
from pathlib import Path
import yaml

class UnknownAlias(KeyError):
    """A model string that is not a gate alias. Fail closed — never guess a task class."""

def load_aliases(path: Path) -> dict[str, dict]:
    """Read the 'aliases' section of a routing YAML. Absent -> {} (nothing resolves,
    which is fail-closed, not an error). Malformed -> ValueError, because passing a
    wrong-shaped alias map downstream would be worse than refusing to start."""
    doc = yaml.safe_load(Path(path).read_text())
    if not isinstance(doc, dict):
        raise ValueError(f"routing file {path}: top level must be a mapping")
    aliases = doc.get("aliases") or {}
    if not isinstance(aliases, dict):
        raise ValueError(f"routing file {path}: 'aliases' must be a mapping")
    return aliases

def resolve_alias(model: str, aliases: dict) -> str:
    """Map a gate alias ('gate/extraction') to its task class. Anything not in the map
    raises UnknownAlias: the proxy must never infer a task class from an unrecognised
    model string, because the routing table's empty defaults are what make unknown
    classes refuse."""
    if model not in aliases:
        raise UnknownAlias(model)
    return aliases[model]["task_class"]
