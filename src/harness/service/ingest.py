# src/harness/service/ingest.py — /ingest as a plain function (M3).
"""Corpus ingest into a session's matter: sha256 resume, batches of 64,
LOCAL_ONLY embeddings — the substrate. Moved from tui.py's _ingest; the TUI
keeps asyncio.to_thread and echoes the report lines."""
from __future__ import annotations

from pathlib import Path


def ingest_source(matter_ref: str, source: str,
                  trace_name: str = "corpus_ingest_trace.sqlite3") -> dict:
    """Ingest one source path into the matter; returns the ingest_dir report."""
    from harness.corpus_ingest import build_live_stack, ingest_dir, make_embed_fn
    gate, store = build_live_stack(trace_name, matter_ref)
    return ingest_dir(matter_ref, [Path(source)], store, make_embed_fn(gate, matter_ref))
