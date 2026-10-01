# tests/test_vectors.py — A-4 thin local vector index (spec §4)
import sqlite3
import pytest
from harness.vectors import VectorStore, SearchHit

def test_round_trip_top_hit_is_the_query_vector(tmp_path):
    store = VectorStore(tmp_path / "v.db")
    texts = ["contract termination clause", "tax evasion statute", "property boundary dispute"]
    vecs = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
    added = store.add("M-1", texts, vecs, model="bge-m3:567m", provider="ollama-embed")
    assert added == 3
    hits = store.search("M-1", [1.0, 0.0, 0.0, 0.0], k=2)
    assert isinstance(hits[0], SearchHit)
    assert hits[0].text == "contract termination clause"
    assert hits[0].score == pytest.approx(1.0)          # exact self-match
    assert len(hits) == 2                                # k respected

def test_search_never_returns_another_matters_vectors(tmp_path):
    # matter_ref scoping is a confidentiality property, not a convenience (spec §4).
    store = VectorStore(tmp_path / "v.db")
    store.add("M-1", ["contract clause"], [[1.0, 0.0]], model="m", provider="p")
    store.add("M-2", ["unrelated statute"], [[0.0, 1.0]], model="m", provider="p")
    assert [h.text for h in store.search("M-1", [1.0, 0.0])] == ["contract clause"]
    # M-2's own row is orthogonal to the query (score 0.0) yet is still its own hit — a
    # store that dropped zero-score hits could not satisfy test 1's k=2-among-3 case. The
    # confidentiality property is that M-1's vector never surfaces in M-2's search.
    assert [h.text for h in store.search("M-2", [1.0, 0.0])] == ["unrelated statute"]
    assert store.count("M-1") == 1 and store.count("M-2") == 1

def test_dim_mismatch_and_corrupt_rows_are_skipped_not_fatal(tmp_path):
    # A row whose stored dim disagrees with the query, or whose BLOB is not a float32
    # multiple, is skipped with its id recorded — never a crash on the search path.
    store = VectorStore(tmp_path / "v.db")
    store.add("M-1", ["good row"], [[1.0, 0.0, 0.0, 0.0]], model="m", provider="p")
    con = sqlite3.connect(tmp_path / "v.db")
    try:
        con.execute(
            "INSERT INTO embeddings(matter_ref,seq,text,model,provider,dim,vector,ts) "
            "VALUES('M-1',1,'wrong dim','m','p',2,X'00003C00',NULL)")       # 2 floats, dim=2
        con.execute(
            "INSERT INTO embeddings(matter_ref,seq,text,model,provider,dim,vector,ts) "
            "VALUES('M-1',2,'corrupt','m','p',4,X'010203',NULL)")            # 3 bytes, dim=4
        con.commit()
    finally:
        con.close()
    hits = store.search("M-1", [1.0, 0.0, 0.0, 0.0], k=10)
    assert [h.text for h in hits] == ["good row"]
    assert sorted(store.last_skipped) == [2, 3]

def test_search_on_unknown_matter_is_empty(tmp_path):
    store = VectorStore(tmp_path / "v.db")
    assert store.search("M-x", [1.0, 0.0]) == []

def test_add_rejects_mismatched_lengths(tmp_path):
    store = VectorStore(tmp_path / "v.db")
    with pytest.raises(ValueError):
        store.add("M-1", ["a", "b"], [[1.0]], model="m", provider="p")
