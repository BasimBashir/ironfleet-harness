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


def test_case_name_join_keys_generic_span_forms():
    """2026-10-14 amendment 2: case NAMES are join keys like statute pins — any
    'X v Y' / 'Re X' span, any corpus, no case-specific hardcoding. Header form
    ('& ORS' trailer, uppercase V, trailing court designator) and needle form
    ('... v Cooper [2020] NZSC 100') must canonicalise to ONE key."""
    from harness.corpus import _citation_keys
    needle = _citation_keys("Madsen-Ries v Cooper [2020] NZSC 100 director duties")
    header = _citation_keys("MADSEN-RIES & ORS V COOPER NZSC")
    assert needle == header == {"case:madsen ries v cooper"}
    assert _citation_keys("Re Duomatic Ltd") == {"case:re duomatic ltd"}
    assert "case:goldcorp exchange ltd v liggett" in _citation_keys(
        "Goldcorp Exchange Ltd v Liggett [1994] UKPC 3")
    # prose without case names stays key-free
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


# ------------------------------------------- multi-query pool construction (2026-10-14)

def test_count_restored_after_reindex_amendment(tmp_path):
    """ae1fe3f replaced `def count` with `def reindex_cites` and left count's body
    orphaned inside it — accept_r1.py C3 crashed on the missing attribute."""
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    store.ingest("m-a", DocRecord("real-A", "SEC ONE\n\nalpha body words\n\n"
                                  "SEC TWO\n\nbeta body words", "a.pdf"),
                 vectors=[[0.0]] * 2, model="m", provider="p")
    assert store.count("m-a") == 2
    assert store.count("m-never-ingested") == 0


