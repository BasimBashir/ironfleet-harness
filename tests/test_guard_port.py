# tests/test_guard_port.py
from harness.spike.guard_port import portable_grounding_guard

def test_guard_annotates_ungrounded_citations():
    draft = "The threshold is $3,000 [Imaginary Act 2026, s 9] and it is met [Insolvency Act 2006, s 214]."
    res = portable_grounding_guard(draft, allowed_authorities=["Insolvency Act 2006, s 214"])
    assert res.ungrounded == ["[Imaginary Act 2026, s 9]"]
    assert "[UNGROUNDED" in res.annotated and "Insolvency Act 2006, s 214" in res.annotated

def test_guard_passes_when_all_grounded():
    draft = "Met as required [Insolvency Act 2006, s 214]."
    res = portable_grounding_guard(draft, allowed_authorities=["Insolvency Act 2006, s 214"])
    assert res.ungrounded == [] and res.annotated == draft
