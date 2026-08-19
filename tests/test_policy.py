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
    reg.upsert(ProviderConfig(name="mini1-mlx", base_url="http://m1/v1", engine="mlx-lm", tier="local"))
    reg.upsert(ProviderConfig(name="mini2", base_url="http://m2/v1", engine="vllm", tier="local",
                              admitted="mechanical-only"))
    reg.upsert(ProviderConfig(name="cloud-x", base_url="https://x/v1", engine="cloud", tier="cloud"))
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
