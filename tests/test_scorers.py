# tests/test_scorers.py
from harness.eval.golden_case import GoldenCase
from harness.eval.scorers import score_case

def test_score_case_counts_citations_and_checks():
    case = GoldenCase(id="c", matter_type="m", task_class="drafting", prompt="p",
                      expected_citations=["[Insolvency Act 2006, s 214]", "[Companies Act 1993, s 289]"],
                      required_grounding=["prescribed amount"],
                      persona_checks={"structure": "PARTIES"})
    out = ("PARTIES ... DEBT ... As to the threshold, the prescribed amount applies [Insolvency Act 2006, s 214].")
    s = score_case(out, case)
    assert s.citation_accuracy == 0.5                     # 1 of 2 verbatim
    assert s.grounding_score == 1.0
    assert s.checks["structure"] is True
