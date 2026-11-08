"""S7i: the improvement-loop driver, orchestration against a stub gate (spec 12 §3.3).

No network, ever: the stub gate replaces EgressGate.dispatch. The house rule that drivers'
main() is never run by the suite holds — these are function-level tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys_path = Path(__file__).resolve().parents[1] / "scripts"
if str(sys_path) not in sys.path:
    sys.path.insert(0, str(sys_path))

import agent_memory_cli  # noqa: E402
from agent_memory_cli import drive_leg, system_for  # noqa: E402
from harness.eval.golden_case import GoldenCase  # noqa: E402
from harness.gate import LLMResponse, ProvenanceReport  # noqa: E402

CASES = [
    GoldenCase(id="c1", matter_type="t", task_class="analysis",
               prompt="p1", expected_citations=["Needle One"],
               required_grounding=["ground one"], persona_checks={"liable": "liable"}),
    GoldenCase(id="c2", matter_type="t", task_class="analysis",
               prompt="p2", expected_citations=[], required_grounding=[], persona_checks={}),
]


class StubGate:
    """Returns a fixed answer per case id — no network, deterministic scores."""
    def __init__(self, answers: dict[str, str | None]):
        self.answers = answers
        self.requests: list = []

    async def dispatch(self, request):
        self.requests.append(request)
        cid = request.matter_ref.rsplit(":", 1)[-1]
        return LLMResponse(content=self.answers.get(cid), provider="stub", model="stub",
                           usage={"tokens_in": 1}, provenance=ProvenanceReport())


def test_system_for_appends_delimited_memory():
    sys_prompt = system_for("PERSONA", "note", 2)
    assert sys_prompt.startswith("PERSONA")
    assert "<!-- ironfleet:memory:v2 begin -->" in sys_prompt and "note" in sys_prompt
    assert system_for("PERSONA", "", 0) == "PERSONA"


@pytest.mark.asyncio
async def test_drive_leg_scores_stubs_and_records_failures():
    gate = StubGate({"c1": "liable. Needle One. ground one", "c2": None})
    recs = await drive_leg(gate, "SYS", CASES, "agent-memory:hunter")
    by_id = {r["case_id"]: r for r in recs}
    assert by_id["c1"]["status"] == "scored" and by_id["c1"]["citation_accuracy"] == 1.0
    assert by_id["c1"]["checks"] == {"liable": True}
    assert by_id["c2"]["status"] == "empty_content"          # cap failure, not a quality zero
    req = gate.requests[0]
    assert req.matter_ref == "agent-memory:hunter:c1" and req.max_tokens == 16384
    assert req.messages[0]["role"] == "system" and req.messages[0]["content"] == "SYS"


@pytest.mark.asyncio
async def test_drive_leg_records_dispatch_exception_and_continues():
    class Boom(StubGate):
        async def dispatch(self, request):
            if request.matter_ref.endswith("c1"):
                raise RuntimeError("proxy down")
            return await super().dispatch(request)

    gate = Boom({"c2": "anything"})
    recs = await drive_leg(gate, "SYS", CASES, "agent-memory:hunter")
    by_id = {r["case_id"]: r for r in recs}
    assert by_id["c1"]["status"] == "failed" and "proxy down" in by_id["c1"]["error"]
    assert by_id["c2"]["status"] == "scored"


from agent_memory_cli import ReflectorError, confirm, reflect, screen  # noqa: E402
from harness.agent_memory import MAX_MEMORY_CHARS  # noqa: E402

PERSONA = "PERSONA BODY"
CUR = "current canon"      # a memory that says nothing useful
GOOD = "memory that fixes cases"


class ScriptedGate(StubGate):
    """Canned answers for probe cases; `reflect_answer` feeds the reflector dispatch."""
    def __init__(self, answers, reflect_answer=""):
        super().__init__(answers)
        self.reflect_answer = reflect_answer

    async def dispatch(self, request):
        if request.matter_ref.endswith(":reflector"):
            return LLMResponse(content=self.reflect_answer, provider="stub", model="stub",
                               usage={}, provenance=ProvenanceReport())
        return await super().dispatch(request)


@pytest.mark.asyncio
async def test_reflect_parses_json_and_tolerates_fences():
    class Fenced:
        async def dispatch(self, request):
            assert request.matter_ref == "agent-memory:hunter:reflector"
            return LLMResponse(content=f"```json\n{{\"memory\": \"{GOOD}\"}}\n```",
                               provider="s", model="m", usage={}, provenance=ProvenanceReport())
    assert await reflect(Fenced(), "hunter", PERSONA, CUR, []) == GOOD


@pytest.mark.asyncio
async def test_reflect_decline_and_garbage():
    decline = ScriptedGate({}, reflect_answer='{"decline": true}')
    assert await reflect(decline, "hunter", PERSONA, CUR, []) is None
    garbage = ScriptedGate({}, reflect_answer="not json at all")
    with pytest.raises(ReflectorError):
        await reflect(garbage, "hunter", PERSONA, CUR, [])


def _seeded_store(tmp_path, *, with_canon=True):
    from harness.agent_memory import MemoryStore, select_probe
    store = MemoryStore(tmp_path / "db.sqlite")
    store.init(["hunter"])
    if with_canon:
        store.set("hunter", CUR, "seed")
    store.seed_suite("hunter", select_probe("hunter", [c.id for c in CASES]))
    return store


@pytest.mark.asyncio
async def test_screen_keeps_candidate_through_confirm(tmp_path):
    store = _seeded_store(tmp_path)

    class Switching(ScriptedGate):
        """Answers wrong under the CURRENT canon, right under GOOD — decided PER REQUEST,
        so the confirm's current leg (CUR prompt) answers wrong again."""
        def __init__(self):
            super().__init__({}, reflect_answer=json.dumps({"memory": GOOD}))

        async def dispatch(self, request):
            if ":reflector" not in request.matter_ref:
                good = GOOD in request.messages[0]["content"]
                self.answers = ({"c1": "liable. Needle One. ground one", "c2": "fine"}
                                if good else {"c1": "nothing useful", "c2": "nothing useful"})
            return await super().dispatch(request)

    result = await screen(store, Switching(), "hunter", PERSONA, CASES)
    assert result["status"] == "kept" and result["version"] == 2
    assert store.get("hunter") == (GOOD, 2)
    assert store.proposal(result["proposal_id"])["status"] == "kept"


