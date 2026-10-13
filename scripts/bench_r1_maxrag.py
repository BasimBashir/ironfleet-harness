"""R1 evidence gate — is the CURRENT harness extracting the MAX of the RAG? (user-directed
2026-10-13: prove max utilization BEFORE any web research; threshold 95% on accuracy /
grounding / quotation; prototype the argue-and-revise loop with per-stage quality deltas.)

Arms (30 golden cases, thomson1-chat through gate.dispatch, production scorers):
  wide20    — top-20 chunks by chunk-level hybrid+rerank (~4x the golden test's context)
  fulldoc3  — the top-3 WHOLE documents (doc-level hybrid+rerank; 262k ctx makes this cheap)
  iter2     — wide20 passages; draft1 -> critic agent attacks it -> reviser re-drafts;
              every stage scored, deltas recorded, critique kept as "what to improve next"

Strict no-memory citation rule on every arm: the model must cite ONLY what the extracts
contain and must say so expressly when they lack authority — measured citation_accuracy
becomes honest (memory-cited needles score 0, as they should).

Usage:
  python scripts/bench_r1_maxrag.py --limit 2     # smoke
  python scripts/bench_r1_maxrag.py               # full (hours; resumable per case|arm|stage)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))   # scripts.* imports (stand_up_opencode.py lesson)

from harness.gate import EmbeddingRequest, LLMRequest  # noqa: E402
from harness.eval.golden_case import load_cases  # noqa: E402
from harness.eval.scorers import citation_hit, score_case  # noqa: E402
from harness.vectors import VectorStore  # noqa: E402
from scripts.bench_r1_golden_rag import (  # noqa: E402
    MATTER, SMOKE_STORES, load_real_chunks, quote_verification,
    rerank_docs, sqlite3_connect_lexicon, start_rerank_server)
from scripts.bench_r1_ingest import rrf  # noqa: E402
from scripts.stand_up_opencode import ROUTING, build_gate  # noqa: E402

OUT_DIR = REPO / f"data/eval/R1-MAXRAG-{date.today().isoformat()}"
MODEL_DRAFT = "thomson1-chat:latest"
THRESHOLD = 0.95
BASELINE = {"ca": 0.117, "gs": 0.367}          # A7 no-corpus
GOLDEN = {"ca": 0.233, "gs": 0.450, "qv": 0.658}  # yesterday's best arm, for delta rows

RULES = """STRICT RULES:
- Use ONLY the law extracts provided here as sources. Do NOT cite any authority from
  your own knowledge; if the extracts do not contain authority for a point, SAY SO
  expressly instead of citing.
- When you state a legal proposition taken from an extract, cite that extract's case or
  statute exactly as written in its header line.
- Any direct quotation MUST be copied word-for-word from an extract.
- Write as a senior barrister: court-ready structure (issues, law applied to the facts,
  conclusion), precise prose, no hedging filler."""

DRAFT_TMPL = RULES + """

LAW EXTRACTS:
{extracts}

TASK:
{prompt}"""

CRITIC_TMPL = """You are a merciless senior partner reviewing a junior's draft advice for
filing. Attack it. The LAW EXTRACTS are the ONLY permitted sources.

LAW EXTRACTS:
{extracts}

TASK:
{prompt}

DRAFT UNDER REVIEW:
{draft}

Produce a NUMBERED list of concrete defects, each one sentence:
1. every citation in the draft that does NOT appear word-for-word in the extracts (name it);
2. every quotation that is not word-for-word from an extract (name it);
3. every legal element the TASK requires that the draft fails to address;
4. structural, tonal, or precision defects for a court-ready advice (be specific).
Do not rewrite the draft. Number every defect. If a category is clean, write 'clean'."""

REVISE_TMPL = RULES + """

LAW EXTRACTS:
{extracts}

TASK:
{prompt}

YOUR EARLIER DRAFT:
{draft}

THE SENIOR PARTNER'S DEFECT LIST:
{critique}

