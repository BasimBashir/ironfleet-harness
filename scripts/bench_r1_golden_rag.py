"""R1 quality gate — golden-case RAG test (user-directed 2026-10-13: quality before speed).

The question the research gate did NOT answer: do golden-case drafts built on RETRIEVED
passages actually cite exactly? The A7 baseline (no corpus) is the comparison point:
thomson1-chat citation_accuracy 0.117 / grounding 0.367 on these same 30 cases under
production scorers (data/eval/A7-MODEL-SUBSTITUTION-2026-10-09.md).

Arms, same 30 cases, same model (thomson1-chat, the incumbent), same scorer:
  hybrid8  — top-8 passages by hybrid RRF (BM25 + bge-m3 vector, k=60)
  rerank5  — the RRF top-12 reranked by llama-server Qwen3-Reranker-0.6B, top-5 kept

Measured per case x arm (all deterministic, production machinery):
  citation_accuracy / grounding_score / persona checks / passed (score_case)
  retrieval ceiling — expected needles present in the SUPPLIED passages (citation_hit)
  quote_verification — draft quotations found verbatim (normalised) in supplied passages
  empty_content / refusal accounting (the S7h sidecar pattern; resume by case+arm)

Live discipline: retrieval goes through gate.embed (LOCAL_ONLY, real trace); drafting
dispatches through gate.dispatch on the research class with the RECORDED in-memory
admission override (2026-08-28 precedent; traced verified=0). The rerank server is
started and stopped BY THIS DRIVER around the retrieval phase only, so the 21GB draft
model never contends with it for VRAM (the bench lesson that killed the first full run).

Usage:
  python scripts/bench_r1_golden_rag.py --limit 2          # smoke
  python scripts/bench_r1_golden_rag.py                    # full 30 x 2 arms (hours)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from harness.gate import EmbeddingRequest, LLMRequest  # noqa: E402
from harness.eval.golden_case import load_cases  # noqa: E402
from harness.eval.scorers import citation_hit, score_case  # noqa: E402
from harness.vectors import VectorStore  # noqa: E402
from scripts.bench_r1_ingest import MATTER_REAL, bm25_search, rrf  # noqa: E402
from scripts.stand_up_opencode import ROUTING, build_gate  # noqa: E402

SMOKE_STORES = REPO / "data/eval/R1-RESEARCH-smoke"
RERANK_SERVER_DIR = REPO / "data/eval/R1-RESEARCH-2026-10-13/rerank-server"
RERANK_URL = "http://127.0.0.1:8778"
OUT_DIR = REPO / f"data/eval/R1-GOLDEN-RAG-{date.today().isoformat()}"
MATTER = "m-r1-goldenrag"                     # colon-free
MODEL_DRAFT = "thomson1-chat:latest"
# A7 dashboard comparison point (same 30 cases, same model, same scorers, no corpus):
BASELINE = {"citation_accuracy": 0.117, "grounding_score": 0.367}

PROMPT_TMPL = """You are a New Zealand law firm assistant. Draft the advice requested below.

STRICT CITATION RULES:
- Use ONLY the law extracts provided here as sources. Do not cite any authority that is
  not in the extracts.
- When you state a legal proposition taken from an extract, cite that extract's case or
  statute exactly as written in its header line.
- Any direct quotation MUST be copied word-for-word from an extract.

LAW EXTRACTS:
{extracts}

