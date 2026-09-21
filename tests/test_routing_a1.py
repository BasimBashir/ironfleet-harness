# tests/test_routing_a1.py
import json
import pytest
from pathlib import Path
from harness.alias import load_aliases, resolve_alias, UnknownAlias
from harness.policy import RoutingTable, MECHANICAL_TASKS

A1 = Path(__file__).resolve().parent.parent / "data" / "routing-a1.yaml"

def test_a1_table_loads_and_has_aliases():
    aliases = load_aliases(A1)
    assert "gate/extraction" in aliases
    assert "gate/drafting" in aliases
    # from_yaml still works on the same file (it ignores the aliases key) — the two
    # readers must agree the file is valid.
    RoutingTable.from_yaml(A1)

def test_a1_defaults_are_empty_so_unknown_classes_refuse():
    rt = RoutingTable.from_yaml(A1)
    assert rt._defaults["local_only"] == []
    assert rt._defaults["local_preferred"] == []
    assert rt._defaults["cloud_permitted"] == []

def test_a1_every_alias_maps_to_a_listed_rule():
    # An alias whose task class has no rule would silently fall to the empty defaults
    # and refuse — correct behaviour, but a config bug we want to catch at test time.
    rt = RoutingTable.from_yaml(A1)
    rule_classes = {r["task_class"] for r in rt._rules}
    for alias, spec in load_aliases(A1).items():
        assert spec["task_class"] in rule_classes, f"{alias} has no rule"

def test_a1_aliases_cover_exactly_the_mount_models():
    # §5 of the spec: the mount's model list and the routing aliases must not drift.
    mount = Path(__file__).resolve().parent.parent / "data" / "opencode-a1" / "opencode.json"
    mounted = set(json.loads(mount.read_text())["provider"]["gate-local"]["models"])
    assert mounted == set(load_aliases(A1)), "mount models and routing aliases drifted"

def test_a1_extraction_is_mechanical():
    aliases = load_aliases(A1)
    assert resolve_alias("gate/extraction", aliases) in MECHANICAL_TASKS
    with pytest.raises(UnknownAlias):
        resolve_alias("gate/summarising", aliases)   # not a mechanical task we admit
