# tests/test_eval_runner.py
import pytest
from harness.eval.runner import run_eval
from harness.gate import EgressGate, LLMRequest
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
    reg.upsert(ProviderConfig(name="mini1", base_url="http://m/v1", engine="mlx-lm", tier="local", model="qwen-30b"))
    rp = tmp_path / "r.yaml"; rp.write_text(ROUTING)
    gate = EgressGate(registry=reg, routing=RoutingTable.from_yaml(rp),
                      trace=TraceStore(tmp_path / "t.db"), transport=fake_transport)
    scores = await run_eval(gate, tmp_path / "cases", tmp_path / "report.md")
    assert len(scores) == 1
    assert (tmp_path / "report.md").exists()
    assert gate.trace.summary()["dispatches"] == 1          # went through the gate, traced
