# tests/test_corpus.py — R1 Task 1: the promoted structure-aware splitter
from harness.corpus import Chunk, chunk_text, split_structure


def test_headings_carry_onto_chunks():
    doc = ("GOLDCORP EXCHANGE LTD V LIGGETT\n\nIntro para one.\n\n"
           "III. TITLE TO BULLION\n\nPara under heading one.\n\n"
           "IV. CONCLUSION\n\nFinal para.\n\n")
    cs = split_structure("d1", doc)
    assert [c.heading for c in cs] == [
        "GOLDCORP EXCHANGE LTD V LIGGETT", "III. TITLE TO BULLION", "IV. CONCLUSION"]
    assert all(c.doc_id == "d1" for c in cs)


def test_oversized_paragraph_is_hard_split_under_2x_target():
    doc = "BODY\n\n" + ("Long paragraph. " * 400)
    cs = split_structure("d2", doc)
    assert cs, "hard split produced nothing"
    assert all(len(c.text.split()) <= 210 * 2 + 20 for c in cs)


def test_empty_doc_yields_zero_chunks():
    assert split_structure("d3", "") == []


def test_chunk_text_prefixes_heading():
    cs = chunk_text("d4", "IV. SOLE HEADING\n\nOnly paragraph here.")
    assert cs == ["IV. SOLE HEADING\nOnly paragraph here."]
