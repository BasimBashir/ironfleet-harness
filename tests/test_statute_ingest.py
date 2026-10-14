# tests/test_statute_ingest.py — R1 plan Task 11: provision parser + the licence gate
from pathlib import Path

from scripts.statute_ingest import ingest_statutes, licence_check, parse_provisions

_CA_SAMPLE = """Companies Act 1993
1993 No 105

297 Requirements for solvency statement
(1) A solvency statement must state that, in the opinion of the directors,
the company will be able to pay its debts.
(2) Subsection (1) applies to a company that is not in liquidation.

298 Effect of solvency statement
A solvency statement is conclusive evidence of solvency.

1 Title
This is the short title of an earlier section and stays preamble material
when no prior section exists."""


def _store(tmp_path):
    from harness.corpus import CorpusStore
    from harness.vectors import VectorStore
    return CorpusStore(tmp_path / "c.sqlite3",
                       vectors=VectorStore(tmp_path / "v.sqlite3", dim=2))


def test_parse_provisions_one_record_per_section():
    provs = parse_provisions("Companies Act 1993", _CA_SAMPLE)
    pins = [p.source_name for p in provs]
    assert "Companies Act 1993, s 297 Requirements for solvency statement" in pins
    assert "Companies Act 1993, s 298 Effect of solvency statement" in pins
    by_src = {p.source_name: p for p in provs}
    body = next(v.text for k, v in by_src.items() if k.startswith("Companies Act 1993, s 297"))
    assert "conclusive evidence" not in body          # s 297 body stops before s 298
    assert "pay its debts" in body


def test_provision_texts_are_verbatim_from_the_source():
    provs = parse_provisions("Companies Act 1993", _CA_SAMPLE)
    joined = "\n".join(p.text for p in provs)
    assert "state that, in the opinion of the directors" in joined   # exact source words


def test_licence_gate_refuses_without_provenance(tmp_path):
    src = tmp_path / "ca.txt"
    src.write_text(_CA_SAMPLE, encoding="utf-8")
    # no licence/source_url/retrieved -> refusal; fail-closed, never an assumption
    assert "licence" in (licence_check({"file": str(src), "act": "Companies Act 1993"}) or "")
    assert "retrieved" in (licence_check({"file": str(src), "act": "A", "licence": "CC BY 4.0",
                                          "source_url": "https://x"}) or "")
    assert "not found" in (licence_check({"file": str(tmp_path / "nope.txt"), "act": "A",
                                          "licence": "CC BY 4.0", "source_url": "u",
                                          "retrieved": "2026-10-13"}) or "")
    assert licence_check({"file": str(src), "act": "Companies Act 1993",
                          "licence": "CC BY 4.0", "source_url": "https://legislation.govt.nz/x",
                          "retrieved": "2026-10-13"}) is None


def test_ingest_refuses_unlicensed_and_ingests_licensed(tmp_path):
    import yaml
    src = tmp_path / "ca.txt"
    src.write_text(_CA_SAMPLE, encoding="utf-8")
    manifest = [
        {"file": str(src), "act": "Companies Act 1993"},                # unlicensed -> refused
        {"file": str(src), "act": "Companies Act 1993", "licence": "CC BY 4.0",
         "source_url": "https://legislation.govt.nz/act/public/1993/0105/latest",
         "retrieved": "2026-10-13"},                                    # licensed -> ingested
    ]
    calls = []

    def embed_fn(texts):
        calls.append(len(texts))
        return [[0.5, 0.5] for _ in texts]
    report = ingest_statutes("m-a", manifest, _store(tmp_path), embed_fn,
                         min_words=20)
    assert report["refused"] and "licence" in report["refused"][0]
    assert report["ingested"] == ["ca.txt"]   # general core reports file-centric
    assert report["provisions"] >= 2
    assert sum(calls) >= report["provisions"]        # embedded 1:1, nothing silent


def test_ingested_statute_section_is_retrievable_by_needle(tmp_path):
    from scripts.statute_ingest import parse_provisions
    # the acceptance-critical property: 'Companies Act 1993, s 297' surfaces the section
    store = _store(tmp_path)
    for prov in parse_provisions("Companies Act 1993", _CA_SAMPLE):
        store.ingest("m-a", prov, vectors=[[float(len(prov.text) % 7) / 7, 0.3]],
                     model="m", provider="p")
    hits = store.search_lexical("m-a", "solvency statement requirements 297", k=5)
    assert hits and "297" in hits[0].source_name
    from harness.eval.scorers import citation_hit
    blob = "\n".join(h.text for h in hits)
    assert citation_hit(blob, "Companies Act 1993, s 297")


def test_parser_chain_reaches_docx_without_custom_code(tmp_path):
    # the user's future-proofing requirement: new FORMAT, not new script. markitdown
    # converts docx; the chain tries it first and falls back gracefully when absent.
    from harness.ingest_generic import extract_text
    txt = tmp_path / "plain.txt"
    txt.write_text("HEADING\n\nplain body " * 10, encoding="utf-8")
    assert "plain body" in extract_text(txt)           # chain never breaks the text path
    try:
        import docx  # noqa: F401
        from docx import Document
        d = Document()
        d.add_paragraph("DOCX body text for the parser chain test.")
        d.save(tmp_path / "t.docx")
        assert "DOCX body text" in extract_text(tmp_path / "t.docx")
    except ImportError:
        pass                            # python-docx absent: markitdown's own docx leg suffices


def test_detect_kind_judgment_page_numbers_are_not_statutes():
    # the live false positive: extracted judgment PDFs spray standalone page numbers
    from harness.ingest_generic import detect_kind
    judgment = "\n".join(
        [f"para text about the parties and the law {i} with enough words here to look real."
         if i % 37 else str(i) for i in range(300)])
    assert detect_kind(judgment) == "prose"
    statute = ("Companies Act 1993\n1993 No 105\nVersion as at 30 September 2024\n\n"
               + "\n".join(f"{n}\nSection {n} body text with sufficient words to pass the floor."
                           for n in range(1, 30)))
    assert detect_kind(statute) == "statute"
