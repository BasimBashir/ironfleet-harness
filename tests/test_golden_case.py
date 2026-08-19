from harness.eval.golden_case import load_cases

def test_load_seed_cases(tmp_path):
    (tmp_path / "a.yaml").write_text("""
id: seed-imca-001
matter_type: debt-enforcement
task_class: drafting
prompt: |
  Draft a statutory demand notice for a debt of $12,400 incurred 2026-03-01 under the
  Insolvency Act 2006? Do not answer; this is a fixed test prompt.
expected_citations:
  - "[Insolvency Act 2006, s 214]"
required_grounding:
  - "Insolvency Act 2006 s 214 requires the debt to exceed the prescribed amount"
persona_checks:
  structure: "Output contains the sections: PARTIES, DEBT, DEMAND, CONSEQUENCES"
""")
    cases = load_cases(tmp_path)
    assert len(cases) == 1
    c = cases[0]
    assert c.id == "seed-imca-001" and c.task_class == "drafting"
    assert c.expected_citations == ["[Insolvency Act 2006, s 214]"]
    assert "PARTIES" in c.persona_checks["structure"]
