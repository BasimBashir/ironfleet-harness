"""R1 plan Task 8 (D7): the corpus ingest command.

parse (pypdf for PDFs; utf-8 text) -> recorded-skip for scanned/no-text sources ->
split (harness.corpus) -> embed in 64-batches through the INJECTED embed_fn (the real
gate in live mode; a fake in tests) -> CorpusStore + VectorStore. Resume by sha256
(an interrupted hours-long run must not re-embed). Throughput is a logged first-class
output (the cognee lesson), not a benchmark-only number.

Usage (live, real gate):
  python scripts/corpus_ingest.py --matter m-acme --sources dir/ file.pdf --out-report r.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from harness.corpus import CorpusStore, DocRecord, chunk_text  # noqa: E402
from harness.gate import EmbeddingRequest  # noqa: E402
from harness.vectors import VectorStore  # noqa: E402

BATCH = 64                       # EmbeddingRequest.max_texts ceiling
MIN_WORDS = 200                  # below this a source is recorded-and-skipped (scanned)


def extract_text(source: Path) -> str:
    if source.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(source))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    return source.read_text(encoding="utf-8")


def ingest_dir(matter_ref: str, sources: list[Path], store: CorpusStore,
               embed_fn, model: str = "bge-m3:567m", provider: str = "ollama-embed",
               min_words: int = MIN_WORDS) -> dict:
    """The unit-testable core: no gate import, no network. embed_fn(texts)->vectors is
    injected by the caller (asyncio.run(gate.embed...) in live mode)."""
    report: dict = {"date": date.today().isoformat(), "matter": matter_ref,
                    "ingested": [], "skipped": [], "skipped_by_resume": [],
                    "chunks": 0, "tokens_in": 0}
    files: list[Path] = []
    for s in sources:
        files.extend(sorted(s.glob("**/*.pdf")) if s.is_dir() else [s])
    t0 = time.perf_counter()
    for src in files:
        try:
            text = extract_text(src)
        except Exception as ex:                        # noqa: BLE001 — recorded, keep going
            report["skipped"].append(f"{src.name}: parse error {ex}")
            continue
        if len(text.split()) < min_words:
            # D7: recorded-and-skipped, never silently embedded empty (the scanned-PDF
            # contract; the R1-MAXRAG bench learned this one the hard way)
            report["skipped"].append(f"{src.name}: {len(text.split())} words (<{min_words}, scanned?)")
            continue
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if store.has_doc(matter_ref, sha):
            report["skipped_by_resume"].append(src.name)
            continue
        doc = DocRecord(doc_id=f"doc-{sha[:12]}", text=text, source_name=src.name)
        texts = chunk_text(doc.doc_id, text)
        vectors: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            res = embed_fn(texts[i:i + BATCH])
            vectors.extend(res)
        store.ingest(matter_ref, doc, vectors=vectors, model=model, provider=provider)
        report["ingested"].append(src.name)
        report["chunks"] += len(texts)
    wall = time.perf_counter() - t0
    report["wall_s"] = round(wall, 1)
    report["chunks_per_s"] = round(report["chunks"] / wall, 1) if wall else 0.0
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matter", required=True, help="colon-free matter ref")
    ap.add_argument("--sources", nargs="+", required=True, type=Path)
    ap.add_argument("--out-report", type=Path, required=True)
    args = ap.parse_args()

    from scripts.stand_up_opencode import ROUTING, build_gate
    print("[gate] building (real probe; the embed leg is LOCAL_ONLY bge-m3)...", flush=True)
    gate, _rt, _al = build_gate(Path("corpus_ingest_trace.sqlite3"), ROUTING)

    def embed_fn(texts: list[str]) -> list[list[float]]:
        res = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=args.matter, texts=texts)))
        return res.vectors

    from harness.paths import resolve_store_root
    root = Path(resolve_store_root())
    store = CorpusStore(root / "corpus.sqlite3",
                        vectors=VectorStore(root / "vectors.sqlite3"))
    report = ingest_dir(args.matter, args.sources, store, embed_fn)
    print(f"[ingest] {len(report['ingested'])} ingested, {len(report['skipped'])} skipped, "
          f"{len(report['skipped_by_resume'])} resumed, "
          f"{report['chunks']} chunks @ {report['chunks_per_s']} chunks/s", flush=True)
    for s in report["skipped"]:
        print(f"  [skipped] {s}", flush=True)
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[done] report -> {args.out_report}")


if __name__ == "__main__":
    main()
