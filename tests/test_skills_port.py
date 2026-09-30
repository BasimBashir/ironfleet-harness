# tests/test_skills_port.py
from pathlib import Path
import pytest
from harness.module_e.skills import normalise_skill_md, sync_skills

DATA = Path(__file__).resolve().parent.parent / "data" / "module-e"

def test_all_twenty_six_skills_are_ported():
    d = DATA / "skills"
    assert sorted(p.name for p in d.iterdir() if p.is_dir()) == sorted([
        "affidavit-formatter", "correspondence-tone-analyser", "exhibit-numberer",
        "hearing-bundle-assembler", "nz-context-compression", "nz-contract-review-analyzer",
        "nz-contract-reviewer", "nz-court-calendar", "nz-data-structure-protocol",
        "nz-differential-review", "nz-imca-2016-calculator", "nz-kreuzberg-ingestor",
        "nz-limitation-act-checker", "nz-memory-systems", "nz-nutrient-processor",
        "nz-penalty-clause-analyzer", "nz-property-based-testing", "nz-recursive-decomposition",
        "nz-security-interest-checker", "nz-solvency-assessor", "nz-statutory-demand-validator",
        "nz-varlock", "pagination-index-mapper", "summariser", "what-if-dashboard",
        "without-prejudice-detector"])

def test_every_skill_dir_has_a_skill_md():
    for p in (DATA / "skills").iterdir():
        if p.is_dir():
            assert (p / "SKILL.md").is_file(), p.name

def test_normalise_sets_name_to_the_directory_name():
    out = normalise_skill_md("---\ndescription: Some skill that does a thing in NZ law\n---\nbody\n",
                             "nz-court-calendar")
    assert "name: nz-court-calendar" in out.split("---")[1]

def test_normalise_rejects_a_name_that_disagrees_with_the_directory():
    raw = "---\nname: WrongName\ndescription: Some skill that does a thing in NZ law\n---\nx\n"
    with pytest.raises(ValueError):
        normalise_skill_md(raw, "nz-court-calendar")

def test_normalise_requires_a_substantial_description():
    # opencode surfaces the description to the model for trigger-matching; a thin one makes the
    # skill unreachable in practice.
    with pytest.raises(ValueError):
        normalise_skill_md("---\nname: x\ndescription: too short\n---\nx\n", "x")

def test_sync_skills_writes_into_the_workspace_tree():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "skills"
        paths = sync_skills(DATA / "skills", out)
        assert len(paths) == 26
        assert (out / "nz-court-calendar" / "SKILL.md").is_file()
