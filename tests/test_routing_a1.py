# tests/test_routing_a1.py
import json
import pytest
from pathlib import Path
from harness.alias import load_aliases, resolve_alias, UnknownAlias
from harness.policy import RoutingTable, MECHANICAL_TASKS, MatterPolicy

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


def test_a1_embedding_alias_maps_to_the_embedding_rule():
    aliases = load_aliases(A1)
    assert resolve_alias("gate/embedding", aliases) == "embedding"
    rt = RoutingTable.from_yaml(A1)
    rule_classes = {r["task_class"] for r in rt._rules}
    assert "embedding" in rule_classes, "gate/embedding needs a routing rule"

def test_a1_toolpath_rule_names_only_the_qwen_provider():
    # The injection leg's disjointness property (S7j-W spec §1.2): the toolpath class must
    # never share a candidate with parity's research class (which names only ollama-local),
    # or a routing edit could silently move the fail-closed proof onto the
    # non-tool-calling model.
    rt = RoutingTable.from_yaml(A1)
    rule = next(r for r in rt._rules if r["task_class"] == "toolpath")
    for tier in ("local_only", "local_preferred", "cloud_permitted"):
        assert rule[tier] == ["qwen-local"], tier

def test_a1_toolpath_is_not_mechanical():
    # Non-mechanical on purpose: Ollama's honest probe verdict (mechanical-only) must NOT
    # silently serve this class — the driver's recorded in-memory override is what admits
    # it, keeping the CR-3 deviation visible instead of implicit.
    assert "toolpath" not in MECHANICAL_TASKS
    aliases = load_aliases(A1)
    assert resolve_alias("gate/toolpath", aliases) == "toolpath"

def test_a1_embedding_rule_lists_only_local_providers():
    # The routing-table half of the belt-and-braces LOCAL_ONLY rule (spec §2): the
    # committed table must not name a cloud provider for the embedding class.
    from harness.providers.config import ProviderConfig, ProviderRegistry
    rt = RoutingTable.from_yaml(A1)
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="ollama-embed", base_url="http://o/v1", engine="ollama",
                              tier="local", model="bge-m3:567m", admitted="mechanical-only"))
    picks = rt.route("embedding", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"), reg)
    assert [c.name for c in picks] == ["ollama-embed"]
