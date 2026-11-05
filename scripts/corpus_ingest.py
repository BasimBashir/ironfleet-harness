"""Shim for the M3 substrate relocation: the real module is harness.corpus_ingest.

Run as a CLI:
  .venv/Scripts/python.exe scripts/corpus_ingest.py --matter m-acme --sources dir/ ... --out-report r.json
"""
from __future__ import annotations

from harness.corpus_ingest import *            # noqa: F401,F403 — public surface
from harness.corpus_ingest import (           # noqa: F401 — names star-import skips
    REPO, BATCH, MIN_WORDS, extract_text, ingest_dir, build_live_stack, make_embed_fn, main)

if __name__ == "__main__":
    main()
