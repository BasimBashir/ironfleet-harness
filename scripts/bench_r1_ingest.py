"""R1 research gate — ingest-throughput bench (NEXT_STEPS R1; research deliverable, not product code).

Measures, on THIS box, in one run:
  A. Corpus  — N synthetic legal-shaped docs (seeded, deterministic) plus the 31 real
               golden-corpus PDFs (pypdf text layer; scanned docs surface as near-empty).
  B. Ingest  — the thin assembly the research gate names as candidate B:
               structure-aware split (headings + paragraphs, section provenance kept)
               -> SQLite FTS5/BM25 (lexical) -> gate.embed() bge-m3 (the EXISTING
               LOCAL_ONLY path, real probe/routing/trace) -> VectorStore.
  C. Query   — against the REAL 31-doc store (matter m-r1-real): the 30 golden-case
               prompts, lexical vs hybrid (RRF), source-document recall@5. This is the
               no-reranker baseline the one-page verdict argues from.

Usage:
  python scripts/bench_r1_ingest.py [--docs 1000] [--out data/eval/R1-RESEARCH-<date>]
                                    [--quick] [--selfcheck] [--skip-synthetic] [--skip-real]

--quick caps synthetic docs at 40 for a smoke pass. --selfcheck: splitter asserts only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))   # scripts.* imports (stand_up_opencode.py:33-38 lesson)

from harness.gate import EmbeddingRequest  # noqa: E402
from harness.vectors import VectorStore  # noqa: E402
from scripts.stand_up_opencode import ROUTING, build_gate  # noqa: E402

MATTER_SYN = "m-r1-bench"            # colon-free: Windows forbids ':' in registry dirs
MATTER_REAL = "m-r1-real"
BATCH = 64                           # EmbeddingRequest.max_texts ceiling
CHUNK_WORDS = 210                    # target chunk size in words (1-3 paragraphs)
EMBED_MODEL, EMBED_PROVIDER = "bge-m3:567m", "ollama-embed"

# --------------------------------------------------------------------------- split

_HEADING = re.compile(r"^(?:[IVXLC]+|\d+)[.\)]?\s+[A-Z].*[A-Z]{3}")   # "III. Title ..." / "12. Foo Bar"
_ALLCAPS = re.compile(r"^[^a-z]{6,}$")                                # "TITLE TO BULLION"


@dataclass
class Chunk:
    doc_id: str
    heading: str
    text: str


def split_structure(doc_id: str, text: str, target_words: int = CHUNK_WORDS) -> list[Chunk]:
    """Paragraph- AND heading-aware split; each chunk carries its section heading.

    Legal structure honoured: ALL-CAPS headings, roman/numbered headings ("III. Title"),
    and blank-line paragraphs. A paragraph is never split mid-way unless it alone exceeds
    2x target (hard-split then — judgments have some very long paragraphs).
    """
    chunks: list[Chunk] = []
    heading = ""
    para_buf: list[str] = []
    buf_words = 0

    def flush() -> None:
        nonlocal para_buf, buf_words
        body = "\n\n".join(para_buf).strip()
        if body:
            chunks.append(Chunk(doc_id, heading, body))
        para_buf, buf_words = [], 0

    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        first_line = para.splitlines()[0].strip()
        is_heading = (len(para) <= 120
                      and (_ALLCAPS.match(first_line) or _HEADING.match(first_line)))
        if is_heading:
            flush()
            heading = first_line
            continue
        words = len(para.split())
        if words > target_words * 2:                      # hard-split an outsized paragraph
            flush()
            cur: list[str] = []
            cur_w = 0
            for s in para.split(". "):
                cur.append(s)
                cur_w += len(s.split())
                if cur_w >= target_words:
                    chunks.append(Chunk(doc_id, heading, ". ".join(cur).strip()))
                    cur, cur_w = [], 0
            if cur:
                chunks.append(Chunk(doc_id, heading, ". ".join(cur).strip()))
            continue
        if buf_words and buf_words + words > target_words:
            flush()
        para_buf.append(para)
        buf_words += words
    flush()
    return chunks


def chunk_text(doc_id: str, text: str) -> list[str]:
    """The embedded form: heading-prefixed chunk bodies."""
    return [f"{c.heading}\n{c.text}" if c.heading else c.text
            for c in split_structure(doc_id, text)]


def selfcheck() -> None:
    doc = ("GOLDCORP EXCHANGE LTD V LIGGETT\n\nIntro para one.\n\n"
           "III. TITLE TO BULLION\n\nPara under heading one, with [44] pin.\n\n"
           "Para two under same heading.\n\nIV. CONCLUSION\n\nFinal para.\n\n"
           + ("Long paragraph. " * 200))
    cs = split_structure("d1", doc)
    heads = [c.heading for c in cs]
    assert heads[0] == "GOLDCORP EXCHANGE LTD V LIGGETT", heads
    assert "III. TITLE TO BULLION" in heads and "IV. CONCLUSION" in heads, heads
    assert all(c.text for c in cs), "empty chunk"
    assert all(len(c.text.split()) <= CHUNK_WORDS * 2 + 20 for c in cs), "hard split failed"
    assert split_structure("d2", "") == [], "empty doc must yield zero chunks"
    one = split_structure("d3", "IV. SOLE HEADING\n\nOnly paragraph here.")
    assert len(one) == 1 and one[0].heading == "IV. SOLE HEADING"
    print("selfcheck OK")


# ------------------------------------------------------------------- synthetic corpus

_SENTENCES = [
    "The plaintiff advanced ${n} under an unallocated storage scheme that promised delivery "
    "of metal of the contracted weight but set nothing aside for any buyer.",
    "Section {s} of the {act} applies only where property has passed to the debtor.",
    "As Atkin LJ explained in In re Wait [1927] 1 Ch 606, unascertained goods pass no "
    "property until appropriation is unconditional.",
    "The liquidators conceded that the purchase price was traceable into the account "
    "maintained with the second respondent bank.",
    "His Honour found that the security interest attached on {day} {month} {year} and "
    "that perfection by registration followed within the statutory period.",
    "Counsel for the appellant submitted that the trial Judge erred in preferring the "
    "evidence of the expert called by the respondent over the contemporaneous documents.",
    "The floating charge crystallised on the appointment of receivers under clause {s}.",
    "In Mainzeal Property and Construction Ltd (in liq) v Yan [2019] NZHC 255 the Court "
    "restated the bewildered-creditor test for s 297 reliance.",
    "There was never any bailment, and no identifiable property to which any trust could attach.",
    "The Personal Property Securities Act 1999 governs priority disputes between competing "
    "security interests in personal property, including after-acquired property.",
    "Accordingly the appeal is dismissed and the respondent is entitled to costs on a "
    "2B basis, with certified second counsel.",
    "The question is whether the transaction is voidable under s 292 as a gift, or under "
    "s 296 as a transaction at undervalue within the relevant period.",
    "A purchase money security interest has super priority under s 79 of the Act where "
    "the collateral is identifiable and the registration requirements are met.",
    "The judge held that the payments were not without prejudice communications and were "
    "therefore admissible on the winding-up application.",
    "Verification of the solvency statement under s 222 requires the directors to form "
    "an opinion on a balance of probabilities, not a guarantee.",
]
_ACTS = ["Sale of Goods Act 1908", "Companies Act 1993", "Personal Property Securities Act 1999"]
_MONTHS = ["January", "March", "June", "September", "November"]
_SECTIONS = ["INTRODUCTION", "BACKGROUND", "STATUTORY FRAMEWORK", "SUBMISSIONS FOR THE PLAINTIFF",
             "THE JUDGE'S FINDINGS", "ISSUE ON APPEAL", "OUR APPROACH", "RESULT",
             "TITLE TO BULLION", "THE FLOATING CHARGE", "PRIORITY COMPETITION", "COSTS"]


def make_docs(n: int, rng: random.Random, words_target: int) -> list[tuple[str, str]]:
    docs = []
    for i in range(n):
        year = rng.randint(1994, 2026)
        court = rng.choice(["NZSC", "NZCA", "NZHC", "UKPC"])
        ref = f"[{year}] {court} {rng.randint(1, 999)}"
        parts = [f"{'A' * rng.randint(4, 9)} {'A' * rng.randint(4, 9)} Ltd (in liq) v "
                 f"{'B' * rng.randint(4, 9)} {'B' * rng.randint(4, 9)} Holdings {ref}",
                 f"HEARD at Auckland on {rng.randint(1, 28)} {rng.choice(_MONTHS)} {year}",
                 f"JUDGMENT of Justice {'C' * rng.randint(4, 9)}"]
        while sum(len(p.split()) for p in parts) < words_target:
            parts.append(rng.choice(_SECTIONS))
            for _ in range(rng.randint(2, 6)):
                s = rng.choice(_SENTENCES)
                s = (s.replace("{n}", f"{rng.randint(20, 900) * 1000:,}")
                      .replace("{s}", str(rng.randint(9, 297)))
                      .replace("{act}", rng.choice(_ACTS))
                      .replace("{day}", str(rng.randint(1, 28)))
                      .replace("{month}", rng.choice(_MONTHS))
                      .replace("{year}", str(year)))
                parts.append(s)
        docs.append((f"syn-{i:04d}", "\n\n".join(parts)))
    return docs


# ------------------------------------------------------------------ real corpus (PDFs)

def load_real_pdf_texts(corpus_dir: Path) -> list[tuple[str, str]]:
    from pypdf import PdfReader
    docs = []
    for pdf in sorted(corpus_dir.glob("*.pdf")):
        try:
            reader = PdfReader(str(pdf))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as ex:                            # noqa: BLE001 — record, keep going
            text = ""
            print(f"  [parse error] {pdf.name}: {ex}")
        docs.append((f"real-{pdf.stem}", text))
    return docs


# ------------------------------------------------------------------- lexical + hybrid

def bm25_search(con: sqlite3.Connection, table: str, query: str, k: int = 20,
                doc_filter: str = "") -> list[str]:
    """BM25 ranking; OR of the alphanumeric tokens (FTS5 syntax chokes on legal punctuation).
    doc_filter is a SQL fragment on doc_id, e.g. " AND doc_id LIKE 'real-%'"."""
    terms = [t for t in re.findall(r"[A-Za-z0-9]{3,}", query)][:24]
    if not terms:
        return []
    q = " OR ".join(f'"{t}"' for t in terms)
    try:
        rows = con.execute(
            f"SELECT doc_id FROM {table} WHERE {table} MATCH ?{doc_filter} "
            f"ORDER BY bm25({table}) LIMIT ?", (q, k)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [doc_id for (doc_id,) in rows]


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [d for d, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


# ------------------------------------------------------------------------------- main

async def run(args: argparse.Namespace, gate) -> dict:
    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict = {"date": date.today().isoformat(), "box": "windows-dev",
                     "chunk_words": CHUNK_WORDS, "batch": BATCH}

    # ---------- corpora
    real_docs: list[tuple[str, str]] = []
    if not args.skip_real:
        t0 = time.perf_counter()
        real_docs = load_real_pdf_texts(REPO / "data/golden_cases/sources/Set_2")
        parse_s = time.perf_counter() - t0
        empty = [d for d, t in real_docs if len(t.split()) < 200]
        results["real_parse"] = {
            "docs": len(real_docs), "wall_s": round(parse_s, 2),
            "docs_per_s": round(len(real_docs) / parse_s, 2),
            "mean_words_per_doc": round(sum(len(t.split()) for _, t in real_docs)
                                        / max(1, len(real_docs))),
            "near_empty_scanned": empty,
        }
        print(f"[real] {len(real_docs)} PDFs parsed in {parse_s:.1f}s "
              f"({len(empty)} near-empty/scanned)")

    syn_docs: list[tuple[str, str]] = []
    if not args.skip_synthetic:
        rng = random.Random(20261013)
        t0 = time.perf_counter()
        # synthetic docs sized to the real corpus's mean words/doc — the honest doc shape
        target = results.get("real_parse", {}).get("mean_words_per_doc", 2500)
        syn_docs = make_docs(args.docs, rng, target)
        results["synthetic_make"] = {"docs": len(syn_docs),
                                     "wall_s": round(time.perf_counter() - t0, 3)}
        print(f"[syn]  {len(syn_docs)} synthetic docs generated")

    # ---------- ingest: split -> fts -> embed -> vectorstore (the thin assembly)
    for p in ("vectors.sqlite3", "lexical.sqlite3"):
        if (out_dir / p).exists():
            (out_dir / p).unlink()
    store = VectorStore(out_dir / "vectors.sqlite3")
    con = sqlite3.connect(out_dir / "lexical.sqlite3")
    con.execute("CREATE VIRTUAL TABLE fts USING fts5(doc_id, heading, body)")

    all_docs = syn_docs + real_docs
    t_split = 0.0
    chunks_by_doc: dict[str, list] = {}
    for doc_id, text in all_docs:
        t0s = time.perf_counter()
        chunks_by_doc[doc_id] = split_structure(doc_id, text)
        t_split += time.perf_counter() - t0s
    all_chunks = [c for cs in chunks_by_doc.values() for c in cs]
    t0 = time.perf_counter()
    con.executemany("INSERT INTO fts(doc_id, heading, body) VALUES(?,?,?)",
                    [(c.doc_id, c.heading, c.text) for c in all_chunks])
    con.commit()
    t_lex = time.perf_counter() - t0
    results["split"] = {"chunks": len(all_chunks), "wall_s": round(t_split, 2),
                        "chunks_per_s": round(len(all_chunks) / max(t_split, 1e-9))}
    results["lexical_index"] = {"chunks": len(all_chunks), "wall_s": round(t_lex, 2),
                                "chunks_per_s": round(len(all_chunks) / max(t_lex, 1e-9))}
    print(f"[ingest] {len(all_chunks)} chunks: split {t_split:.1f}s, fts {t_lex:.1f}s")

    def matter_of(doc_id: str) -> str:
        return MATTER_REAL if doc_id.startswith("real-") else MATTER_SYN

    # per-matter chunk lists: a 64-batch must never straddle the matter boundary
    syn_chunks = [c for c in all_chunks if matter_of(c.doc_id) == MATTER_SYN]
    real_chunks = [c for c in all_chunks if matter_of(c.doc_id) == MATTER_REAL]

    t_start = time.perf_counter()

    async def embed_all(chunks: list, total: int, offset: int) -> tuple[float, int, int]:
        tokens = 0
        dim = 0
        t0 = time.perf_counter()
        matter = matter_of(chunks[0].doc_id)
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i:i + BATCH]
            texts = [f"{c.heading}\n{c.text}" if c.heading else c.text for c in batch]
            res = None
            for attempt in range(3):        # transient Ollama hiccups must not kill a long run
                try:
                    res = await gate.embed(EmbeddingRequest(matter_ref=matter, texts=texts))
                    break
                except Exception as ex:     # noqa: BLE001
                    if attempt == 2:
                        raise
                    print(f"\n  [embed retry {attempt + 1}] {ex}", flush=True)
                    await asyncio.sleep(5 * (attempt + 1))
            store.add(matter, texts, res.vectors, res.model, res.provider)
            tokens += sum(res.usage.values())
            dim = len(res.vectors[0])
            done = offset + min(i + BATCH, len(chunks))
            rate = done / (time.perf_counter() - t_start)
            print(f"  [embed] {done}/{total} chunks ({rate:.1f} chunks/s)", end="\r", flush=True)
        return time.perf_counter() - t0, tokens, dim

    t_emb = time.perf_counter()
    embed_wall = 0.0
    tokens_in = 0
    dim = 0
    for chunks, offset in ((syn_chunks, 0), (real_chunks, len(syn_chunks))):
        dt, toks, d = await embed_all(chunks, len(all_chunks), offset)
        embed_wall += dt
        tokens_in += toks
        dim = dim or d
    t_emb = embed_wall
    results["embed_index"] = {
        "chunks": len(all_chunks), "wall_s": round(t_emb, 1),
        "chunks_per_s": round(len(all_chunks) / t_emb, 1),
        "docs_per_s": round(len(all_docs) / t_emb, 2),
        "tokens_in": tokens_in, "vector_dims": dim,
        "model": EMBED_MODEL, "provider": EMBED_PROVIDER,
        "via": "gate.embed (LOCAL_ONLY path, real probe/routing/trace)",
    }
    print(f"\n[ingest] embed+store {t_emb:.1f}s -> {len(all_chunks) / t_emb:.1f} chunks/s "
          f"({len(all_docs) / t_emb:.2f} docs/s)")

    # query leg on the REAL corpus only (quality signal; synthetic corpus is machinery-only)
    if real_docs:
        results["query_real"] = await query_leg(gate, store, con, real_docs)

    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"[done] results -> {out_dir / 'results.json'}")
    return results


async def query_leg(gate, store: VectorStore, con: sqlite3.Connection,
                    real_docs: list[tuple[str, str]]) -> dict:
    """Golden-case queries against the real corpus; lexical vs hybrid-RRF recall@5."""
    import yaml

    real_ids = {d for d, _ in real_docs}
    real_chunks: list[tuple[str, str, str]] = []          # (doc_id, heading, body)
    for doc_id, text in real_docs:
        for c in split_structure(doc_id, text):
            real_chunks.append((doc_id, c.heading, c.text))
    # 2026-10-13 correction: VectorStore.seq is BATCH-LOCAL (restarts every 64-add) —
    # mapping hits by seq to a global list is garbage; map by the stored text instead.
    idx_by_text = {f"{h}\n{b}" if h else b: i for i, (_, h, b) in enumerate(real_chunks)}
    doc_of = [rc[0] for rc in real_chunks]

    def source_of(case_id: str) -> str | None:
        suffix = case_id.split("-", 3)[-1]                 # e.g. "ppsa-001-goldcorp"
        tokens = [t for t in re.split(r"[-\d]+", suffix) if t]
        best, best_n = None, 0
        for d in real_ids:
            stem = d.lower()
            n = sum(1 for t in tokens if t in stem)
            if n > best_n:
                best, best_n = d, n
        return best

    cases = [yaml.safe_load(p.read_text(encoding="utf-8"))
             for p in sorted((REPO / "data/golden_cases").glob("gc-*.yaml"))]

    t0 = time.perf_counter()
    lex_hits = hyb_hits = 0
    lat: list[float] = []
    per_case = []
    for case in cases:
        q = case["prompt"][:1200]
        tq = time.perf_counter()
        emb = await gate.embed(EmbeddingRequest(matter_ref=MATTER_REAL, texts=[q]))
        bm = bm25_search(con, "fts", q, 20, " AND doc_id LIKE 'real-%'")
        vr = [doc_of[idx_by_text[h.text]] for h in store.search(MATTER_REAL, emb.vectors[0], k=20)
              if h.text in idx_by_text]
        vr = list(dict.fromkeys(vr))
        fused = rrf([bm, vr])[:5]
        lat.append(time.perf_counter() - tq)
        src = source_of(case["id"])
        lex_hits += int(src in bm[:5])
        hyb_hits += int(src in fused)
        per_case.append({"id": case["id"], "source": src, "top5_hybrid": fused})
    wall = time.perf_counter() - t0
    return {"queries": len(cases), "wall_s": round(wall, 1),
            "mean_latency_s": round(sum(lat) / len(lat), 2),
            "source_recall_at5_lexical": f"{lex_hits}/{len(cases)}",
            "source_recall_at5_hybrid_rrf": f"{hyb_hits}/{len(cases)}",
            "vector_search": "pure-Python cosine (VectorStore as shipped, S7e)",
            "per_case": per_case}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=1000)
    ap.add_argument("--out", default=f"data/eval/R1-RESEARCH-{date.today().isoformat()}")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--skip-synthetic", action="store_true")
    ap.add_argument("--skip-real", action="store_true")
    args = ap.parse_args()
    if args.selfcheck:
        selfcheck()
        return
    if args.quick:
        args.docs = min(args.docs, 40)
    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    # build_gate asyncio.runs the probe internally (bootstrap.py:115) — call it OUTSIDE
    # the run() loop, the S7e nested-asyncio lesson (accept_s7e driver, commit 7cc1642).
    print(f"[gate] building (probe + routing {ROUTING.name})...")
    gate, _rt, _aliases = build_gate(out_dir / "trace.sqlite3", ROUTING)
    asyncio.run(run(args, gate))


if __name__ == "__main__":
    main()
