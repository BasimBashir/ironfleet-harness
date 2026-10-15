"""R1 quality gate — golden-case RAG test (user-directed 2026-10-13: quality before speed).

The question the research gate did NOT answer: do golden-case drafts built on RETRIEVED
passages actually cite exactly? The A7 baseline (no corpus) is the comparison point:
thomson1-chat citation_accuracy 0.117 / grounding 0.367 on these same 30 cases under
production scorers (data/eval/A7-MODEL-SUBSTITUTION-2026-10-09.md).

Arms, same 30 cases, same model (thomson1-chat, the incumbent), same scorer,
SAME product-path retrieval (multi-query pool + citation join keys over the LIVE
acceptance corpus, gate-rerank top-8 — 2026-10-15; the arms differ only in the
DRAFTING contract, isolating select-compose's effect):
  product8 — the product evidence window, plain drafting (PROMPT_TMPL contract)
  compose8 — D9 select-compose: references only, harness splices verbatim sentences
             (qv is a construction property; the measure verifies it)

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

from harness.corpus import CorpusStore, evidence_window, expand_query, splice_references  # noqa: E402
from harness.gate import EmbeddingRequest, LLMRequest, RerankRequest  # noqa: E402
from harness.eval.golden_case import load_cases  # noqa: E402
from harness.eval.scorers import citation_hit, score_case  # noqa: E402
from harness.paths import resolve_store_root  # noqa: E402
from harness.vectors import VectorStore  # noqa: E402
from scripts.stand_up_opencode import ROUTING, build_gate  # noqa: E402

RERANK_SERVER_DIR = REPO / "data/eval/R1-RESEARCH-2026-10-13/rerank-server"
RERANK_URL = "http://127.0.0.1:8778"
OUT_DIR = REPO / f"data/eval/R1-GOLDEN-RAG-{date.today().isoformat()}"
MATTER = "m-r1-goldenrag"                     # colon-free (drafting dispatches)
MATTER_LIVE = "m-r1-accept"                   # THE corpus (the product retrieval path)
MODEL_DRAFT = "thomson1-chat:latest"
MODEL_EXPAND = "qwen3.8:27b"                  # the probe's approved expansion path
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

# D9 select-compose: the model NEVER writes quoted prose — it emits [E#.S#] references
# into the numbered evidence window and the harness splices the verbatim sentences
# (research/07: quote fidelity 100% BY CONSTRUCTION, 781 refs / 0 invalid on a 30B model;
# v2 rule — quotation marks are banned outright).
COMPOSE_TMPL = """You are a New Zealand law firm assistant. Draft the advice requested below.

STRICT RULES:
- The evidence window below numbers every sentence as [E<extract>.S<sentence>]. Compose
  your answer by inserting these references — e.g. [E2.S17] — exactly where the cited
  sentence's content belongs.
- NEVER write quoted prose yourself. Quotation marks are FORBIDDEN in your output: the
  only quotations in the final document are spliced in from the references afterwards.
- Do not cite any authority that is not named in an evidence window header.

EVIDENCE WINDOW:
{window}

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
    """RETIRED with the smoke-store arms (2026-10-15): retrieval now rides the live
    acceptance corpus through the product path. Kept as a named removal — the smoke
    store was judgments-only, which is why statute needles could never be supplied."""
    raise RuntimeError("smoke-store retrieval retired; product_retrieve is the path")


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
    """RETIRED 2026-10-15: rerank rides gate.rerank (the traced LOCAL_ONLY provider)
    in the product path; the raw HTTP call was the smoke-store bench's."""
    raise RuntimeError("use gate.rerank via the product path")


def product_retrieve(gate, store: CorpusStore, case) -> dict:
    """The PRODUCT retrieval path for one case (2026-10-15): multi-query pool
    construction over the LIVE corpus — strict-schema expansion (qwen, mechanical
    class), one RRF across all (query, leg) rankings incl. the citation join keys,
    pool capped below the reranker's refusal ceiling, gate-rerank (traced), top-8.
    Replaces the smoke-store single-query arms that could not even see the statutes."""
    prompt = case.prompt[:1200]

    def dispatch(p: str) -> str:
        res = asyncio.run(gate.dispatch(LLMRequest(
            matter_ref=MATTER_LIVE, task_class="extraction", model=MODEL_EXPAND,
            messages=[{"role": "user", "content": p}], max_tokens=2048)))
        return res.content or ""

    alts = expand_query(prompt, dispatch)
    queries = [prompt] + alts
    qvecs = asyncio.run(gate.embed(EmbeddingRequest(
        matter_ref=MATTER_LIVE, texts=[q[:1200] for q in queries]))).vectors
    pool, _supply = store.search_multi(MATTER_LIVE, list(zip(queries, qvecs)),
                                       candidates=50)
    pool = pool[:48]                       # the reranker REFUSES above 64
    ranked: list = pool                    # fail-open: unranked pool keeps RRF order
    if len(pool) > 1:
        try:
            scores = asyncio.run(gate.rerank(RerankRequest(
                matter_ref=MATTER_LIVE, query=prompt,
                texts=[h.text[:4000] for h in pool]))).scores
            ranked = [pool[j] for j in sorted(range(len(pool)), key=lambda j: -scores[j])]
        except Exception as ex:            # noqa: BLE001 — honest degradation, recorded
            print(f"    [rerank] {case.id}: failed ({ex}) — RRF order used", flush=True)
    hits = ranked[:8]
    blob = "\n".join(h.text for h in hits)
    ceiling = sum(1 for n in case.expected_citations if citation_hit(blob, n))
    words = [len(h.text.split()) for h in hits]
    passages = [{"source": h.source_name, "text": h.text, "doc_id": h.doc_id}
                for h in hits]
    out = {"passages": passages,
           "ceiling": f"{ceiling}/{len(case.expected_citations)}",
           "expanded": alts,
           "pool_len": len(pool),
           "passage_words_min_mean": f"{min(words)}/{sum(words) // max(1, len(words))}"
           if words else "0/0"}
    print(f"  [retrieve] {case.id}: ceiling {ceiling}/{len(case.expected_citations)} "
          f"pool {len(pool)} alts {len(alts)} "
          f"words {out['passage_words_min_mean']}", flush=True)
    return out


