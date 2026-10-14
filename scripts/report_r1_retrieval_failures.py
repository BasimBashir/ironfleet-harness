"""R1 retrieval failure report (2026-10-14): classify EVERY expected citation needle.

The measurement the programme was missing: "did retrieval fail, or was the authority
never there?" Per needle over the 30 golden cases on the live acceptance corpus:

  ABSENT               the citation surface exists nowhere in the stored corpus
                       -> ingestion/licence work, NOT retrieval tuning
  PRESENT_NOT_RETRIEVED in the corpus but never entered any leg's candidate pool
                       (depth 50, all queries) -> pool-formation work
  LOST_AT_RERANK       in the merged pool but below the reranked top-k window
                       -> reranker / window-depth work (rerank_rank recorded so
                       deeper windows can be simulated without re-running)
  SUPPLIED             in the final top-k evidence window

Categories 5-6 of the programme taxonomy (citation WRONG despite the passage
supplied / conclusion unsupported) are DRAFTING-side: this report measures supply
only and says so. Supply is scored with the production scorer (citation_hit,
variant-tolerant) — identical rules to the C4 acceptance axis.

Also measured per case: raw single-query supply (today's C4 path) vs multi-query
pool supply vs multi+rerank supply; pool duplicate rate; expansion output;
rerank latency. Everything lands in data/eval/R1-ACCEPT/.

Structure note: build_live_stack uses asyncio.run internally, so this runs SYNC
with per-call asyncio.run — the accept_r1.py pattern.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MATTER = "m-r1-accept"
POOL_CAP = 48                      # the rerank pool bound (RerankRequest refuses > 64)
WINDOW_K = 5                       # the product evidence window (acceptance axis)


def classify(needle_rec: dict) -> str:
    if not needle_rec["present"]:
        return "ABSENT"
    if needle_rec["final_supplied"]:
        return "SUPPLIED"
    if needle_rec["pool_supplied"]:
        return "LOST_AT_RERANK"
    return "PRESENT_NOT_RETRIEVED"


def main_sync() -> None:
    from harness.corpus import expand_query
    from harness.eval.golden_case import load_cases
    from harness.eval.scorers import _norm, citation_hit, citation_variants
    from harness.gate import EmbeddingRequest, LLMRequest, RerankRequest
    from scripts.corpus_ingest import build_live_stack

    gate, store = build_live_stack("failure_report_trace.sqlite3", MATTER)
    cases = load_cases(REPO / "data/golden_cases")

    # ---- corpus presence index (text-derived; no dispatches) --------------------
    print("[presence] scanning stored chunks...", flush=True)
    with store._c() as c:
        rows = c.execute(
            f"SELECT doc_id, heading, body FROM {_mtab()}").fetchall()
    chunk_norms = [_norm(f"{h}\n{b}") for _d, h, b in rows]
    chunk_raw = [f"{h}\n{b}" for _d, h, b in rows]
    print(f"[presence] {len(rows)} chunks indexed", flush=True)

    def presence(needle: str) -> bool:
        for v in citation_variants(needle):
            nv = _norm(v)
            if nv and any(nv in cn for cn in chunk_norms):
                return True
            if any(v in raw for raw in chunk_raw):
                return True
        return False

    def dispatch(prompt: str) -> str:
        res = asyncio.run(gate.dispatch(LLMRequest(
            matter_ref=MATTER, task_class="extraction", model="qwen3.8:27b",
            messages=[{"role": "user", "content": prompt}], max_tokens=2048)))
        return res.content or ""

    def embed(texts: list[str]) -> list[list[float]]:
        res = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=MATTER, texts=texts)))
        return res.vectors

    out: dict = {"matter": MATTER, "window_k": WINDOW_K, "pool_cap": POOL_CAP,
                 "cases": [], "rerank_available": True}
    needle_rows: list[dict] = []
    tot = {"needles": 0, "raw_top5": 0, "multi_top5": 0, "multi_top5_pool": 0,
           "final_top5": 0, "final_top10": 0, "final_top20": 0, "pool48": 0}
    for i, case in enumerate(cases):
        t0 = time.time()
        prompt = case.prompt[:1200]
        needles = case.expected_citations

        # 1. today's single-query path (the C4 baseline leg)
        hits = store.search(MATTER, prompt, embed([prompt])[0], k=WINDOW_K, candidates=50)
        raw_blob = "\n".join(h.text for h in hits)

        # 2. multi-query pool construction (the new path)
        t_exp = time.time()
        alts = expand_query(prompt, dispatch)
        expansion = [a for a in alts]
        queries = [prompt] + alts
        qvecs = embed([q[:1200] for q in queries])
        fused, supply = store.search_multi(MATTER, list(zip(queries, qvecs)), candidates=50)
        expansion_s = time.time() - t_exp
        pool = fused[:POOL_CAP]
        pool_blob = "\n".join(h.text for h in pool)
        sightings = sum(len(v) for v in supply.values())
        dup_rate = round(1 - len(fused) / sightings, 3) if sightings else 0.0

        # 3. rerank the merged pool; the window is the reranked top-k
        t_rr = time.time()
        rerank_error = ""
        order: list[int] = []
        try:
            scores = asyncio.run(gate.rerank(RerankRequest(
                matter_ref=MATTER, query=prompt,
                texts=[h.text[:4000] for h in pool]))).scores
            order = sorted(range(len(pool)), key=lambda j: -scores[j])
        except Exception as ex:                        # noqa: BLE001 — honest degradation
            rerank_error = f"{type(ex).__name__}: {ex}"
            out["rerank_available"] = False
        rerank_s = round(time.time() - t_rr, 2)
        ranked = order if order else list(range(len(pool)))

        def blob_at(k: int) -> str:
            return "\n".join(pool[j].text for j in ranked[:k])

        final5, final10, final20 = blob_at(5), blob_at(10), blob_at(20)

        case_rec = {"case": case.id, "needles": len(needles),
                    "raw_top5": 0, "pool48": 0, "final_top5": 0,
                    "expanded": expansion, "expansion_s": round(expansion_s, 1),
                    "pool_len": len(fused), "dup_rate": dup_rate,
                    "rerank_s": rerank_s, "rerank_error": rerank_error,
                    "wall_s": 0}
        for n in needles:
            rec = {"case": case.id, "needle": n,
                   "present": presence(n),
                   "raw_supplied": citation_hit(raw_blob, n),
                   "pool_supplied": citation_hit(pool_blob, n),
                   "final_supplied": citation_hit(final5, n),
                   "supplied_at10": citation_hit(final10, n),
                   "supplied_at20": citation_hit(final20, n),
                   "multi_fused_rank": None, "rerank_rank": None}
            fused_rank = next((r for r, j in enumerate(ranked)
                               if citation_hit(pool[j].text, n)), None)
            rec["rerank_rank"] = fused_rank
            if not rec["final_supplied"]:
                deep = next((r for r in range(len(fused))
                             if citation_hit(fused[r].text, n)), None)
                rec["multi_fused_rank"] = deep
            rec["class"] = classify(rec)
            needle_rows.append(rec)
            case_rec["raw_top5"] += int(rec["raw_supplied"])
            case_rec["pool48"] += int(rec["pool_supplied"])
            case_rec["final_top5"] += int(rec["final_supplied"])
            tot["needles"] += 1
            tot["raw_top5"] += int(rec["raw_supplied"])
            tot["pool48"] += int(rec["pool_supplied"])
            tot["multi_top5"] += int(rec["pool_supplied"])   # un-reranked pool supply (diag)
            tot["final_top5"] += int(rec["final_supplied"])
            tot["final_top10"] += int(rec["supplied_at10"])
            tot["final_top20"] += int(rec["supplied_at20"])
        case_rec["wall_s"] = round(time.time() - t0, 1)
        out["cases"].append(case_rec)
        print(f"  [{i+1}/30] {case.id}: raw {case_rec['raw_top5']}/{len(needles)} "
              f"pool48 {case_rec['pool48']} final {case_rec['final_top5']} "
              f"(pool {len(fused)}, dup {dup_rate}, exp {expansion[0][:40] if expansion else 'NONE'}, "
              f"{case_rec['wall_s']}s)", flush=True)

    # final per-needle classification rollup
    for rec in needle_rows:
        if rec["multi_fused_rank"] is not None and not rec["pool_supplied"]:
            rec["class"] = "PRESENT_BELOW_POOL"          # retrieved, outside the 48 bound
    by_class: dict[str, int] = {}
    for rec in needle_rows:
        by_class[rec["class"]] = by_class.get(rec["class"], 0) + 1
    tot["multi_top5_pool"] = tot.pop("multi_top5")
    out["totals"] = tot
    out["class_counts"] = by_class
    out["needles_detail"] = needle_rows
    dest = REPO / "data/eval/R1-ACCEPT/retrieval_failure_report.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("WROTE", dest)
    print("TOTALS", tot)
    print("CLASSES", by_class)


def _mtab() -> str:
    import re
    return "fts_" + re.sub(r"[^A-Za-z0-9_]", "_", MATTER)


if __name__ == "__main__":
    main_sync()
