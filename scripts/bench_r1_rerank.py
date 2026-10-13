"""R1 research gate — reranker A/B on the real 31-doc corpus (uses the smoke bench's stores).

For each of the 30 golden-case prompts:
  hybrid RRF (BM25 + bge-m3 vector, k=60) top-5              -> recall@5 + verbatim-citation hit
  the SAME fused top-20, reranked by FlashRank (local ONNX)  -> recall@5 + verbatim-citation hit

Verbatim-citation hit = an expected_citations needle found in a retrieved chunk under the
PRODUCTION scorer's normaliser (harness.eval.scorers.citation_hit) — the R1 acceptance axis.

Also measures pure-Python VectorStore search latency at the smoke corpus's chunk count
(the "named sqlite-vec/numpy swap" datum for the verdict).

Usage: python scripts/bench_r1_rerank.py [--stores data/eval/R1-RESEARCH-smoke]
Writes <stores>/rerank_ab.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from harness.gate import EmbeddingRequest  # noqa: E402
from harness.eval.scorers import citation_hit  # noqa: E402
from scripts.bench_r1_ingest import MATTER_REAL, bm25_search, rrf, split_structure  # noqa: E402
from scripts.stand_up_opencode import ROUTING, build_gate  # noqa: E402
from harness.vectors import VectorStore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stores", default="data/eval/R1-RESEARCH-smoke")
    ap.add_argument("--backend", choices=["flashrank", "server"], default="flashrank")
    ap.add_argument("--server-url", default="http://127.0.0.1:8778")
    ap.add_argument("--rerank-model", default="ms-marco-MiniLM-L-12-v2")
    args = ap.parse_args()
    stores = REPO / args.stores

    import yaml

    ranker = None
    if args.backend == "flashrank":
        from flashrank import Ranker
        t0 = time.perf_counter()
        ranker = Ranker(model_name=args.rerank_model)   # downloads ~34 MB on first use
        print(f"[rerank] {args.rerank_model} loaded in {time.perf_counter() - t0:.1f}s")
    else:
        import urllib.request
        health = urllib.request.urlopen(f"{args.server_url}/health", timeout=10).read()
        assert b"ok" in health, health

    def rerank(q: str, cand_docs: list[str], cand_texts: list[str]) -> list[str]:
        if args.backend == "flashrank":
            from flashrank import RerankRequest
            ranked = ranker.rerank(RerankRequest(query=q, passages=[
                {"id": d, "text": t} for d, t in zip(cand_docs, cand_texts)]))
            return [r["id"] for r in ranked]
        import urllib.request
        req = urllib.request.Request(
            f"{args.server_url}/rerank",
            data=json.dumps({"model": "qwen3-reranker", "query": q,
                             "documents": cand_texts}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            results = json.load(resp)["results"]
        return [cand_docs[r["index"]] for r in sorted(results, key=lambda r: -r["relevance_score"])]

    con = __import__("sqlite3").connect(stores / "lexical.sqlite3")
    store = VectorStore(stores / "vectors.sqlite3")

    real_texts: dict[str, str] = {}   # doc_id -> concatenated chunk text (verbatim scoring)
    doc_of_seq: list[str] = []
    for (doc_id, heading, body) in con.execute(
            "SELECT doc_id, heading, body FROM fts WHERE doc_id LIKE 'real-%'"):
        real_texts[doc_id] = real_texts.get(doc_id, "") + "\n\n" + body
    chunks: list[tuple[str, str, str]] = [
        (d, h, b) for (d, h, b) in con.execute(
            "SELECT doc_id, heading, body FROM fts WHERE doc_id LIKE 'real-%'")]
    # 2026-10-13 correction: VectorStore.seq is BATCH-LOCAL — mapping hits by seq to a
    # global list is garbage. Map by the stored text (the store's own row identity).
    idx_by_text = {f"{h}\n{b}" if h else b: i for i, (d, h, b) in enumerate(chunks)}
    doc_of = [c[0] for c in chunks]

    gate, _rt, _aliases = build_gate(stores / "trace_rerank.sqlite3", ROUTING)

    async def queries() -> list[dict]:
        cases = [yaml.safe_load(p.read_text(encoding="utf-8"))
                 for p in sorted((REPO / "data/golden_cases").glob("gc-*.yaml"))]
        out = []
        for case in cases:
            q = case["prompt"][:1200]
            emb = await gate.embed(EmbeddingRequest(matter_ref=MATTER_REAL, texts=[q]))
            out.append({"case": case, "qvec": emb.vectors[0]})
        return out

    print("[gate] embedding 30 golden queries...")
    qd = asyncio.run(queries())

    # source doc per case: same token-overlap mapping as the ingest bench, eyeballed there
    import re
    def source_of(case_id: str) -> str | None:
        tokens = [t for t in re.split(r"[-\d]+", case_id.split("-", 3)[-1]) if t]
        best, best_n = None, 0
        for d in real_texts:
            n = sum(1 for t in tokens if t in d.lower())
            if n > best_n:
                best, best_n = d, n
        return best

    # vector-search latency datum at this store's chunk count (pure-Python cosine)
    n_vec = store.count(MATTER_REAL)
    lat_samples = []
    for item in qd[:10]:
        t0 = time.perf_counter()
        store.search(MATTER_REAL, item["qvec"], k=20)
        lat_samples.append(time.perf_counter() - t0)
    vec_ms = sum(lat_samples) / len(lat_samples) * 1000

    rows = []
    lex_hits = hyb_hits = rr_hits = 0
    lex_cit = hyb_cit = rr_cit = 0
    total_cit = 0
    rr_ms_samples = []
    for item in qd:
        case, qvec = item["case"], item["qvec"]
        q = case["prompt"][:1200]
        needles = case.get("expected_citations") or []
        total_cit += len(needles)

        bm = bm25_search(con, "fts", q, 20, " AND doc_id LIKE 'real-%'")
        vr = [doc_of[idx_by_text[h.text]] for h in store.search(MATTER_REAL, qvec, k=20)
              if h.text in idx_by_text]
        vr = list(dict.fromkeys(vr))
        fused = rrf([bm, vr])[:20]

        # dedupe for rerank, keep fused order for tie stability
        cand_docs = list(dict.fromkeys(fused))
        cand_texts = [real_texts[d][:4000] for d in cand_docs]
        t0 = time.perf_counter()
        rr_top5 = rerank(q, cand_docs, cand_texts)[:5]
        rr_ms_samples.append((time.perf_counter() - t0) * 1000)

        lex5, hyb5 = bm[:5], fused[:5]
        src = source_of(case["id"])
        lex_hits += int(src in lex5)
        hyb_hits += int(src in hyb5)
        rr_hits += int(src in rr_top5)

        def cit_hit(docs: list[str]) -> int:
            blob = "\n".join(real_texts[d] for d in docs)
            return sum(1 for n in needles if citation_hit(blob, n))

        lex_cit += cit_hit(lex5)
        hyb_cit += cit_hit(hyb5)
        rr_cit += cit_hit(rr_top5)
        rows.append({"id": case["id"], "source": src, "in_lex5": src in lex5,
                     "in_hyb5": src in hyb5, "in_rr5": src in rr_top5})

    n = len(qd)
    out = {
        "date": date.today().isoformat(),
        "reranker": args.rerank_model if args.backend == "flashrank"
                    else f"llama-server b11580 vulkan + ggml-org Qwen3-Reranker-0.6B-Q8_0",
        "backend": args.backend,
        "queries": n,
        "vector_search_ms_pure_python": round(vec_ms, 1),
        "vector_chunks": n_vec,
        "rerank_ms_mean": round(sum(rr_ms_samples) / len(rr_ms_samples), 1),
        "source_recall_at5": {
            "lexical": f"{lex_hits}/{n}",
            "hybrid_rrf": f"{hyb_hits}/{n}",
            "hybrid_rrf_plus_rerank": f"{rr_hits}/{n}",
        },
        "verbatim_citation_hits": {
            "note": "expected_citations needles found verbatim (production normaliser) "
                    "in the union of top-5 chunk texts",
            "lexical": f"{lex_cit}/{total_cit}",
            "hybrid_rrf": f"{hyb_cit}/{total_cit}",
            "hybrid_rrf_plus_rerank": f"{rr_cit}/{total_cit}",
        },
        "per_case": rows,
    }
    (stores / "rerank_ab.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_case"}, indent=2))
    print(f"[done] -> {stores / 'rerank_ab.json'}")


if __name__ == "__main__":
    main()