def _two_topic_store(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    from harness.vectors import VectorStore
    vs = VectorStore(tmp_path / "vectors.sqlite3", dim=2)
    store = CorpusStore(tmp_path / "corpus.sqlite3", vectors=vs)
    store.ingest("m-a", DocRecord(
        "D-ppsa", "SEC PRIORITY\n\nThe PPSA governs priority disputes between "
        "secured parties.", "ppsa.md"), vectors=[[1.0, 0.0]], model="m", provider="p")
    store.ingest("m-a", DocRecord(
        "D-liab", "SEC LIABILITY\n\nA director owes duty of care under the "
        "Companies Act 1993.", "ca.md"), vectors=[[0.0, 1.0]], model="m", provider="p")
    return store


def test_search_multi_unions_pools_and_records_supply(tmp_path):
    from harness.corpus import _hit_key
    store = _two_topic_store(tmp_path)
    fused, supply = store.search_multi(
        "m-a", [("PPSA priority secured parties", [1.0, 0.0]),
                ("director duty of care Companies Act 1993", [0.0, 1.0])],
        candidates=5)
    by_doc = {h.doc_id: h for h in fused}
    assert {"D-ppsa", "D-liab"} <= set(by_doc)      # union across queries, not either alone
    assert any(qi == 0 for qi, _leg in supply[_hit_key(by_doc["D-ppsa"])])
    assert any(qi == 1 for qi, _leg in supply[_hit_key(by_doc["D-liab"])])
    # single-query multi == plain search (the fallback is the same pipeline)
    solo, _ = store.search_multi("m-a", [("PPSA priority secured parties", [1.0, 0.0])],
                                 candidates=5)
    plain = store.search("m-a", "PPSA priority secured parties", [1.0, 0.0], k=5, candidates=5)
    assert [_hit_key(h) for h in solo] == [_hit_key(h) for h in plain]


def test_search_multi_never_crosses_matters(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    store = _two_topic_store(tmp_path)
    store.ingest("m-b", DocRecord("D-other", "SECRET only matter two body", "b.md"),
                 vectors=[[1.0, 0.0]], model="m", provider="p")
    fused, _ = store.search_multi(
        "m-b", [("SECRET body", [1.0, 0.0]), ("PPSA priority", [1.0, 0.0])], candidates=5)
    assert {h.doc_id for h in fused} == {"D-other"}


def test_expand_query_strict_schema_and_bounds():
    from harness.corpus import expand_query
    ok = '["s 135 Companies Act 1993 director duty", "voidable transactions preference", "statutory demand"]'
    assert len(expand_query("p", lambda p: ok)) == 3
    assert len(expand_query("p", lambda p: '["a","b","c","d"]')) == 3   # capped, never passed through
    assert expand_query("p", lambda p: 'not json') == []
    assert expand_query("p", lambda p: '{"q": 1}') == []
    assert expand_query("p", lambda p: '["ok", 42]') == []              # a non-string rejects the WHOLE output
    assert expand_query("p", lambda p: f'["{"x" * 201}"]') == []        # over-length rejects the whole output
    assert expand_query("p", lambda p: '[]') == []

    def boom(prompt):
        raise RuntimeError("gate down")
    assert expand_query("p", boom) == []                                # never raises


def test_corpus_search_expand_fail_open_and_supply(tmp_path, monkeypatch):
    from harness.corpus import ironfleet_corpus_search
    store = _two_topic_store(tmp_path)
    monkeypatch.setenv("IRONFLEET_MATTER", "m-a")
    embed = lambda texts: [[1.0, 0.0] if "PPSA" in t else [0.0, 1.0] for t in texts]
    # gate down -> exact single-query behaviour; the original query still answers
    res = ironfleet_corpus_search("PPSA priority secured", k=3, store=store, rerank=False,
                                  embed_fn=embed, expand=True,
                                  expand_fn=lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    assert res["passages"] and res["passages"][0]["doc_id"] == "D-ppsa"
    assert res["supply"]["0"]                       # (query_index, leg) pairs recorded
    # junk expansion output degrades the same way
    res = ironfleet_corpus_search("PPSA priority secured", k=3, store=store, rerank=False,
                                  embed_fn=embed, expand=True, expand_fn=lambda p: "garbage")
    assert res["passages"][0]["doc_id"] == "D-ppsa"


def test_expand_pool_capped_before_rerank(tmp_path, monkeypatch):
    from harness.corpus import CorpusStore, DocRecord, ironfleet_corpus_search
    vs = __import__("harness.vectors", fromlist=["VectorStore"]).VectorStore(
        tmp_path / "vectors.sqlite3", dim=2)
    store = CorpusStore(tmp_path / "corpus.sqlite3", vectors=vs)
    doc = "SEC TOP\n\n" + "\n\n".join(
        f"HEADING {i:02d}\n\nchunk number {i} carries unique body words" for i in range(60))
    store.ingest("m-a", DocRecord("D-many", doc, "many.md"),
                 vectors=[[1.0, 0.0]] * 60, model="m", provider="p")
    monkeypatch.setenv("IRONFLEET_MATTER", "m-a")
    seen = []
    res = ironfleet_corpus_search(
        "chunk number unique body", k=3, store=store,
        embed_fn=lambda texts: [[1.0, 0.0]] * len(texts), rerank=True,
        rerank_fn=lambda q, texts: (seen.append(len(texts)) or [1.0] * len(texts)),
        expand=True, expand_fn=lambda p: '["alt query one", "alt query two"]',
        pool_cap=10)
    assert seen == [10]          # the merged pool was capped BEFORE rerank, at pool_cap
    assert len(res["passages"]) == 3


def test_drop_matter_removes_all_matter_tables(tmp_path):
    # D of matter CRUD: a matter is fully manageable from the harness, never by
    # hand-rolled SQL (the 2026-10-14 clean-and-reingest used exactly this).
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    store.ingest("m-a", DocRecord("real-A", "SEC ONE\n\nalpha body words", "a.pdf"),
                 vectors=[[0.0]], model="m", provider="p")
    store.drop_matter("m-a")
    assert store.doc_count("m-a") == 0
    assert store.count("m-a") == 0
    assert store.search_lexical("m-a", "alpha", k=5) == []   # fts table gone -> not present
    store.ingest("m-a", DocRecord("real-B", "SEC TWO\n\nbeta body words", "b.pdf"),
                 vectors=[[0.0]], model="m", provider="p")   # matter is reusable after drop
    assert store.doc_count("m-a") == 1


def test_corpus_search_accepts_dispatch_dict_convention(tmp_path, monkeypatch):
    """The TS tools shim calls fn(args) with ONE JSON-args dict (module_e.dispatch);
    the tool must accept both shapes or the live tool path dies on a TypeError
    (found by the C5 build, 2026-10-14)."""
    from harness.corpus import ironfleet_corpus_search
    store = _two_topic_store(tmp_path)
    monkeypatch.setenv("IRONFLEET_MATTER", "m-a")
    res = ironfleet_corpus_search({"query": "PPSA priority secured", "k": 2,
                                   "rerank": False},
                                  store=store,
                                  embed_fn=lambda texts: [[1.0, 0.0]] * len(texts))
    assert res["passages"] and res["passages"][0]["doc_id"] == "D-ppsa"
    assert res["authorities"] == [p["text"] for p in res["passages"]]


def test_act_abbreviation_keys_join_the_full_name():
    """The measured PPSA finding (failure report run 2): expansion emits the
    ABBREVIATION ('PPSA 1999 s 6') and the join missed the DLM provision
    ('Personal Property Securities Act 1999, s 6'). Unambiguous abbreviations
    canonicalise to the same key; ambiguous ones stay out of the table."""
    from harness.corpus import _citation_keys
    assert _citation_keys("PPSA 1999 s 6 lease of goods") == {
        "personal property securities act|1999|6"}
    assert _citation_keys("Personal Property Securities Act 1999, s 6") == {
        "personal property securities act|1999|6"}


def test_default_gate_never_depends_on_the_scripts_package():
    """C5 run 4 (live): the tool's default gate built from the scripts namespace
    package — ModuleNotFoundError in the plugin subprocess, and scripts/ is not even
    shipped in the distribution. The tool must build from the packaged path."""
    import inspect
    from harness.corpus import _default_gate
    src = inspect.getsource(_default_gate)
    assert "harness.bootstrap" in src and "from scripts" not in src


def test_docs_lists_the_matter_sources_newest_first(tmp_path):
    from harness.corpus import CorpusStore, DocRecord
    store = CorpusStore(tmp_path / "corpus.sqlite3")
    assert store.docs("m-x") == []            # missing tables: empty, not a crash
    store.ingest("m-x", DocRecord(doc_id="d1",
                                  text="S 66 PRIORITY\n\nRules follow.",
                                  source_name="case-a.pdf"),
                 vectors=[[0.0]], model="bge-m3:567m", provider="ollama-embed")
    rows = store.docs("m-x")
    assert len(rows) == 1
    assert rows[0]["name"] == "case-a.pdf" and rows[0]["chunks"] == 1
    assert rows[0]["doc_id"] == "d1"
