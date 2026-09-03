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

# --- S6-5: citation-form normaliser -------------------------------------------
# The exact-substring scorer was brittle to citation-form variants (S2 findings).
# citation_accuracy now accepts the documented families below. Regex touches only
# the AUTHORED needle (variants); model output is still matched by plain substring.

def _acc(output: str, needle: str) -> float:
    from harness.eval.scorers import citation_accuracy
    return citation_accuracy(output, [needle])

def test_citation_volume_drop_bracket_year():
    # [1965] 1 AC 1175 (needle) vs [1965] AC 1175 (model, volume omitted)
    assert _acc("see National Provincial Bank Ltd v Ainsworth [1965] AC 1175 at 1180",
                "National Provincial Bank Ltd v Ainsworth [1965] 1 AC 1175") == 1.0

def test_citation_statute_prose_order():
    # "Companies Act 1993, s 135" (needle) vs "s 135 of the Companies Act 1993" (model)
    assert _acc("the threshold under s 135 of the Companies Act 1993 is engaged",
                "Companies Act 1993, s 135") == 1.0

def test_citation_statute_commaless_order():
    # needle vs "s 284 Companies Act 1993" (no comma, no "of")
    assert _acc("a director is in breach per s 284 Companies Act 1993",
                "Companies Act 1993, s 284") == 1.0

def test_citation_full_party_name_with_qualifier():
    # short needle vs full party + "(in liquidation)" — cite-only variant carries the hit
    assert _acc("In Yan v Mainzeal International Ltd (in liquidation) [2013] NZSC 20 the court held",
                "Yan v Mainzeal [2013] NZSC 20") == 1.0

def test_citation_hyphenation_normalised():
    # Madsen-Ries (needle) vs Madsen Ries (model, hyphen dropped) and vice versa
    assert _acc("per Madsen Ries v Cooper [2020] NZSC 100", "Madsen-Ries v Cooper [2020] NZSC 100") == 1.0
    assert _acc("per Madsen-Ries v Cooper [2020] NZSC 100", "Madsen Ries v Cooper [2020] NZSC 100") == 1.0

def test_citation_bare_act_pin_year_dropped():
    # year-fragile instrument pin: model cites the act without the year
    assert _acc("that conduct is caught by the Companies Act", "Companies Act 1993") == 1.0

def test_citation_no_false_positive_on_wrong_section_or_page():
    assert _acc("the threshold under s 136 of the Companies Act 1993", "Companies Act 1993, s 135") == 0.0
    assert _acc("Mason v Lewis [2006] 2 NZLR 225", "Mason v Lewis [2006] 3 NZLR 225") == 0.0

def test_citation_exact_substring_still_primary():
    assert _acc("cites [Insolvency Act 2006, s 236] directly", "[Insolvency Act 2006, s 236]") == 1.0
