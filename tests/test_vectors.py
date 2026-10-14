# tests/test_vectors.py — A-4 vector index, NOW on sqlite-vec (R1 plan Task 4, spec 14 D4).
# The S7e interface is unchanged (add/search/count, SearchHit, per-matter confidentiality);
# the implementation contract changed by the named swap: schema-dim store, fail-loud
# mismatch (the old pure-Python scan's skip-list is gone — an index that silently shrinks
# is the prefix-embedding lie), vectors normalised at add so score = exact cosine.
import sqlite3

import pytest

from harness.vectors import SearchHit, VectorStore


def test_round_trip_top_hit_is_the_query_vector(tmp_path):
    store = VectorStore(tmp_path / "v.db", dim=4)
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
    # matter_ref scoping is a confidentiality property, not a convenience (spec §4) —
    # now enforced by the vec0 PARTITION KEY, not by filtering a shared scan.
    store = VectorStore(tmp_path / "v.db", dim=2)
    store.add("M-1", ["contract clause"], [[1.0, 0.0]], model="m", provider="p")
    store.add("M-2", ["unrelated statute"], [[0.0, 1.0]], model="m", provider="p")
    assert [h.text for h in store.search("M-1", [1.0, 0.0])] == ["contract clause"]
    assert [h.text for h in store.search("M-2", [1.0, 0.0])] == ["unrelated statute"]
    assert store.count("M-1") == 1 and store.count("M-2") == 1


def test_search_on_unknown_matter_is_empty(tmp_path):
    store = VectorStore(tmp_path / "v.db", dim=2)
    assert store.search("M-x", [1.0, 0.0]) == []


def test_add_rejects_mismatched_lengths(tmp_path):
    store = VectorStore(tmp_path / "v.db", dim=2)
    with pytest.raises(ValueError):
        store.add("M-1", ["a", "b"], [[1.0]], model="m", provider="p")


def test_dim_mismatch_fails_loud_at_add(tmp_path):
    # D4: a row that is not schema-dim is REFUSED, never stored-and-skipped — an index
    # that silently shrinks looks complete and is not (the prefix-embedding lie).
    store = VectorStore(tmp_path / "v.db", dim=4)
    with pytest.raises(ValueError):
        store.add("M-1", ["wrong dim"], [[1.0, 0.0]], model="m", provider="p")
    assert store.count("M-1") == 0


def test_normalised_vectors_score_exact_cosine(tmp_path):
    # [2,0] and [1,0] are the same direction: self-similarity must be 1.0 either way.
    store = VectorStore(tmp_path / "v.db", dim=2)
    store.add("M-1", ["scaled", "unit"], [[2.0, 0.0], [1.0, 0.0]], model="m", provider="p")
    hits = store.search("M-1", [1.0, 0.0], k=2)
    assert all(h.score == pytest.approx(1.0) for h in hits)


def test_missing_extension_fails_closed(tmp_path, monkeypatch):
    # D4: no silent pure-Python fallback. A broken extension path must stop construction.
    import sqlite_vec
    monkeypatch.setattr(sqlite_vec, "loadable_path",
                        lambda: tmp_path / "does-not-exist.so")
    with pytest.raises(RuntimeError, match="fail-closed"):
        VectorStore(tmp_path / "v.db", dim=2)


def test_add_is_idempotent_per_matter_and_text(tmp_path):
    # 2026-10-14 live finding: interrupted-then-rerun ingests appended DUPLICATE rows
    # (48,436 rows / 18,845 distinct texts on the acceptance store), and duplicate KNN
    # rows crowd out unique chunks at depth. Re-adds must be ignored, first write wins.
    store = VectorStore(tmp_path / "v.db", dim=2)
    store.add("M-1", ["alpha body", "beta body"], [[1.0, 0.0], [0.0, 1.0]],
              model="m", provider="p")
    store.add("M-1", ["alpha body", "gamma body"], [[0.5, 0.5], [0.9, 0.1]],
              model="m", provider="p")            # alpha re-added with a NEW vector
    assert store.count("M-1") == 3                # not 4 — alpha stored once
    hits = store.search("M-1", [1.0, 0.0], k=10)
    texts = [h.text for h in hits]
    assert len(texts) == len(set(texts))          # no duplicate texts can ever surface
    alpha = [h for h in hits if h.text == "alpha body"]
    assert len(alpha) == 1 and alpha[0].score == pytest.approx(1.0)  # first vector stands


def test_add_idempotence_is_per_matter(tmp_path):
    store = VectorStore(tmp_path / "v.db", dim=2)
    store.add("M-1", ["shared text"], [[1.0, 0.0]], model="m", provider="p")
    store.add("M-2", ["shared text"], [[0.0, 1.0]], model="m", provider="p")
    assert store.count("M-1") == 1 and store.count("M-2") == 1
    assert store.search("M-2", [0.0, 1.0], k=5)[0].score == pytest.approx(1.0)


def test_delete_specific_texts_and_purge_whole_matter(tmp_path):
    # D of the 2026-10-14 CRUD completion: targeted deletes and whole-matter purge,
    # index rows always going with their metadata.
    store = VectorStore(tmp_path / "v.db", dim=2)
    store.add("M-1", ["alpha", "beta", "gamma"], [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
              model="m", provider="p")
    store.add("M-2", ["alpha"], [[0.9, 0.1]], model="m", provider="p")
    assert store.delete("M-1", texts=["alpha"]) == 1
    assert store.count("M-1") == 2
    assert all(h.text != "alpha" for h in store.search("M-1", [1.0, 0.0], k=10))
    assert store.count("M-2") == 1                        # other matter untouched
    assert store.delete("M-1") == 2                       # purge
    assert store.count("M-1") == 0
    assert store.search("M-1", [1.0, 0.0], k=10) == []


def test_list_texts_rows_are_readable(tmp_path):
    store = VectorStore(tmp_path / "v.db", dim=2)
    store.add("M-1", ["one text", "two text"], [[1.0, 0.0], [0.0, 1.0]],
              model="bge-m3", provider="ollama-embed")
    rows = store.list_texts("M-1")
    assert [r["text"] for r in rows] == ["one text", "two text"]
    assert rows[0]["model"] == "bge-m3" and rows[0]["seq"] == 0
    assert store.list_texts("M-none") == []
