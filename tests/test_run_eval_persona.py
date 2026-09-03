# tests/test_run_eval_persona.py
import importlib.util
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_eval_persona_ollama.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_eval_persona_ollama", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _case(cid: str, matter: str) -> str:
    return yaml.safe_dump({
        "id": cid, "matter_type": matter, "task_class": "analysis",
        "prompt": f"prompt for {cid}",
        "expected_citations": [f"cite-{cid}"], "required_grounding": [f"ground-{cid}"],
        "persona_checks": {"ok": "ok"},
    })


def test_parity_subset_one_per_cluster_first_by_id(tmp_path):
    mod = _load()
    # deliberately unsorted file order: selection must key off id, not glob order
    for name, cid, matter in [
        ("b.yaml", "gc-dir-002-x", "directors-duties"),
        ("a.yaml", "gc-dir-001-x", "directors-duties"),
        ("c.yaml", "gc-liq-001-x", "liquidators-duties"),
        ("d.yaml", "gc-ppsa-009-x", "ppsa-priority"),
        ("e.yaml", "gc-ppsa-001-x", "ppsa-priority"),
        ("f.yaml", "gc-recv-001-x", "receivership"),
        ("g.yaml", "gc-misc-001-x", "insolvency-general"),
    ]:
        (tmp_path / name).write_text(_case(cid, matter), encoding="utf-8")
    picked = mod.select_parity_subset(mod.load_cases(tmp_path))
    assert [c.id for c in picked] == [
        "gc-dir-001-x", "gc-liq-001-x", "gc-misc-001-x",
        "gc-ppsa-001-x", "gc-recv-001-x",
    ]


def test_build_messages_mounts_persona_verbatim_as_system():
    mod = _load()
    case = mod.GoldenCase.model_validate(yaml.safe_load(_case("gc-x-001-x", "ppsa-priority")))
    msgs = mod.build_messages(case)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"] == mod.PERSONA_PORT["system_prompt"]
    assert msgs[1]["content"] == case.prompt

def test_rescore_sidecars_normaliser_lifts_citations_only(tmp_path):
    import json
    mod = importlib.util.spec_from_file_location(
        "rescore_sidecars",
        Path(__file__).resolve().parents[1] / "scripts" / "rescore_sidecars.py")
    rs = importlib.util.module_from_spec(mod); mod.loader.exec_module(rs)
    case = yaml.safe_dump({
        "id": "gc-x-001", "matter_type": "m", "task_class": "analysis", "prompt": "p",
        "expected_citations": ["Companies Act 1993, s 135"],
        "required_grounding": ["prescribed amount"], "persona_checks": {},
    })
    d = tmp_path / "cases"; d.mkdir(); (d / "c.yaml").write_text(case, encoding="utf-8")
    records = [
        {"id": "gc-x-001", "citation_accuracy": 0.0, "grounding_score": 1.0,
         "content": "the threshold under s 135 of the Companies Act 1993 involves a prescribed amount"},
        {"id": "gc-x-404", "citation_accuracy": 0.0, "grounding_score": 0.0, "content": "x"},   # no case
        {"id": "gc-x-002", "citation_accuracy": None, "grounding_score": None, "content": None},  # refused
    ]
    out = rs.rescore(records, {c.id: c for c in rs.load_cases(d)})
    assert out[0]["new_citation_accuracy"] == 1.0        # normaliser lifts the prose-order cite
    assert out[0]["new_grounding_score"] == 1.0          # grounding unchanged
    assert out[1]["new_citation_accuracy"] is None       # unmatched id -> skipped honestly
    assert out[2]["new_citation_accuracy"] is None       # no content -> not re-scored
