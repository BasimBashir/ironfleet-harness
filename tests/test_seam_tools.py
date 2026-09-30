# tests/test_seam_tools.py
import pytest
from harness.module_e.supervisor import route_tool
from harness.module_e import refine

# ── route_tool (the supervisor routing, tool-shaped) ─────────────────────────

def test_route_resolves_analysis_low():
    r = route_tool({"intent": "analysis", "complexity": "LOW"})
    assert r["personas"] == ["hunter", "strategist"]
    assert r["intent"] == "analysis" and r["complexity"] == "LOW"

def test_route_defaults_on_an_unknown_intent():
    r = route_tool({"intent": "brand-new-intent"})
    assert r["personas"] == ["hunter"]          # the _DEFAULT_ROUTE behaviour
    assert r["defaulted"] is True

def test_route_is_not_a_default_when_known():
    assert route_tool({"intent": "ingestion"})["defaulted"] is False

def test_route_with_no_intent_fails_loud():
    # The missing-intent contract: `args["intent"]` indexes before anything can default, so a
    # call with no intent raises KeyError — surfaced, never swallowed into a default route.
    with pytest.raises(KeyError):
        route_tool({})

# ── refine_tool (critique + improve, through the gate proxy) ─────────────────

class FakeResp:
    def __init__(self, payload): self._p = payload
    def read(self): return self._p
    def __enter__(self): return self
    def __exit__(self, *a): return False

def _install(monkeypatch, responses):
    calls = []
    def fake_urlopen(req, timeout):
        import json as _j
        calls.append(_j.loads(req.data.decode()))
        return FakeResp(_j.dumps(responses[len(calls) - 1]).encode())
    monkeypatch.setattr(refine.urllib.request, "urlopen", fake_urlopen)
    return calls

CRITIQUE = ("HIGH: the deadline misstates s 241(4)(a).\n"
            "MEDIUM: passive voice throughout.\n"
            "OVERALL_QUALITY: 4/10")

def test_refine_runs_critique_then_improve(monkeypatch):
    calls = _install(monkeypatch, [
        {"choices": [{"message": {"content": CRITIQUE}}]},
        {"choices": [{"message": {"content": "IMPROVED TEXT"}}]},
    ])
    r = refine.refine_tool({"text": "DRAFT TEXT", "task_class": "drafting"})
    assert len(calls) == 2
    assert calls[0]["model"] == "gate/drafting"       # the BARE alias — resolve_alias's contract
    assert calls[0]["stream"] is False
    assert "DRAFT TEXT" in calls[0]["messages"][-1]["content"]
    assert calls[1]["messages"][-1]["content"].count("DRAFT TEXT") >= 1
    assert CRITIQUE in calls[1]["messages"][-1]["content"]
    assert r["refined"] == "IMPROVED TEXT"
    assert r["score_before"] == 4.0

def test_refine_requires_text():
    with pytest.raises(ValueError):
        refine.refine_tool({"task_class": "drafting"})

def test_score_parser_tolerates_a_missing_marker():
    assert refine._parse_quality_score("no marker here") is None
