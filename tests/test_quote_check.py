# tests/test_quote_check.py — R1 Task 7 (D6 referee) + Task 10 (D9 splice support)
from harness.quote_check import extract_quotes, normalize, quote_audit, span_in_passages


def test_extract_quotes_straight_and_curly():
    t = 'He said "unascertained goods pass no property" and ‘never any bailment’.'
    qs = extract_quotes(t)
    assert any("unascertained" in q for q in qs) and any("bailment" in q for q in qs)


def test_normalize_folds_case_whitespace_hyphens():
    assert normalize("Un-ascertained  GOODS") == normalize("unascertained goods")


def test_normalize_bridges_hyphen_linebreaks():
    assert normalize("no bail- \nment and no trust") == normalize("no bailment and no trust")


def test_quote_found_inside_longer_passage():
    passage = ("III. TITLE TO BULLION\n\nAs Atkin LJ explained, unascertained goods pass "
               "no property until appropriation is unconditional.")
    assert span_in_passages("Unascertained goods pass no property", [passage])


def test_fabricated_quote_is_not_in_passages():
    assert not span_in_passages("the court invented this phrase wholly", ["real text only"])


def test_quote_audit_splits_grounded_from_fabricated():
    passages = ["The PPSA governs priority disputes between competing security interests."]
    draft = ('The PPSA "governs priority disputes" but also "invented nonsense phrase".')
    grounded, ungrounded = quote_audit(draft, passages)
    assert grounded == ["governs priority disputes"]
    assert ungrounded == ["invented nonsense phrase"]


# ---------------------------------------------------------- R1 Task 10: D9 splice support

def test_evidence_window_numbers_sentences_and_splice_restores_verbatim():
    from harness.corpus import evidence_window, splice_references
    passages = [{"source": "Case1.pdf",
                 "text": "The Personal Property Securities Act governs priority disputes. "
                         "Section 16 of the Act defines the perfection requirements fully."}]
    block, table = evidence_window(passages)
    assert "[E1.S1]" in block and "[E1.S2]" in block
    assert table["[E1.S1]"].startswith("The Personal Property Securities Act")
    draft = ("Priority turns on perfection [E1.S2], so the interest was unperfected "
             "[E1.S1].")
    spliced, subbed, invalid = splice_references(draft, table)
    assert subbed == 2 and invalid == 0
    assert spliced.count('"Section 16 of the Act defines the perfection requirements '
                         'fully."') == 1
    assert "[E1.S1]" not in spliced


def test_splice_records_invalid_references_and_leaves_them_visible():
    from harness.corpus import evidence_window, splice_references
    _, table = evidence_window([{"source": "s",
                                 "text": "One sufficiently long sentence sits here now."}])
    spliced, subbed, invalid = splice_references("Claim [E9.S9] and [E1.S1].", table)
    assert subbed == 1 and invalid == 1
    assert "[E9.S9]" in spliced and '"One sufficiently long sentence sits here now."' in spliced


def test_spliced_quotes_pass_the_verbatim_check_by_construction():
    from harness.corpus import evidence_window, splice_references
    from harness.quote_check import quote_audit
    passages = [{"source": "s", "text": "Security interests rank by attachment order."}]
    block, table = evidence_window(passages)
    spliced, _, _ = splice_references("Ranking follows attachment [E1.S1].", table)
    grounded, ungrounded = quote_audit(spliced, [p["text"] for p in passages])
    assert grounded and not ungrounded


# ------------------------------------------------------- guard integration (D6 composes)

def test_guard_blocks_fabricated_quotes_and_passes_spliced_ones():
    from harness.module_e.guard_port import OpenCodeHookAdapter
    passages = ["The Personal Property Securities Act governs priority disputes fully."]
    adapter = OpenCodeHookAdapter()
    ok = adapter.handle({"output": 'The Act "governs priority disputes fully" per s 16.',
                         "allowed": [], "allowed_passages": passages})
    assert ok["decision"] == "approve"
    bad = adapter.handle({"output": 'The Act "wholly invented wording here" per s 16.',
                          "allowed": [], "allowed_passages": passages})
    assert bad["decision"] == "block"
    assert "[UNQUOTED — not in retrieved corpus]" in bad["output"]
    # passages bound EMPTY -> any quote blocks (the D6 contract: no corpus, no licence
    # to quote). An ABSENT key stays legacy (S7c payloads) and skips the quote check.
    none = adapter.handle({"output": 'Any "quoted span whatsoever here" blocks.',
                           "allowed": [], "allowed_passages": []})
    assert none["decision"] == "block"
    legacy = adapter.handle({"output": 'Any "quoted span whatsoever here" blocks.',
                             "allowed": []})
    assert legacy["decision"] == "approve"


def test_guard_needle_check_unchanged_and_composes():
    from harness.module_e.guard_port import portable_grounding_guard
    res = portable_grounding_guard("per [Imaginary Act 2026, s 9]", allowed_authorities=["Real Act"])
    assert res.ungrounded == ["[Imaginary Act 2026, s 9]"]
    res = portable_grounding_guard("plain prose, no quotes", allowed_authorities=[],
                                   allowed_passages=[])
    assert res.ungrounded == []          # a quote-free draft never blocks on passages
