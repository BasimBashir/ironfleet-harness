"""R1 plan Task 11 (D7 extension): the statute-provision ingester.

The measured 39%-of-needles STATUTE-ABSENT class exists because the corpus held only
judgments. This ingester adds NZ legislation at PROVISION level — one chunk per section
(the COLIEE/RefWalk corpus shape) — from LOCAL text files the operator fetched from the
official source. It deliberately does NOT fetch: legislation.govt.nz serves this box a
bot challenge (202), and circumventing a bot wall is not the harness's job. The
operator's browser fetches; the ingester verifies provenance and licence, then ingests.

Licence gate (fail-closed): a statute source is ingested ONLY when the manifest row
carries `licence:` (e.g. "CC BY 4.0") + `source_url:` + `retrieved:`. legislation.govt.nz
content is Crown copyright / CC BY 4.0 — the operator records it after checking the
page footer; a manifest without the row is a refusal, never an assumption.

Usage:
  python scripts/statute_ingest.py --manifest data/corpus/statute_sources.yaml \
      --matter m-acme [--out-report r.json]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
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

BATCH = 64

# NZ statute structure: a section heading is a line at column 0 carrying just the
# section number ("297") or number + title ("16 Meaning of security interest") —
# both shapes appear in PCO exports.
_SECTION = re.compile(r"^(?P<num>\d{1,3}[A-Z]{0,2})\s*(?P<title>[A-Z][^|\n]{0,120})?\s*$")


def parse_provisions(act_name: str, text: str) -> list[DocRecord]:
    """One DocRecord per section: heading = 's <num> <title>', body = section text.
    Provision-level retrieval is the measured fix for statute pins — a needle like
    'Companies Act 1993, s 297' must hit a chunk that IS that section. The header uses
    the judgment surface form ('s 297') so the pin and the provision text agree."""
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []
    cur_num, cur_body = "", []          # preamble material before the first section
    for ln in lines:
        m = _SECTION.match(ln)
        if m:
            if cur_num:
                sections.append((cur_num, cur_body))
            cur_num = f"{m['num']} {m['title'] or ''}".strip()
            cur_body = []
        elif cur_num:
            cur_body.append(ln)
        else:
            cur_body.append(ln)
    if cur_num:
        sections.append((cur_num, cur_body))
    out: list[DocRecord] = []
    for num, body in sections:
        body_text = "\n".join(body).strip()
        if len(body_text.split()) < 8:                   # "(Repealed)" stubs, page furniture
            continue
        text_full = f"{act_name}, s {num}\n\n{body_text}"   # the needle surface form, verbatim
        sha = hashlib.sha256(text_full.encode("utf-8")).hexdigest()[:12]
        out.append(DocRecord(doc_id=f"statute-{sha}", text=text_full,
                             source_name=f"{act_name}, s {num}"))
    return out


def load_manifest(path: Path) -> list[dict]:
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return doc.get("statutes", []) if isinstance(doc, dict) else []


def licence_check(row: dict) -> str | None:
    """The fail-closed gate: returns a refusal reason, or None when the row proves
    licence + provenance. A missing field is a refusal, never an assumption."""
    for field in ("file", "act", "licence", "source_url", "retrieved"):
        if not row.get(field):
            return f"manifest row missing {field!r}"
    if not Path(row["file"]).exists():
        return f"source file {row['file']!r} not found"
    return None


def ingest_statutes(matter_ref: str, manifest: list[dict], store: CorpusStore,
                    embed_fn) -> dict:
    report: dict = {"date": date.today().isoformat(), "matter": matter_ref,
                    "ingested": [], "provisions": 0, "refused": []}
    t0 = time.perf_counter()
    for row in manifest:
        reason = licence_check(row)
        if reason:
            report["refused"].append(f"{row.get('act', row.get('file', '?'))}: {reason}")
            continue
        text = Path(row["file"]).read_text(encoding="utf-8")
        provisions = parse_provisions(row["act"], text)
        for prov in provisions:
            vectors: list[list[float]] = []
            texts = chunk_text(prov.doc_id, prov.text)
            for i in range(0, len(texts), BATCH):
                vectors.extend(embed_fn(texts[i:i + BATCH]))
            store.ingest(matter_ref, prov, vectors=vectors,
                         model="bge-m3:567m", provider="ollama-embed")
            report["provisions"] += 1
        report["ingested"].append(row["act"])
    wall = time.perf_counter() - t0
    report["wall_s"] = round(wall, 1)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/corpus/statute_sources.yaml", type=Path)
    ap.add_argument("--matter", required=True)
    ap.add_argument("--out-report", type=Path, default=None)
    args = ap.parse_args()
    from scripts.stand_up_opencode import ROUTING, build_gate
    print("[gate] building (the embed leg is LOCAL_ONLY bge-m3)...", flush=True)
    gate, _rt, _al = build_gate(Path("statute_ingest_trace.sqlite3"), ROUTING)

    def embed_fn(texts: list[str]) -> list[list[float]]:
        res = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=args.matter, texts=texts)))
        return res.vectors

    from harness.paths import resolve_store_root
    root = Path(resolve_store_root())
    store = CorpusStore(root / "corpus.sqlite3",
                        vectors=VectorStore(root / "vectors.sqlite3"))
    report = ingest_statutes(args.matter, load_manifest(REPO / args.manifest), store, embed_fn)
    print(f"[ingest] {len(report['ingested'])} acts, {report['provisions']} provisions, "
          f"{len(report['refused'])} refused", flush=True)
    for r in report["refused"]:
        print(f"  [refused] {r}", flush=True)
    if args.out_report:
        args.out_report.parent.mkdir(parents=True, exist_ok=True)
        args.out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