def retrieve(gate, cases) -> dict:
    """case_id -> the product-path retrieval shared by BOTH arms (the arms differ in
    the DRAFTING contract, not the evidence: same passages = the comparison isolates
    select-compose's effect)."""
    root, _ = resolve_store_root()
    store = CorpusStore(root / "corpus.sqlite3",
                        vectors=VectorStore(root / "vectors.sqlite3"))
    return {case.id: product_retrieve(gate, store, case) for case in cases}


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


def compose_prompt(case, passages: list[dict]) -> str:
    window, _table = evidence_window(passages)
    return COMPOSE_TMPL.format(window=window, prompt=case.prompt.strip())


def compose_arm(gate, case, passages: list[dict]) -> tuple[str, dict, dict]:
    """D9 select-compose: draft = references only; the harness splices the verbatim
    sentences. Returns (final_text, usage, compose_stats). Quote fidelity on the
    spliced text is a construction property — the qv measure below VERIFIES it
    (refs spliced + any banned self-quotes the model smuggled in)."""
    _block, table = evidence_window(passages)
    res = asyncio.run(gate.dispatch(LLMRequest(
        matter_ref=MATTER, task_class="research", model=MODEL_DRAFT,
        messages=[{"role": "user", "content": compose_prompt(case, passages)},
                  ], max_tokens=16384)))
    raw = res.content or ""
    spliced, substituted, invalid = splice_references(raw, table)
    stats = {"refs_substituted": substituted, "refs_invalid": invalid,
             "refs_table": len(table)}
    return spliced, res.usage, stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="smoke: first N cases only")
    ap.add_argument("--arms", default="product8,compose8")
    ap.add_argument("--no-retrieval", action="store_true", help="reuse the saved retrieval")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",")]

    cases = load_cases(REPO / "data/golden_cases")
    if args.limit:
        cases = cases[:args.limit]

    # The rerank server must be UP BEFORE build_gate: the probe admits llama-rerank at
    # build time, and a refused provider stays refused for the whole run (found by the
    # 2026-10-15 smoke: 'no eligible provider for rerank' with the server up but probed
    # down). VRAM discipline is preserved: it stops right after the retrieval phase,
    # before any draft dispatch loads the 21GB draft model.
    proc = start_rerank_server()
    gate, _rt, _al = build_gate(OUT_DIR / "trace.sqlite3", ROUTING)
    # The recorded in-memory admission override (2026-08-28 precedent; CR-3 untouched;
    # src/ untouched; every dispatch traces the honest verified=0).
    gate.registry.get("ollama-local").admitted = "full"
    print("[deviation] in-memory admission override for ollama-local (recorded precedent)",
          flush=True)

    retr_path = OUT_DIR / "retrieval.json"
    if args.no_retrieval and retr_path.exists():
        retrieval = json.loads(retr_path.read_text(encoding="utf-8"))
        proc.terminate()
        print("[rerank] server stopped before the draft phase (VRAM discipline)",
              flush=True)
    else:
        try:
            retrieval = retrieve(gate, cases)
        finally:
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

    with sidecar.open("a", encoding="utf-8") as fh:
        for case in cases:
            for arm in arms:
                key = f"{case.id}|{arm}"
                if key in done:
                    continue
                passages = retrieval[case.id]["passages"]
                t_c = time.perf_counter()
                row: dict = {"case_id": case.id, "arm": arm, "date": date.today().isoformat(),
                             "model": MODEL_DRAFT,
                             "ceiling": retrieval[case.id]["ceiling"],
                             "pool_len": retrieval[case.id]["pool_len"]}
                try:
                    if arm == "compose8":
                        content, usage, cstats = compose_arm(gate, case, passages)
                        row |= cstats
                    else:
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
                      f"refs={row.get('refs_substituted')}/{row.get('refs_invalid')} "
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
