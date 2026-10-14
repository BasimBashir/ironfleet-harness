"""R1 retrieval probe: multi-query expansion vs the raw prompt (2026-10-14).

Evidence probe, not product code. Hypothesis: the golden-case prompts are 1,200-char
fact patterns — terrible single queries — and the needle-containing chunks never enter
the top-50 candidate pool (measured: fused20 supply 9/69, rerank-of-20 6/69; both legs
recover only 18-23/69 even at depth 200). Test whether LLM issue-focused queries move
the needle supply at top-5, which the product corpus_search would then compose.

Writes JSON evidence to data/eval/R1-ACCEPT/query_expansion_probe.json.

Structure note: build_live_stack uses asyncio.run internally (the S7e nested-loop trap),
so the stack is built in a SYNC context and each gate call gets its own asyncio.run —
the accept_r1.py pattern.
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

EXPAND_TMPL = """You are a legal retrieval expert. Given this New Zealand legal problem, output \
exactly 3 short search queries (one line each, no numbering, no commentary) that a hybrid \
lexical+semantic search engine should run to retrieve (a) the governing statutory provisions, \
(b) the leading cases on the point, and (c) the procedural rule. Each query under 20 words, \
dense with the salient legal terms — not the facts of the parties.

PROBLEM:
{prompt}"""


def main_sync() -> None:
    from harness.corpus import CorpusStore
    from harness.eval.golden_case import load_cases
    from harness.eval.scorers import citation_hit
    from harness.gate import EmbeddingRequest, LLMRequest, RerankRequest
    from harness.paths import resolve_store_root
    from harness.vectors import VectorStore
    from scripts.corpus_ingest import build_live_stack

    root, _ = resolve_store_root()
    store = CorpusStore(root / "corpus.sqlite3",
                        vectors=VectorStore(root / "vectors.sqlite3"))
    gate, _ = build_live_stack("expand_probe_trace.sqlite3", MATTER)
    cases = load_cases(REPO / "data/golden_cases")

    def supply(queries: list[str], k: int, dedup_to: int | None = None) -> str:
        """Union the top-k fused chunks across queries; return the joined blob."""
        texts: list[str] = []
        for q in queries:
            res = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=MATTER, texts=[q])))
            hits = store.search(MATTER, q, res.vectors[0], k=k, candidates=50)
            for h in hits:
                if h.text not in texts:
                    texts.append(h.text)
        if dedup_to:
            texts = texts[:dedup_to]
        return "\n".join(texts)

    def supply_count(blob: str, needles: list[str]) -> int:
        return sum(1 for n in needles if citation_hit(blob, n))

    out: dict = {"cases": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    tot_raw = tot_x3 = tot_xr = 0
    for i, c in enumerate(cases):
        t0 = time.time()
        prompt = c.prompt[:1200]
        needles = c.expected_citations
        n_raw = supply_count(supply([prompt], 5), needles)

        exp = asyncio.run(gate.dispatch(LLMRequest(
            matter_ref=MATTER, task_class="extraction", model="qwen3.8:27b",
            messages=[{"role": "user", "content": EXPAND_TMPL.format(prompt=prompt)}],
            max_tokens=2048)))
        expanded = [ln.strip() for ln in (exp.content or "").splitlines()
                    if ln.strip() and not ln.strip().startswith(("#", "[", "*"))
                    and len(ln.strip()) > 8][:3]
        blob_x = supply([prompt] + expanded, 5)
        n_x3 = supply_count(blob_x, needles)

        # rerank the union pool: does the cross-encoder lift the best chunks to the top?
        pool = supply([prompt] + expanded, 10).split("\n")[:40]
        rr_scores: list[float] = []
        for j in range(0, len(pool), 20):
            rr = asyncio.run(gate.rerank(RerankRequest(
                matter_ref=MATTER, query=prompt, texts=[t[:1500] for t in pool[j:j + 20]])))
            rr_scores.extend(rr.scores)
        order = sorted(range(len(pool)), key=lambda j: -rr_scores[j]) if rr_scores else []
        n_xr = supply_count("\n".join(pool[j] for j in order[:5]), needles)

        tot_raw += n_raw
        tot_x3 += n_x3
        tot_xr += n_xr
        rec = {"case": c.id, "needles": needles, "expanded": expanded,
               "raw_prompt_top5": n_raw, "expanded_top5": n_x3,
               "expanded_rerank_top5": n_xr, "elapsed_s": round(time.time() - t0, 1)}
        out["cases"].append(rec)
        print(f"  [{i+1}/30] {c.id}: raw {n_raw}/{len(needles)} exp {n_x3} "
              f"exp+rr {n_xr} ({rec['elapsed_s']}s) — {expanded[0][:50] if expanded else 'NO EXPANSION'}",
              flush=True)

    out["totals"] = {"needles": sum(len(c.expected_citations) for c in cases),
                     "raw_prompt_top5": tot_raw, "expanded_top5": tot_x3,
                     "expanded_rerank_top5": tot_xr}
    dest = REPO / "data/eval/R1-ACCEPT/query_expansion_probe.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("WROTE", dest, out["totals"])


if __name__ == "__main__":
    main_sync()
