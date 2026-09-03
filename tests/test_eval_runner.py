# tests/test_eval_runner.py
import pytest
from harness.eval.runner import run_eval
from harness.gate import EgressGate
from harness.policy import RoutingTable
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.trace import TraceStore

ROUTING = """rules: []
defaults:
  local_only: [mini1]
  local_preferred: [mini1]
  cloud_permitted: [mini1]
"""

@pytest.mark.asyncio
async def test_run_eval_end_to_end_offline(tmp_path, fake_transport):
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases" / "c.yaml").write_text(
        "id: c1\nmatter_type: m\ntask_class: drafting\nprompt: draft\n"
        'expected_citations: ["[Act, s 1]"]\nrequired_grounding: []\npersona_checks: {}\n')
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="mini1", base_url="http://m/v1", engine="mlx-lm", tier="local",
                              model="qwen-30b", admitted="full"))
    rp = tmp_path / "r.yaml"; rp.write_text(ROUTING)
    gate = EgressGate(registry=reg, routing=RoutingTable.from_yaml(rp),
                      trace=TraceStore(tmp_path / "t.db"), transport=fake_transport)
    scores = await run_eval(gate, tmp_path / "cases", tmp_path / "report.md")
    assert len(scores) == 1
    assert (tmp_path / "report.md").exists()
    assert gate.trace.summary()["dispatches"] == 1          # went through the gate, traced

@pytest.mark.asyncio
async def test_run_eval_reports_partial_results_when_a_case_is_refused(tmp_path):
    # S6-3: a mid-run dispatch refusal must not kill the run — the refused case is
    # recorded as such and every other case still lands in the report.
    (tmp_path / "cases").mkdir()
    for name, prompt in (("c1", "first"), ("c2", "poison")):
        (tmp_path / "cases" / f"{name}.yaml").write_text(
            f"id: {name}\nmatter_type: m\ntask_class: drafting\nprompt: {prompt}\n"
            "expected_citations: []\nrequired_grounding: []\npersona_checks: {}\n")
    async def transport(provider, payload):
        if "poison" in payload["messages"][0]["content"]:
            raise RuntimeError("provider down")            # -> all candidates failed
        return {"model": payload["model"], "choices": [{"message": {"content": "ok"}}]}
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="mini1", base_url="http://m/v1", engine="mlx-lm", tier="local",
                              model="qwen-30b", admitted="full"))
    rp = tmp_path / "r.yaml"; rp.write_text(ROUTING)
    gate = EgressGate(registry=reg, routing=RoutingTable.from_yaml(rp),
                      trace=TraceStore(tmp_path / "t.db"), transport=transport)
    scores = await run_eval(gate, tmp_path / "cases", tmp_path / "report.md")
    assert [s.status for s in scores] == ["scored", "refused"]
    assert scores[1].passed is False
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "c1" in text and "c2" in text and "refused" in text
