# tests/test_corpus.py — R1 Tasks 1-3: splitter, per-matter store, hybrid search
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


# ---------------------------------------------------------------- R1 Task 2: the store

def test_ingest_and_lexical_roundtrip(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    doc = DocRecord(doc_id="real-Case1",
                    text="INTRO\n\nThe PPSA governs priority.\n\n"
                         "S 292 VOIDABLE TRANSACTIONS\n\nA gift is voidable.",
                    source_name="Case1.pdf")
    n = store.ingest("m-a", doc, vectors=[[0.0, 0.0]] * 2,
                     model="bge-m3:567m", provider="ollama-embed")
    assert n == 2  # two paragraphs -> two chunks
    assert store.doc_count("m-a") == 1
    hits = store.search_lexical("m-a", "PPSA priority", k=5)
    assert hits and "PPSA" in hits[0].text and hits[0].source_name == "Case1.pdf"


def test_per_matter_isolation_both_directions(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    store.ingest("m-a", DocRecord("real-A", "AAA matter one body", "a.pdf"),
                 [[0.0]], "m", "p")
    store.ingest("m-b", DocRecord("real-B", "BBB matter two body", "b.pdf"),
                 [[0.0]], "m", "p")
    assert all(h.doc_id != "real-B" for h in store.search_lexical("m-a", "BBB body matter", k=10))
    assert all(h.doc_id != "real-A" for h in store.search_lexical("m-b", "AAA body matter", k=10))


def test_resume_by_hash_skips_known_doc(tmp_path):
    import hashlib
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    doc = DocRecord("real-A", "INTRO\n\nBody text here.", "a.pdf")
    sha = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
    store.ingest("m-a", doc, [[0.0]], "m", "p")
    assert store.has_doc("m-a", sha) is True
    assert store.has_doc("m-a", "0" * 64) is False


def test_matter_ref_sanitised_into_table_names(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    store.ingest("m:bad/ref", DocRecord("real-A", "INTRO\n\nBody.", "a.pdf"), [[0.0]], "m", "p")
    assert store.doc_count("m:bad/ref") == 1  # worked, colon-free tables under the hood
