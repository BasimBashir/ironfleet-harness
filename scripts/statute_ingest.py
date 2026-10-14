"""R1 statute ingestion — now a thin shell over the GENERAL core (harness.ingest_generic).

The user's direction 2026-10-14: ingestion must be future-proof — a new corpus set is
manifest ROWS, never code. parse_provisions / licence_check / ingest_statutes stay
importable here (re-exports + a wrapper) so existing callers and tests are unchanged;
the general front door is scripts/corpus_ingest.py --sources-spec (any mix of judgment
PDFs, statute MDs, plain text; kind auto-detects; statute rows are licence-gated).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from harness.ingest_generic import (  # noqa: F401 — re-exported for existing callers
    detect_kind, licence_check, load_spec, parse_provisions)

REPO = Path(__file__).resolve().parents[1]


def ingest_statutes(matter_ref: str, manifest: list[dict], store, embed_fn,
                    min_words: int = 200) -> dict:
    """Compatibility wrapper: statute manifest rows through the general core."""
    from harness.ingest_generic import ingest_any
    rows = [dict(r, kind="statute", path=r.get("path") or r.get("file"))
            for r in manifest]
    return ingest_any(matter_ref, rows, store, embed_fn, min_words=min_words)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/corpus/statute_sources.yaml", type=Path)
    ap.add_argument("--matter", required=True)
    ap.add_argument("--out-report", type=Path, default=None)
    args = ap.parse_args()
    from scripts.corpus_ingest import build_live_stack, make_embed_fn
    gate, store = build_live_stack(Path("statute_ingest_trace.sqlite3"), args.matter)
    report = ingest_statutes(args.matter, load_spec(REPO / args.manifest), store,
                             make_embed_fn(gate, args.matter))
    print(f"[ingest] provisions={report['provisions']} ingested={len(report['ingested'])} "
          f"refused={len(report['refused'])} chunks/s={report['chunks_per_s']}", flush=True)
    for r in report["refused"]:
        print(f"  [refused] {r}", flush=True)
    if args.out_report:
        args.out_report.parent.mkdir(parents=True, exist_ok=True)
        args.out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
