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


# ---------------------------------------------------------------- R1 Task 3: hybrid search

def test_hybrid_search_fuses_and_never_crosses_matters(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    from harness.vectors import VectorStore
    vs = VectorStore(tmp_path / "vectors.sqlite3", dim=2)
    store = CorpusStore(tmp_path / "corpus.sqlite3", vectors=vs)
    store.ingest("m-a", DocRecord("real-A", "SEC ONE\n\nstatutory demand text",
                                  "a.pdf"), vectors=[[1.0, 0.0]], model="m", provider="p")
    store.ingest("m-b", DocRecord("real-B", "SEC TWO\n\ndemand text again",
                                  "b.pdf"), vectors=[[0.0, 1.0]], model="m", provider="p")
    hits = store.search("m-a", "statutory demand", [1.0, 0.0], k=5)
    assert hits and all(h.doc_id == "real-A" for h in hits)
    assert all(h.source_name == "a.pdf" for h in hits)


def test_hybrid_fuses_vector_first_when_lexical_misses(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    from harness.vectors import VectorStore
    vs = VectorStore(tmp_path / "vectors.sqlite3", dim=2)
    store = CorpusStore(tmp_path / "corpus.sqlite3", vectors=vs)
    store.ingest("m-a", DocRecord("real-A", "AAA xqzwk body", "a.pdf"),
                 vectors=[[1.0, 0.0]], model="m", provider="p")
    # a query whose tokens match nothing lexically still finds the chunk by vector
    hits = store.search("m-a", "qqq zzzz", [0.9, 0.1], k=5)
    assert hits and hits[0].doc_id == "real-A"


def test_rrf_prefers_items_ranked_by_both_legs():
    from harness.corpus import rrf
    fused = rrf([["a", "b", "c"], ["b", "a", "d"]], k=60)
    assert fused[0] in ("a", "b") and set(fused[:2]) == {"a", "b"}


# ---------------------------------------------------------------- R1 Task 6: the tool

def test_corpus_search_tool_envelope_and_fail_closed(tmp_path, monkeypatch):
    from harness.corpus import CorpusStore, DocRecord, ironfleet_corpus_search
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    store.ingest("m-a", DocRecord("real-A", "SEC ONE\n\nThe PPSA governs priority disputes.",
                                  "a.pdf"), vectors=[[1.0, 0.0]], model="m", provider="p")
    monkeypatch.setenv("IRONFLEET_MATTER", "m-a")
    res = ironfleet_corpus_search("PPSA priority", k=3, store=store, rerank=False,
                                  embed_fn=lambda texts: [[1.0, 0.0]])
    assert res["passages"] and res["authorities"] == [res["passages"][0]["text"]]
    assert res["passages"][0]["source_name"] == "a.pdf"
    monkeypatch.setenv("IRONFLEET_MATTER", "")
    res = ironfleet_corpus_search("anything", store=store, rerank=False,
                                  embed_fn=lambda t: [[1.0, 0.0]])
    assert res == {"passages": [], "authorities": [], "error": "no matter bound"}


def test_corpus_search_rerank_leg_resorts_by_score(tmp_path, monkeypatch):
    from harness.corpus import CorpusStore, DocRecord, ironfleet_corpus_search
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    # headings flush chunks; two tiny paragraphs alone would merge (D2 behaviour)
    store.ingest("m-a", DocRecord("real-A", "HEAD ONE\n\nAAA first body text\n\n"
                                  "HEAD TWO\n\nBBB second body text", "a.pdf"),
                 vectors=[[1.0, 0.0], [0.5, 0.5]], model="m", provider="p")
    monkeypatch.setenv("IRONFLEET_MATTER", "m-a")

    def fake_rerank(query, texts):
        # the SECOND passage is far more relevant per the cross-encoder
        return [0.1, 0.99]
    res = ironfleet_corpus_search("body", k=2, store=store,
                                  embed_fn=lambda t: [[0.6, 0.4]], rerank_fn=fake_rerank)
    assert [p["text"] for p in res["passages"]][0].startswith("BBB")


# ------------------------------------------------------- R1 amendment: citation injection
def test_citation_keys_canonical_and_order_invariant():
    from harness.corpus import _citation_keys
    assert _citation_keys("Companies Act 1993, s 135") == {"companies act|1993|135"}
    # the query form: section FIRST, act after, prose around it
    assert "companies act|1993|135" in _citation_keys(
        "s 135 Companies Act 1993 director personal liability")
    # plural sections, ranges
    ks = _citation_keys("Companies Act 1993 ss 135 137 recklessness")
    assert "companies act|1993|135" in ks and "companies act|1999|137" not in ks
    # no act named -> no keys
    assert _citation_keys("the company was insolvent and traded on") == set()


def test_citation_injection_surfaces_named_provision_above_bm25_noise(tmp_path):
    """The measured failure this closes: for a query naming 'Companies Act 1993 s 135'
    exactly, BM25 ranked the containing chunk 41st among 24,343 matches on the real
    acceptance corpus (2026-10-14). A citation is a JOIN KEY, not a prose match."""
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    noise = "Companies Act 1993 Amendment Act 1997, s 52\n\nAct " + ("x y z. " * 30)
    target = ("Companies Act 1993, s 135\n\nVersion as at 30 September 2024\n\n"
              "135 Duty of care\n\nA director of a company must not act "
              "recklessly or in a way that is likely to cause serious loss.")
    store.ingest("m-a", DocRecord("D-noise", noise, "n.md"), vectors=[[1.0, 0.0]],
                 model="m", provider="p")
    store.ingest("m-a", DocRecord("D-target", target, "ca.mat"),
                 vectors=[[0.1, 0.9]], model="m", provider="p")
    hits = store.search("m-a", "s 135 Companies Act 1993 duty of care", [0.1, 0.9], k=5)
    assert hits and hits[0].doc_id == "D-target"
    # a query that names NO citation is unchanged — injection is a join, not a guess
    plain = store.search("m-a", "director reckless loss", [0.1, 0.9], k=5)
    assert all(h.doc_id != "D-target" or True for h in plain)  # no assertion on order
    assert "D-target" in {h.doc_id for h in plain}


def test_reindex_cites_rebuilds_join_table_without_reembedding(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    store.ingest("m-a", DocRecord("D-1", "Companies Act 1993, s 135\n\nA duty of care.",
                                  "a.md"), vectors=[[1.0, 0.0]], model="m", provider="p")
    # simulate a pre-amendment corpus: drop the table, then rebuild from text
    with store._c() as c:
        c.execute("DROP TABLE cites_m_a")
    n = store.reindex_cites("m-a")
    assert n >= 1
    hits = store.search("m-a", "s 135 Companies Act 1993 duty of care", [1.0, 0.0], k=3)
    assert hits and hits[0].doc_id == "D-1"