Produce the corrected FULL draft. Apply every defect that the extracts' contents allow;
where a defect cannot be fixed from the extracts, comply with the STRICT RULES instead.
Output only the final draft."""


def extracts_block(passages: list[dict]) -> str:
    return "\n\n".join(f"[Extract {n + 1} | {p['source']}]\n{p['text']}"
                       for n, p in enumerate(passages))


def retrieve(gate, cases) -> dict:
    """case_id -> {"wide20": [...], "doc3": [full docs], ceilings}."""
    from scripts.bench_r1_golden_rag import MATTER_REAL, bm25_chunk_rowids
    docs, texts, rowid_to_idx = load_real_chunks()
    by_text = {t: i for i, t in enumerate(texts)}
    lex = sqlite3_connect_lexicon()
    store = VectorStore(SMOKE_STORES / "vectors.sqlite3")
    out: dict = {}
    for case in cases:
        q = case.prompt[:1200]
        emb = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=MATTER, texts=[q])))
        # chunk-level hybrid -> rerank -> top-20
        lex_chunks = [rowid_to_idx[r] for r in bm25_chunk_rowids(lex, q, 30)
                      if r in rowid_to_idx]
        vec_chunks = [by_text[h.text] for h in store.search(MATTER_REAL, emb.vectors[0], k=30)
                      if h.text in by_text]
        fused = rrf([lex_chunks, vec_chunks])
        order = rerank_docs(q, [texts[i][:4000] for i in fused[:40]])
        top20 = [fused[i] for i in order[:20]]
        # doc ranking: first-appearance order of docs in the chunk fusion (cheap, honest)
        doc_seq: list[str] = []
        for i in fused:
            d = docs[i]
            if d not in doc_seq:
                doc_seq.append(d)
        blob20 = "\n".join(texts[i] for i in top20)
        ceil = sum(1 for n in case.expected_citations if citation_hit(blob20, n))
        full = []
        WORD_CAP = 80_000                      # recorded deviation: practical ctx cap
        used = 0
        for d in doc_seq[:3]:
            body = "\n\n".join(texts[i] for i, dd in enumerate(docs) if dd == d)
            if used + len(body.split()) > WORD_CAP:
                body = " ".join(body.split()[:max(0, WORD_CAP - used)])
            used += len(body.split())
            full.append({"source": d.removeprefix("real-"), "text": body})
            if used >= WORD_CAP:
                break
        out[case.id] = {
            "wide20": [{"source": docs[i].removeprefix("real-"), "text": texts[i]}
                       for i in top20],
            "doc3": full,
            "ceiling_wide20": f"{ceil}/{len(case.expected_citations)}",
            "words_wide20": sum(len(texts[i].split()) for i in top20),
            "words_doc3": sum(len(f["text"].split()) for f in full),
        }
        print(f"  [retrieve] {case.id}: ceiling20 {out[case.id]['ceiling_wide20']} "
              f"words20 {out[case.id]['words_wide20']} words_doc3 {out[case.id]['words_doc3']}",
              flush=True)
    return out


async def dispatch(gate, prompt: str) -> tuple[str, dict]:
    # thomson1 can burn the whole output cap into reasoning and return empty content
    # (S7j-W live finding) — retry once; record the attempt count via usage reuse.
    content, usage = "", {}
    for attempt in range(2):
        res = await gate.dispatch(LLMRequest(
            matter_ref=MATTER, task_class="research", model=MODEL_DRAFT,
            messages=[{"role": "user", "content": prompt}], max_tokens=16384))
        usage = res.usage
        content = res.content or ""
        if content.strip():
            return content, usage
    return content, usage


def score_row(case, content: str, passages: list[dict], stage: str, t_c: float,
              usage: dict, extra: dict | None = None) -> dict:
    sc = score_case(content, case)
    qv, qn = quote_verification(content, [p["text"] for p in passages])
    row = {"date": date.today().isoformat(), "model": MODEL_DRAFT, "stage": stage,
           "status": sc.status, "citation_accuracy": sc.citation_accuracy,
           "grounding_score": sc.grounding_score, "persona": sc.checks,
           "passed": sc.passed, "quotes_verified": f"{qv}/{qn}",
           "words": len(content.split()), "tokens_in": sum(usage.values()),
           "wall_s": round(time.perf_counter() - t_c, 1), "content": content}
    if extra:
        row |= extra
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--arms", default="wide20,fulldoc3,iter2")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",")]

    cases = load_cases(REPO / "data/golden_cases")
    if args.limit:
        cases = cases[:args.limit]

    gate, _rt, _al = build_gate(OUT_DIR / "trace.sqlite3", ROUTING)
    gate.registry.get("ollama-local").admitted = "full"   # recorded 2026-08-28 precedent
    print("[deviation] in-memory admission override for ollama-local (recorded precedent)",
          flush=True)

    retr_path = OUT_DIR / "retrieval.json"
    if retr_path.exists():
        retrieval = json.loads(retr_path.read_text(encoding="utf-8"))
    else:
        proc = start_rerank_server()
        try:
            retrieval = retrieve(gate, cases)
        finally:
            proc.terminate()
            print("[rerank] server stopped before drafting (VRAM discipline)", flush=True)
        retr_path.write_text(json.dumps(retrieval, indent=1), encoding="utf-8")

    sidecar = OUT_DIR / "sidecar.jsonl"
    done: set[str] = set()
    if sidecar.exists():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add(f"{r['case_id']}|{r['arm']}|{r['stage']}")

    def emit(row: dict) -> None:
        with sidecar.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        done.add(f"{row['case_id']}|{row['arm']}|{row['stage']}")
        print(f"  [{row['arm']}|{row['stage']}] {row['case_id']}: "
              f"ca={row.get('citation_accuracy')} gs={row.get('grounding_score')} "
              f"qv={row.get('quotes_verified')} words={row.get('words')} "
              f"({row.get('wall_s')}s)", flush=True)

    for case in cases:
        # ---------- wide20
        if "wide20" in arms and f"{case.id}|wide20|draft1" not in done:
            ps = retrieval[case.id]["wide20"]
            t_c = time.perf_counter()
            try:
                content, usage = asyncio.run(dispatch(
                    gate, DRAFT_TMPL.format(extracts=extracts_block(ps), prompt=case.prompt)))
                row = {"case_id": case.id, "arm": "wide20",
                       "ceiling": retrieval[case.id]["ceiling_wide20"]}
                row |= score_row(case, content, ps, "draft1", t_c, usage)
            except Exception as ex:                        # noqa: BLE001 — recorded
                row = {"case_id": case.id, "arm": "wide20", "stage": "draft1",
                       "status": "error", "error": str(ex)[:400]}
            emit(row)

        # ---------- fulldoc3
        if "fulldoc3" in arms and f"{case.id}|fulldoc3|draft1" not in done:
            ps = retrieval[case.id]["doc3"]
            t_c = time.perf_counter()
            try:
                content, usage = asyncio.run(dispatch(
                    gate, DRAFT_TMPL.format(extracts=extracts_block(ps), prompt=case.prompt)))
                row = {"case_id": case.id, "arm": "fulldoc3",
                       "ceiling": retrieval[case.id]["ceiling_wide20"]}
                row |= score_row(case, content, ps, "draft1", t_c, usage)
            except Exception as ex:                        # noqa: BLE001
                row = {"case_id": case.id, "arm": "fulldoc3", "stage": "draft1",
                       "status": "error", "error": str(ex)[:400]}
            emit(row)

        # ---------- iter2 (reuses wide20 draft1 when present)
        if "iter2" in arms:
            d1_key = f"{case.id}|iter2|draft1"
            if d1_key in done:
                d1 = next(json.loads(l) for l in sidecar.read_text(encoding="utf-8").splitlines()
                          if f'"{case.id}"' in l and '"iter2"' in l and '"draft1"' in l)
            elif f"{case.id}|wide20|draft1" in done:
                d1 = next(json.loads(l) for l in sidecar.read_text(encoding="utf-8").splitlines()
                          if f'"{case.id}"' in l and '"wide20"' in l and '"draft1"' in l)
                d1["arm"] = "iter2"
                emit(d1)
            else:
                d1 = None
            ps = retrieval[case.id]["wide20"]
            if d1 is None and d1_key not in done:
                t_c = time.perf_counter()
                try:
                    content, usage = asyncio.run(dispatch(
                        gate, DRAFT_TMPL.format(extracts=extracts_block(ps),
                                                prompt=case.prompt)))
                    d1 = {"case_id": case.id, "arm": "iter2",
                          "ceiling": retrieval[case.id]["ceiling_wide20"]}
                    d1 |= score_row(case, content, ps, "draft1", t_c, usage)
                except Exception as ex:                    # noqa: BLE001
                    d1 = {"case_id": case.id, "arm": "iter2", "stage": "draft1",
                          "status": "error", "error": str(ex)[:400]}
                emit(d1)
            if d1.get("status") == "scored" and f"{case.id}|iter2|critique" not in done:
                t_c = time.perf_counter()
                try:
                    critique, usage = asyncio.run(dispatch(
                        gate, CRITIC_TMPL.format(extracts=extracts_block(ps),
                                                 prompt=case.prompt, draft=d1["content"])))
                    row = {"case_id": case.id, "arm": "iter2",
                           "ceiling": retrieval[case.id]["ceiling_wide20"], "stage": "critique",
                           "critique": critique, "tokens_in": sum(usage.values()),
                           "wall_s": round(time.perf_counter() - t_c, 1), "status": "critique"}
                except Exception as ex:                    # noqa: BLE001
                    row = {"case_id": case.id, "arm": "iter2", "stage": "critique",
                           "status": "error", "error": str(ex)[:400]}
                emit(row)
            if (d1.get("status") == "scored" and f"{case.id}|iter2|critique" in done
                    and f"{case.id}|iter2|draft2" not in done):
                crit = next(json.loads(l) for l in sidecar.read_text(encoding="utf-8").splitlines()
                            if f'"{case.id}"' in l and '"iter2"' in l and '"critique"' in l)
                t_c = time.perf_counter()
                try:
                    content, usage = asyncio.run(dispatch(
                        gate, REVISE_TMPL.format(extracts=extracts_block(ps),
                                                 prompt=case.prompt, draft=d1["content"],
                                                 critique=crit.get("critique", ""))))
                    row = {"case_id": case.id, "arm": "iter2",
                           "ceiling": retrieval[case.id]["ceiling_wide20"]}
                    row |= score_row(case, content, ps, "draft2", t_c, usage,
                                     extra={"delta_ca": round(
                                         row_ca(content, case) - d1["citation_accuracy"], 3)})
                except Exception as ex:                    # noqa: BLE001
                    row = {"case_id": case.id, "arm": "iter2", "stage": "draft2",
                           "status": "error", "error": str(ex)[:400]}
                emit(row)

    summarize(sidecar, cases)


def row_ca(content: str, case) -> float:
    from harness.eval.scorers import citation_accuracy
    return citation_accuracy(content, case.expected_citations)


def summarize(sidecar: Path, cases) -> None:
    rows = [json.loads(l) for l in sidecar.read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = [f"# R1 max-utilization evidence — {date.today().isoformat()}", "",
             f"Model {MODEL_DRAFT}; threshold {THRESHOLD} per axis; "
             f"baseline no-corpus ca {BASELINE['ca']} gs {BASELINE['gs']}; "
             f"golden-test best ca {GOLDEN['ca']} gs {GOLDEN['gs']} qv {GOLDEN['qv']}.", "",
             "| arm/stage | n | citation_accuracy | grounding | quote-verification | passed | words(mean) |",
             "|---|---|---|---|---|---|---|"]
    for arm, stage in (("wide20", "draft1"), ("fulldoc3", "draft1"),
                       ("iter2", "draft1"), ("iter2", "draft2")):
        rs = [r for r in rows if r.get("arm") == arm and r.get("stage") == stage
              and r.get("status") == "scored"]
        if not rs:
            continue
        ca = sum(r["citation_accuracy"] for r in rs) / len(rs)
        gs = sum(r["grounding_score"] for r in rs) / len(rs)
        qv = sum(int(r["quotes_verified"].split("/")[0]) for r in rs)
        qn = sum(int(r["quotes_verified"].split("/")[1]) for r in rs)
        w = sum(r["words"] for r in rs) // len(rs)
        np_ = sum(1 for r in rs if r["passed"])
        lines.append(f"| {arm}/{stage} | {len(rs)} | {ca:.3f} | {gs:.3f} "
                     f"| {qv}/{qn} ({(qv / qn if qn else 0):.0%}) | {np_}/{len(rs)} | {w} |")
    it = [r for r in rows if r.get("arm") == "iter2" and r.get("stage") == "draft2"
          and r.get("status") == "scored"]
    if it:
        d1 = {r["case_id"]: r for r in rows if r.get("arm") == "iter2"
              and r.get("stage") == "draft1" and r.get("status") == "scored"}
        up = sum(1 for r in it if r.get("delta_ca", 0) > 0)
        down = sum(1 for r in it if r.get("delta_ca", 0) < 0)
        same = sum(1 for r in it if r.get("delta_ca", 0) == 0)
        lines += ["", f"## iter2 revision deltas (draft1 -> draft2): improved {up}, "
                      f"worsened {down}, same {same}, of {len(it)}"]
    errs = [r for r in rows if r.get("status") == "error"]
    if errs:
        lines += ["", "## Errors", ""] + \
                 [f"- {r['case_id']}|{r['arm']}|{r['stage']}: {r.get('error', '')[:160]}"
                  for r in errs]
    (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
