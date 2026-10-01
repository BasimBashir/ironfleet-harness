from pathlib import Path
from harness.policy import RoutingTable, MatterPolicy
from harness.providers.config import ProviderConfig, ProviderRegistry

ROUTING = """
rules:
  - task_class: drafting
    local_only: [mini1-mlx]
    local_preferred: [mini1-mlx, cloud-x]
    cloud_permitted: [cloud-x, mini1-mlx]
  - task_class: extraction        # mechanical tier
    local_only: [mini2]
    local_preferred: [mini2]
    cloud_permitted: [mini2]
defaults:
  local_only: [mini1-mlx]
  local_preferred: [mini1-mlx, cloud-x]
  cloud_permitted: [cloud-x, mini1-mlx]
"""

def _registry():
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="mini1-mlx", base_url="http://m1/v1", engine="mlx-lm", tier="local",
                              admitted="full"))
    reg.upsert(ProviderConfig(name="mini2", base_url="http://m2/v1", engine="vllm", tier="local",
                              admitted="mechanical-only"))
    reg.upsert(ProviderConfig(name="cloud-x", base_url="https://x/v1", engine="cloud", tier="cloud",
                              admitted="full"))
    return reg

def test_local_only_never_sees_cloud(tmp_path):
    p = tmp_path / "routing.yaml"; p.write_text(ROUTING)
    rt = RoutingTable.from_yaml(p)
    picks = rt.route("drafting", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"), _registry())
    assert [c.name for c in picks] == ["mini1-mlx"]

def test_mechanical_only_provider_usable_for_extraction_not_drafting(tmp_path):
    p = tmp_path / "routing.yaml"; p.write_text(ROUTING)
    rt = RoutingTable.from_yaml(p)
    ext = rt.route("extraction", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"), _registry())
    assert [c.name for c in ext] == ["mini2"]                       # mechanical tier serves extraction
    drafting = rt.route("drafting", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"), _registry())
    assert all(c.name != "mini2" for c in drafting)                 # but never drafting

def test_malformed_routing_fails_loud_not_silent(tmp_path):
    import pytest
    p = tmp_path / "bad.yaml"; p.write_text("rules: []\n")          # no defaults section
    with pytest.raises(ValueError):
        RoutingTable.from_yaml(p)
    q = tmp_path / "partial.yaml"; q.write_text(ROUTING + "\n")     # valid
    rt = RoutingTable.from_yaml(q)
    result = rt.route("unknown-task", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"), _registry())
    assert [c.name for c in result] == ["mini1-mlx"]               # unknown task falls to defaults

def test_unprobed_provider_defaults_to_refused_and_never_routes(tmp_path):
    # S6-1: admitted defaults to "refused" — only a successful probe upgrades it (fail-closed).
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="mini1-mlx", base_url="http://m1/v1", engine="mlx-lm", tier="local"))
    p = tmp_path / "routing.yaml"; p.write_text(ROUTING)
    picks = RoutingTable.from_yaml(p).route(
        "drafting", MatterPolicy(matter_ref="M", classification="LOCAL_PREFERRED"), reg)
    assert picks == []                                             # never probed -> never routed

# --- A-4: the embedding class is structurally LOCAL_ONLY (policy.py) -------------------

EMB_ROUTING = """
rules:
  - task_class: embedding
    local_only: [emb-local]
    local_preferred: [emb-local]
    cloud_permitted: [cloud-emb, emb-local]   # misconfigured: a cloud embedder named as permitted
  - task_class: drafting
    local_only: [mini1-mlx]
    local_preferred: [mini1-mlx, cloud-x]
    cloud_permitted: [cloud-x, mini1-mlx]
defaults:
  local_only: [mini1-mlx]
  local_preferred: [mini1-mlx, cloud-x]
  cloud_permitted: [cloud-x, mini1-mlx]
"""

def _registry_with_embedders():
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="mini1-mlx", base_url="http://m1/v1", engine="mlx-lm",
                              tier="local", admitted="full"))
    reg.upsert(ProviderConfig(name="emb-local", base_url="http://m2/v1", engine="ollama",
                              tier="local", admitted="mechanical-only"))
    reg.upsert(ProviderConfig(name="cloud-emb", base_url="https://ce/v1", engine="cloud",
                              tier="cloud", admitted="full"))
    reg.upsert(ProviderConfig(name="cloud-x", base_url="https://cx/v1", engine="cloud",
                              tier="cloud", admitted="full"))
    return reg

def test_embedding_never_routes_to_cloud_even_when_cloud_permitted_lists_it(tmp_path):
    # The load-bearing A-4 assertion: a cloud embedder the routing table EXPLICITLY
    # permits under cloud_permitted is still unreachable for the embedding class.
    p = tmp_path / "emb.yaml"; p.write_text(EMB_ROUTING)
    rt = RoutingTable.from_yaml(p)
    picks = rt.route("embedding", MatterPolicy(matter_ref="M",
                                               classification="CLOUD_PERMITTED"),
                     _registry_with_embedders())
    assert picks, "embedding class must have at least one local candidate"
    assert all(c.tier == "local" for c in picks), \
        f"embedding class routed to cloud-tier providers: {[c.name for c in picks]}"
    assert "cloud-emb" not in [c.name for c in picks]

def test_embedding_local_only_prefers_local_embedder(tmp_path):
    p = tmp_path / "emb.yaml"; p.write_text(EMB_ROUTING)
    rt = RoutingTable.from_yaml(p)
    picks = rt.route("embedding", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"),
                     _registry_with_embedders())
    assert [c.name for c in picks] == ["emb-local"]

def test_local_only_filter_does_not_widen_to_other_classes(tmp_path):
    # Regression guard: drafting under CLOUD_PERMITTED must still reach the cloud
    # provider — the new filter is scoped to LOCAL_ONLY_TASKS, not to everything.
    p = tmp_path / "emb.yaml"; p.write_text(EMB_ROUTING)
    rt = RoutingTable.from_yaml(p)
    picks = rt.route("drafting", MatterPolicy(matter_ref="M",
                                              classification="CLOUD_PERMITTED"),
                     _registry_with_embedders())
    assert [c.name for c in picks] == ["cloud-x", "mini1-mlx"]

def test_local_only_tasks_set_contains_embedding():
    from harness.policy import LOCAL_ONLY_TASKS
    assert "embedding" in LOCAL_ONLY_TASKS
