# tests/test_corpus_ingest.py — R1 plan Task 8 (D7): offline core, injected embed_fn
from harness.corpus import CorpusStore
from scripts.corpus_ingest import ingest_dir


def _store(tmp_path):
    from harness.vectors import VectorStore
    return CorpusStore(tmp_path / "corpus.sqlite3",
                       vectors=VectorStore(tmp_path / "vectors.sqlite3", dim=2))


def test_ingest_skips_scanned_and_reports(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("HEADING\n\n" + ("word " * 400), encoding="utf-8")
    scanned = tmp_path / "scanned.txt"
    scanned.write_text("barely anything", encoding="utf-8")
    report = ingest_dir("m-r1", [real, scanned], _store(tmp_path),
                        embed_fn=lambda texts: [[0.1, 0.9] for _ in texts])
    assert report["ingested"] == ["real.txt"]
    assert len(report["skipped"]) == 1 and "scanned" in report["skipped"][0]
    assert report["chunks"] > 0 and "chunks_per_s" in report


def test_ingest_resume_skips_already_stored(tmp_path):
    src = tmp_path / "doc.txt"
    src.write_text("HEADING\n\n" + ("body text here " * 100), encoding="utf-8")
    store = _store(tmp_path)
    fn = lambda texts: [[0.5, 0.5] for _ in texts]  # noqa: E731
    first = ingest_dir("m-r1", [src], store, embed_fn=fn)
    second = ingest_dir("m-r1", [src], store, embed_fn=fn)
    assert first["ingested"] == ["doc.txt"]
    assert second["ingested"] == [] and second["skipped_by_resume"] == ["doc.txt"]


def test_ingest_never_reembeds_a_different_file_with_the_same_text(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    for p in (a, b):
        p.write_text("HEADING\n\n" + ("identical body " * 100), encoding="utf-8")
    calls = []

    def counting(texts):
        calls.append(len(texts))
        return [[0.5, 0.5] for _ in texts]
    report = ingest_dir("m-r1", [a, b], _store(tmp_path), embed_fn=counting)
    assert report["ingested"] == ["a.txt"]          # same sha -> the second is a resume
    assert report["skipped_by_resume"] == ["b.txt"]
    assert sum(calls) == report["chunks"]           # embedded exactly once, 1:1 with chunks
