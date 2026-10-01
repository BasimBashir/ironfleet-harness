# tests/test_accept_s7e.py — the PURE parts of the S7e acceptance driver.
# main() drives real Ollama + bge-m3 and is NEVER run in the suite.
from pathlib import Path

import pytest

from harness.policy import RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore

ROUTING = Path(__file__).resolve().parent.parent / "data" / "routing-a1.yaml"


def _offline_gate(tmp_path):
    """A gate whose registry carries ollama-embed as the probe would admit it
    (mechanical-only, local tier) — no network."""
    from harness.gate import EgressGate
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="ollama-embed", base_url="http://127.0.0.1:11434/v1",
                              engine="ollama", tier="local", model="bge-m3:567m",
                              admitted="mechanical-only"))
    return EgressGate(registry=reg, routing=RoutingTable.from_yaml(ROUTING),
                      trace=TraceStore(tmp_path / "t.db"))


def test_check_c1_passes_with_the_committed_routing(tmp_path):
    from scripts.accept_s7e import check_c1
    gate = _offline_gate(tmp_path)
    assert check_c1(gate) == []


@pytest.mark.parametrize("mutate,fragment", [
    (lambda g: g.registry._providers.pop("ollama-embed"), "exactly [ollama-embed]"),
    (lambda g: g.registry.upsert(ProviderConfig(name="ollama-embed", base_url="x",
                                                engine="ollama", tier="cloud",
                                                model="bge-m3:567m", admitted="full")),
     "tier='cloud'"),
])
def test_check_c1_catches_a_misconfigured_embedder(tmp_path, mutate, fragment):
    from scripts.accept_s7e import check_c1
    gate = _offline_gate(tmp_path)
    mutate(gate)
    problems = check_c1(gate)
    # A cloud-tier ollama-embed is caught twice over — it is filtered out of the routing
    # picks AND its registration is the wrong shape — so the fragment may be on any line.
    assert problems and any(fragment in p for p in problems)


def test_check_c2_refuses_a_cloud_embedder_the_routing_table_permits(tmp_path, monkeypatch):
    # The load-bearing check, offline: cloud-embed is named in the adversarial fixture's
    # cloud_permitted AND registered as fully-admitted cloud-tier, yet routing must
    # still refuse it for the embedding class.
    import scripts.accept_s7e as drv
    monkeypatch.setattr(drv, "WS", tmp_path)   # the check writes its fixture; stay hermetic
    gate = _offline_gate(tmp_path)
    assert drv.check_c2(gate) == []


def test_check_c2_detects_a_vacuous_fixture(tmp_path, monkeypatch):
    # If the adversarial fixture stops naming a cloud embedder, the check is testing
    # nothing — it must say so rather than pass silently.
    import scripts.accept_s7e as drv
    monkeypatch.setattr(drv, "WS", tmp_path)
    monkeypatch.setattr(drv, "ADVERSARIAL_ROUTING",
                        drv.ADVERSARIAL_ROUTING.replace("[cloud-embed, ollama-embed]",
                                                        "[ollama-embed]"))
    gate = _offline_gate(tmp_path)
    problems = drv.check_c2(gate)
    assert problems and "not testing anything" in problems[0]


def test_check_c2_fails_if_the_structural_guard_is_removed(tmp_path, monkeypatch):
    # Negative control: with LOCAL_ONLY_TASKS emptied, the cloud embedder IS reached and
    # the check must fail — proving it tests the guard, not the fixture.
    import harness.policy as pol
    monkeypatch.setattr(pol, "LOCAL_ONLY_TASKS", frozenset())
    import scripts.accept_s7e as drv
    monkeypatch.setattr(drv, "WS", tmp_path)
    gate = _offline_gate(tmp_path)
    problems = drv.check_c2(gate)
    assert problems and "REACHED" in problems[0]


def test_c5_fixture_has_no_embedding_rule(tmp_path):
    import scripts.accept_s7e as drv
    from harness.policy import MatterPolicy
    assert "embedding" not in drv.NO_EMBEDDING_RULE
    p = tmp_path / "no-emb.yaml"
    p.write_text(drv.NO_EMBEDDING_RULE)
    rt = RoutingTable.from_yaml(p)
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="ollama-embed", base_url="http://o/v1", engine="ollama",
                              tier="local", model="bge-m3:567m", admitted="mechanical-only"))
    assert rt.route("embedding", MatterPolicy(matter_ref="M", classification="LOCAL_ONLY"),
                    reg) == []