@pytest.mark.asyncio
async def test_screen_rolls_back_on_tie(tmp_path):
    store = _seeded_store(tmp_path)
    gate = ScriptedGate({"c1": "liable. Needle One. ground one", "c2": "fine"},
                        reflect_answer=json.dumps({"memory": GOOD}))
    result = await screen(store, gate, "hunter", PERSONA, CASES)   # same answers both legs → tie
    assert result["status"] == "rolled_back"
    assert store.get("hunter") == (CUR, 1)
    assert store.proposal(result["proposal_id"])["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_screen_rejected_proposal_is_recorded_not_applied(tmp_path):
    store = _seeded_store(tmp_path, with_canon=False)
    gate = ScriptedGate({}, reflect_answer=json.dumps({"memory": "x" * (MAX_MEMORY_CHARS + 5)}))
    result = await screen(store, gate, "hunter", PERSONA, CASES)
    assert result["status"] == "rejected"
    assert store.get("hunter") == ("", 0)          # canon untouched
    assert store.proposal(result["proposal_id"])["status"] == "rejected"


@pytest.mark.asyncio
async def test_confirm_decides_and_records(tmp_path):
    store = _seeded_store(tmp_path)
    pid = store.propose("hunter", GOOD)

    class PerRequest(ScriptedGate):
        """The proposal is genuinely better: wrong answers under CUR, right under GOOD."""
        def __init__(self):
            super().__init__({})

        async def dispatch(self, request):
            good = GOOD in request.messages[0]["content"]
            self.answers = ({"c1": "liable. Needle One. ground one", "c2": "fine"}
                            if good else {"c1": "nothing useful", "c2": "nothing useful"})
            return await super().dispatch(request)

    verdict = await confirm(store, PerRequest(), "hunter", PERSONA, CASES, pid,
                            proposal_body=GOOD, current_body=CUR, current_version=1)
    assert verdict == "kept" and store.get("hunter") == (GOOD, 2)
    legs = store.legs(pid, "confirm")
    assert set(legs) == {"current", "proposed"} and legs["current"].n_cases == 2


def test_cmd_main_get_and_history(tmp_path, capsys):
    from harness.agent_memory import MemoryStore
    store = MemoryStore(tmp_path / "db.sqlite")
    store.init(["hunter"])
    assert agent_memory_cli.cmd_main(["get", "hunter"], store) == 0
    assert "version 0" in capsys.readouterr().out
    store.set("hunter", "note", "test")
    assert agent_memory_cli.cmd_main(["history", "hunter"], store) == 0
    out = capsys.readouterr().out
    assert "note" in out and "v1" in out


def test_cmd_main_init_is_idempotent_and_reports(tmp_path, capsys):
    from harness.agent_memory import MemoryStore
    store = MemoryStore(tmp_path / "db.sqlite")
    assert agent_memory_cli.cmd_main(["init"], store) == 0
    assert agent_memory_cli.cmd_main(["init"], store) == 0
    assert "18" in capsys.readouterr().out          # 18 personas from the real personas.yaml (M6 adds 5)


def test_cmd_main_revert_restores_exact_bytes(tmp_path, capsys):
    from harness.agent_memory import MemoryStore
    store = MemoryStore(tmp_path / "db.sqlite")
    store.init(["hunter"])
    store.set("hunter", "old body", "v1")
    store.set("hunter", "new body", "v2")
    assert agent_memory_cli.cmd_main(["revert", "hunter", "1"], store) == 0
    body, version = store.get("hunter")
    assert (body, version) == ("old body", 3)     # history never rewritten — new version, old bytes


def test_cmd_main_unknown_subcommand_fails_loud(tmp_path):
    from harness.agent_memory import MemoryStore
    store = MemoryStore(tmp_path / "db.sqlite")
    with pytest.raises(SystemExit):
        agent_memory_cli.cmd_main(["wat"], store)


@pytest.mark.asyncio
async def test_screen_reflector_garbage_is_recorded_rejected_not_crashed(tmp_path):
    store = _seeded_store(tmp_path)
    gate = ScriptedGate({}, reflect_answer="prose, not JSON")
    result = await screen(store, gate, "hunter", PERSONA, CASES)
    assert result["status"] == "rejected"
    assert store.proposal(result["proposal_id"])["status"] == "rejected"
    assert store.get("hunter") == (CUR, 1)          # canon untouched, iteration survived
