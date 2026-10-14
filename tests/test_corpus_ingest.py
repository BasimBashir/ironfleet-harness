# tests/test_corpus_ingest.py — R1 plan Task 8 (D7): offline core, injected embed_fn
import pytest

from harness.corpus import CorpusStore
from harness.ingest_generic import ingest_any
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


def test_extract_text_pdf_parse_watchdog_records_skip(tmp_path):
    """A source whose parse hangs must be killable, not a stuck ingest (observed live
    2026-10-14: one judgment PDF pinned a core for 10+ minutes with zero output)."""
    from pypdf import PdfWriter
    from scripts.corpus_ingest import extract_text
    pdf = tmp_path / "tiny.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with open(pdf, "wb") as f:
        w.write(f)
    assert extract_text(pdf, timeout=120) == ""        # blank page parses, yields no text
    with pytest.raises(TimeoutError):
        # an impossible deadline: Windows spawn + pypdf import always exceeds 0.2 s
        extract_text(pdf, timeout=0.2)


def test_statute_resume_is_doc_granularity(tmp_path):
    """One statute FILE fans out to per-provision DOCS; resume must key on the doc
    sha (what the store holds) or every re-run re-embeds all provisions — the measured
    root cause of the 2.6x duplicate embeddings (2026-10-14)."""
    statute = tmp_path / "Test Act 2020.md"
    body = "\n".join(
        f"{n} Provision title number {n}\n" + " ".join(f"word{i}" for i in range(40))
        for n in (5, 7))
    statute.write_text(body, encoding="utf-8")
    store = _store(tmp_path)
    calls = []
    spec = [{"path": str(statute), "kind": "statute", "act": "Test Act 2020",
             "licence": "CC BY 4.0 (test)", "source_url": "https://test/",
             "retrieved": "test fixture"}]
    r1 = ingest_any("m-t", spec, store, embed_fn=lambda t: calls.append(len(t)) or [[1.0, 0.0]],
                    min_words=50)
    n_docs = r1["provisions"]
    assert n_docs >= 2
    calls.clear()
    r2 = ingest_any("m-t", spec, store, embed_fn=lambda t: calls.append(len(t)) or [[1.0, 0.0]],
                    min_words=50)
    assert r2["resumed_docs"] == n_docs
    assert not calls                                   # not ONE chunk re-embedded
