from pathlib import Path
import yaml

DATA = Path(__file__).resolve().parent.parent / "data" / "module-e"

def _index():
    return yaml.safe_load((DATA / "personas.yaml").read_text())["personas"]

def test_index_names_exactly_the_eighteen_personas():
    # M6 (2026-11-08) adds the plugin's five moot/hearing personas
    names = sorted(p["name"] for p in _index())
    assert names == sorted(["adversary", "ambiguity", "architect", "auditor", "citation",
                            "clerk", "evaluator", "hunter", "ingestor", "negotiator",
                            "strategist", "verifier", "wargamer",
                            "opposing-counsel", "procedural-examiner", "evidence-examiner",
                            "bench", "hearing-coach"])

def test_every_persona_declares_required_fields():
    for p in _index():
        assert set(p) >= {"name", "description", "task_type", "primary",
                          "variants", "allowed_tools", "denied_tools"}, p["name"]
        assert p["description"].strip(), f"{p['name']}: empty description"
        assert p["task_type"], f"{p['name']}: empty task_type"

def test_every_declared_source_file_exists_and_is_non_empty():
    for p in _index():
        for rel in [p["primary"], *p["variants"].values()]:
            f = DATA / "personas" / rel
            assert f.is_file(), f"{p['name']}: missing {rel}"
            assert f.read_text(encoding="utf-8").strip(), f"{p['name']}: empty {rel}"

def test_variant_names_are_known():
    # The only second-prompt shapes the old tree contains.
    allowed = {"glass", "iron", "brain"}
    for p in _index():
        for v in p["variants"]:
            assert v in allowed, f"{p['name']}: unexpected variant {v}"

def test_persona_names_match_their_primary_filename():
    for p in _index():
        assert Path(p["primary"]).name == f"{p['name']}.txt"
