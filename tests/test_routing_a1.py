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

def test_a1_toolpath_rule_leads_with_the_cloud_tool_caller():
    # The injection leg's disjointness property (S7j-W spec §1.2): the toolpath class must
    # never share a candidate with parity's research class, or a routing edit could
    # silently move the fail-closed proof onto the non-tool-calling model.
    # R3 2026-10-19: the leg leads with a full-admission cloud tool-caller — the
    # pragmatic path when Ollama's honest mechanical-only verdict cannot.
    # R3 2026-10-20: that caller is its OWN row, nvidia-nim-tool —
    # research now names nvidia-nim for its cloud leg, and the rows are
    # disjoint BY NAME so the invariant holds by construction.
    rt = RoutingTable.from_yaml(A1)
    rules = {r["task_class"]: r for r in rt._rules}
    rule = rules["toolpath"]
    research = rules["research"]
    assert rule["cloud_permitted"][0] == "nvidia-nim-tool", \
        "cloud leg must lead with the toolpath's own NIM row"
    assert "qwen-local" in rule["local_only"] and "qwen-local" in rule["local_preferred"]
    shared = set(rule["cloud_permitted"]) & set(research["cloud_permitted"])
    assert not shared, f"toolpath and research must not share a candidate: {shared}"
    assert "nvidia-nim-tool" not in research["cloud_permitted"], \
        "research (parity leg) may not name the toolpath row in its cloud candidates"
    assert "nvidia-nim" in research["cloud_permitted"], \
        "research keeps a real cloud leg — that is why the split rows exist"

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