TASK:
{prompt}"""


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[-‐-―]+", "", s).lower().split())


def extract_quotes(text: str) -> list[str]:
    out = []
    for m in re.finditer(r'"([^"]{8,400})"|[“]([^”]{8,400})[”]', text):
        out.append(m.group(1) or m.group(2))
    return out


def quote_verification(draft: str, passages: list[str]) -> tuple[int, int]:
    """(verified, total) quoted spans found word-for-word (normalised) in the passages."""
    blob = " ".join(_norm(p) for p in passages)
    quotes = extract_quotes(draft)
    return sum(1 for q in quotes if _norm(q) in blob), len(quotes)


def load_real_chunks() -> tuple[list[str], list[str], dict[int, int]]:
    """(doc_ids, texts, rowid->index) of the real corpus store the smoke bench built."""
    import sqlite3
    con = sqlite3.connect(SMOKE_STORES / "lexical.sqlite3")
    rows = con.execute("SELECT rowid, doc_id, heading, body FROM fts "
                       "WHERE doc_id LIKE 'real-%' ORDER BY rowid").fetchall()
    con.close()
    texts = [f"{h}\n{b}" if h else b for _, _, h, b in rows]
    docs = [d for _, d, _, _ in rows]
    rowid_to_idx = {r: i for i, (r, *_ ) in enumerate(rows)}
    return docs, texts, rowid_to_idx


def start_rerank_server() -> subprocess.Popen:
    exe = RERANK_SERVER_DIR / "llama-server.exe"
    gguf = RERANK_SERVER_DIR / "qwen3-reranker-0.6b-q8_0.gguf"
    if not exe.exists() or not gguf.exists():
        raise RuntimeError(f"rerank server binaries missing under {RERANK_SERVER_DIR} "
                           f"(local-only; see research/06 for the download recipe)")
    proc = subprocess.Popen(
        [str(exe), "--reranking", "--pooling", "rank", "--embd-normalize", "-1",
         "-m", str(gguf), "--port", "8778", "-c", "16384", "-b", "8192", "-ngl", "99",
         "--host", "127.0.0.1"],
        cwd=str(RERANK_SERVER_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{RERANK_URL}/health", timeout=2)
            return proc
        except Exception:                              # noqa: BLE001 — still booting
            time.sleep(2)
    proc.terminate()
    raise RuntimeError("rerank server did not become healthy in 120s")


def rerank_docs(query: str, cand_texts: list[str]) -> list[int]:
    req = urllib.request.Request(
        f"{RERANK_URL}/rerank",
        data=json.dumps({"model": "qwen3-reranker", "query": query,
                         "documents": cand_texts}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        results = json.load(resp)["results"]
    return [r["index"] for r in sorted(results, key=lambda r: -r["relevance_score"])]


def retrieve(gate, cases, rerank: bool) -> dict:
    """case_id -> passages per arm, fused at CHUNK level.

    2026-10-13 correction (found by this bench's own drafts): VectorStore.seq is
    BATCH-LOCAL (restarts at 0 every 64-batch add), so mapping hits by seq to a global
    list is garbage — map by the stored TEXT instead. And passage assembly must take the
    fused CHUNKS, not the first chunk of each doc (that supplied every draft the document
    title line and nothing else)."""
    docs, texts, rowid_to_idx = load_real_chunks()
    by_text = {t: i for i, t in enumerate(texts)}
    store = VectorStore(SMOKE_STORES / "vectors.sqlite3")
    lex = sqlite3_connect_lexicon()
    out: dict = {}
    for case in cases:
        q = case.prompt[:1200]
        emb = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=MATTER, texts=[q])))
        lex_chunks = [rowid_to_idx[r] for r in bm25_chunk_rowids(lex, q, 12)
                      if r in rowid_to_idx]
        vec_chunks = [by_text[h.text] for h in store.search(MATTER_REAL, emb.vectors[0], k=12)
                      if h.text in by_text]
        fused = rrf([lex_chunks, vec_chunks])
        hyb = fused[:8]
        rr = hyb
        if rerank and len(fused) > 1:
            order = rerank_docs(q, [texts[i][:4000] for i in fused[:12]])
            rr = [fused[i] for i in order[:5]]
        blob = "\n".join(texts[i] for i in hyb)
        ceiling_h = sum(1 for n in case.expected_citations if citation_hit(blob, n))
        words = [len(texts[i].split()) for i in hyb]
        out[case.id] = {
            "hybrid8": [passage(i, docs, texts) for i in hyb],
            "rerank5": [passage(i, docs, texts) for i in rr],
            "ceiling_hybrid8": f"{ceiling_h}/{len(case.expected_citations)}",
            "passage_words_min_mean": f"{min(words)}/{sum(words) // max(1, len(words))}",
        }
        print(f"  [retrieve] {case.id}: ceiling {ceiling_h}/{len(case.expected_citations)} "
              f"passage-words min/mean {out[case.id]['passage_words_min_mean']}", flush=True)
    return out


def bm25_chunk_rowids(con, query: str, k: int) -> list[int]:
    """CHUNK-level BM25 ranking; returns absolute fts rowids (mapped by the caller)."""
    terms = [t for t in re.findall(r"[A-Za-z0-9]{3,}", query)][:24]
    if not terms:
        return []
    q = " OR ".join(f'"{t}"' for t in terms)
    try:
        rows = con.execute(
            "SELECT rowid FROM fts WHERE fts MATCH ? AND doc_id LIKE 'real-%' "
            "ORDER BY bm25(fts) LIMIT ?", (q, k)).fetchall()
    except Exception:                                  # noqa: BLE001 — no match syntax edge
        return []
    return [r[0] for r in rows]


def passage(i: int, docs: list[str], texts: list[str]) -> dict:
    return {"source": docs[i].removeprefix("real-"), "text": texts[i]}


def sqlite3_connect_lexicon():
    import sqlite3
    return sqlite3.connect(SMOKE_STORES / "lexical.sqlite3")


def draft_prompt(case, passages: list[dict]) -> str:
    exts = "\n\n".join(
        f"[Extract {n + 1} | {p['source']}]\n{p['text']}"
        for n, p in enumerate(passages))
    return PROMPT_TMPL.format(extracts=exts, prompt=case.prompt.strip())


async def draft_arm(gate, case, passages: list[dict]) -> tuple[str, dict]:
    prompt = draft_prompt(case, passages)
    res = await gate.dispatch(LLMRequest(
        matter_ref=MATTER, task_class="research", model=MODEL_DRAFT,
        messages=[{"role": "user", "content": prompt}], max_tokens=16384))
    return (res.content or ""), res.usage


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="smoke: first N cases only")
    ap.add_argument("--arms", default="hybrid8,rerank5")
    ap.add_argument("--no-retrieval", action="store_true", help="reuse the saved retrieval")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",")]

    cases = load_cases(REPO / "data/golden_cases")
    if args.limit:
        cases = cases[:args.limit]

    gate, _rt, _al = build_gate(OUT_DIR / "trace.sqlite3", ROUTING)
    # The recorded in-memory admission override (2026-08-28 precedent; CR-3 untouched;
    # src/ untouched; every dispatch traces the honest verified=0).
    gate.registry.get("ollama-local").admitted = "full"
    print("[deviation] in-memory admission override for ollama-local (recorded precedent)",
          flush=True)

    retr_path = OUT_DIR / "retrieval.json"
    if args.no_retrieval and retr_path.exists():
        retrieval = json.loads(retr_path.read_text(encoding="utf-8"))
    else:
        rerank_on = "rerank5" in arms
        proc = start_rerank_server() if rerank_on else None
        try:
            retrieval = retrieve(gate, cases, rerank=proc is not None)
        finally:
            if proc is not None:
                proc.terminate()
                print("[rerank] server stopped before the draft phase (VRAM discipline)",
                      flush=True)
        retr_path.write_text(json.dumps(retrieval, indent=1), encoding="utf-8")

    sidecar = OUT_DIR / "sidecar.jsonl"
    done: set[str] = set()
    if sidecar.exists():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add(f"{r['case_id']}|{r['arm']}")

    t0 = time.perf_counter()
    with sidecar.open("a", encoding="utf-8") as fh:
        for case in cases:
            for arm in arms:
                key = f"{case.id}|{arm}"
                if key in done:
                    continue
                passages = retrieval[case.id][arm]
                t_c = time.perf_counter()
                row: dict = {"case_id": case.id, "arm": arm, "date": date.today().isoformat(),
                             "model": MODEL_DRAFT,
                             "ceiling": retrieval[case.id]["ceiling_hybrid8"]
                             if arm == "hybrid8" else None}
                try:
                    content, usage = asyncio.run(draft_arm(gate, case, passages))
                    sc = score_case(content, case)
                    qv, qn = quote_verification(content, [p["text"] for p in passages])
                    row |= {"status": sc.status, "citation_accuracy": sc.citation_accuracy,
                            "grounding_score": sc.grounding_score,
                            "persona": sc.checks, "passed": sc.passed,
                            "quotes_verified": f"{qv}/{qn}",
                            "tokens_in": sum(usage.values()), "wall_s":
                            round(time.perf_counter() - t_c, 1), "content": content}
                except Exception as ex:                    # noqa: BLE001 — recorded, keep going
                    row |= {"status": "error", "error": str(ex)[:400]}
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                ca = row.get("citation_accuracy")
                print(f"  [draft] {key}: ca={ca} gs={row.get('grounding_score')} "
                      f"qv={row.get('quotes_verified')} "
                      f"({round(time.perf_counter() - t_c, 1)}s)", flush=True)

    summarize(sidecar, cases, arms)


def summarize(sidecar: Path, cases, arms: list[str]) -> None:
    rows = [json.loads(l) for l in sidecar.read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = [f"# R1 golden-case RAG quality test — {date.today().isoformat()}", "",
             f"Model {MODEL_DRAFT}, production scorers, {len(cases)} golden cases.",
             f"Baseline (A7, no corpus): ca {BASELINE['citation_accuracy']} / "
             f"gs {BASELINE['grounding_score']}.", "",
             "| arm | n | citation_accuracy | grounding | quote-verification | passed |",
             "|---|---|---|---|---|---|"]
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm and r.get("status") == "scored"]
        if not rs:
            continue
        ca = sum(r["citation_accuracy"] for r in rs) / len(rs)
        gs = sum(r["grounding_score"] for r in rs) / len(rs)
        qv = sum(int(r["quotes_verified"].split("/")[0]) for r in rs)
        qn = sum(int(r["quotes_verified"].split("/")[1]) for r in rs)
        np_ = sum(1 for r in rs if r["passed"])
        lines.append(f"| {arm} | {len(rs)} | {ca:.3f} | {gs:.3f} | {qv}/{qn} | {np_}/{len(rs)} |")
    errs = [r for r in rows if r.get("status") != "scored"]
    if errs:
        lines += ["", "## Non-scored", ""] + \
                 [f"- {r['case_id']}|{r['arm']}: {r.get('status')} {r.get('error', '')[:160]}"
                  for r in errs]
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
