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


def build_live_stack(trace_name: str, matter: str):
    """Shared live stack for the ingestion CLIs: the real gate (LOCAL_ONLY embeds) and
    the corpus store at the resolved store root."""
    from scripts.stand_up_opencode import ROUTING, build_gate
    from harness.paths import resolve_store_root
    from harness.vectors import VectorStore
    print("[gate] building (the embed leg is LOCAL_ONLY bge-m3)...", flush=True)
    gate, _rt, _al = build_gate(Path(trace_name), ROUTING)
    root, _source = resolve_store_root()
    store = CorpusStore(root / "corpus.sqlite3",
                        vectors=VectorStore(root / "vectors.sqlite3"))
    return gate, store


def make_embed_fn(gate, matter: str):
    def embed_fn(texts):
        res = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=matter, texts=texts)))
        return res.vectors
    return embed_fn


def main() -> None:
    """THE front door: a new corpus set is a sources-spec YAML (or plain paths), never code.

      python scripts/corpus_ingest.py --matter m-acme           --sources-spec data/corpus/sources.yaml --out-report r.json
      python scripts/corpus_ingest.py --matter m-acme --sources dir/ file.pdf ...   # prose-only legacy
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--matter", required=True, help="colon-free matter ref")
    ap.add_argument("--sources", nargs="*", type=Path)
    ap.add_argument("--sources-spec", type=Path, default=REPO / "data/corpus/sources.yaml")
    ap.add_argument("--out-report", type=Path, required=True)
    args = ap.parse_args()

    gate, store = build_live_stack("corpus_ingest_trace.sqlite3", args.matter)
    embed_fn = make_embed_fn(gate, args.matter)

    if args.sources:                                   # legacy prose-only path
        report = ingest_dir(args.matter, args.sources, store, embed_fn)
    else:                                              # THE general path (D7)
        from harness.ingest_generic import ingest_any, load_spec
        report = ingest_any(args.matter, load_spec(args.sources_spec), store, embed_fn)
    print(f"[ingest] {len(report['ingested'])} ingested, {len(report['skipped'])} skipped, "
          f"{len(report['skipped_by_resume'])} resumed, {len(report.get('refused', []))} refused, "
          f"{report['chunks']} chunks @ {report['chunks_per_s']} chunks/s", flush=True)
    for s in report["skipped"][:12]:
        print(f"  [skipped] {s}", flush=True)
    for r in report.get("refused", [])[:12]:
        print(f"  [refused] {r}", flush=True)
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[done] report -> {args.out_report}")


if __name__ == "__main__":
    main()
