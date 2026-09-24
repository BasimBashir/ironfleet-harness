# tests/test_supervisor.py
from pathlib import Path
import pytest
from harness.module_e.supervisor import load_routes

DATA = Path(__file__).resolve().parent.parent / "data" / "module-e"

def test_analysis_route_is_hunter_then_strategist():
    r = load_routes(DATA / "supervisor.yaml")
    assert r.resolve("analysis", "LOW") == ["hunter", "strategist"]

def test_default_route_for_unknown_intent():
    r = load_routes(DATA / "supervisor.yaml")
    assert r.resolve("something-new", "LOW") == ["hunter"]

def test_complexity_medium_adds_strategist_when_absent():
    r = load_routes(DATA / "supervisor.yaml")
    assert r.resolve("research", "MEDIUM") == ["hunter", "strategist"]

def test_complexity_low_keeps_the_minimal_set():
    r = load_routes(DATA / "supervisor.yaml")
    assert r.resolve("research", "LOW") == ["hunter"]

def test_high_negotiation_adds_wargamer():
    r = load_routes(DATA / "supervisor.yaml")
    assert r.resolve("negotiation", "HIGH") == ["hunter", "strategist", "negotiator", "wargamer"]

def test_no_route_references_the_removed_personalities():
    # predictor / ensemble / red_blue had no agent dirs in the old tree — they must not survive
    # into the port. This is the test that would have caught them in the old tree.
    r = load_routes(DATA / "supervisor.yaml")
    all_names = {n for route in r.routes.values() for n in route} | set(r.default_route)
    assert not {"predictor", "ensemble", "red_blue"} & all_names

@pytest.mark.parametrize("intent", ["research", "drafting", "analysis", "calculation",
                                    "strategy_validation", "negotiation", "risk_simulation",
                                    "ingestion"])
def test_every_route_is_deterministic_and_non_empty(intent):
    r = load_routes(DATA / "supervisor.yaml")
    got = r.resolve(intent, "LOW")
    assert got and got == list(dict.fromkeys(got))   # no duplicates, order preserved
