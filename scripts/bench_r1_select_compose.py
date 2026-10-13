"""R1 research bench — SELECT-COMPOSE: make verbatim copying the harness's job, not the
model's (the 30B-floor rule: pipeline architecture, never model goodwill).

Mechanism under test: passages are split into numbered sentences [E2.S17]; the model
composes the advice inserting SENTENCE REFERENCES where the exact wording is relied on;
the harness substitutes the verbatim sentence text deterministically. Quote-fidelity is
then 100% BY CONSTRUCTION for every substituted span — what is measured is whether a
30B model selects coherently (reference validity, draft coherence, ca/gs on the final
spliced text) vs the wide20 baseline (ca 0.333 / gs 0.609 / verbatim 69%).

Usage:
  python scripts/bench_r1_select_compose.py --limit 2   # smoke
  python scripts/bench_r1_select_compose.py             # 30 cases x 1 dispatch
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
    sys.path.insert(0, str(REPO))

from harness.gate import LLMRequest  # noqa: E402
from harness.eval.golden_case import load_cases  # noqa: E402
from harness.eval.scorers import score_case  # noqa: E402
from scripts.bench_r1_golden_rag import (  # noqa: E402
    MATTER, quote_verification, retrieve as golden_retrieve)
from scripts.stand_up_opencode import ROUTING, build_gate  # noqa: E402

OUT_DIR = REPO / f"data/eval/R1-SELECTCOMPOSE-{date.today().isoformat()}"
MODEL_DRAFT = "thomson1-chat:latest"
BASELINE = {"ca": 0.333, "gs": 0.609, "qv": 0.69}   # wide20, the arm to beat

SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z“(\[])")

PROMPT = """You are a New Zealand law firm assistant drafting court-ready advice.

You are given LAW EXTRACTS whose sentences are numbered [E1.S1], [E1.S2], ...

STRICT RULES:
- Base every legal proposition ONLY on the extracts. Cite each extract's case or statute
  exactly as written in its header line.
- WHEREVER YOU RELY ON THE EXACT WORDING of an extract, insert that sentence's reference
  token, e.g. [E2.S17], immediately after the point — do NOT rewrite, paraphrase, or
  copy quoted text yourself. The system will splice the exact sentence in for you.
- Never invent a reference that was not shown to you.
- If the extracts lack authority for a point, SAY SO expressly.
- Write as a senior barrister: issues, law applied to the facts, conclusion.

LAW EXTRACTS:
{extracts}

TASK:
{prompt}

Write the full advice now, with [E#.#S#] reference tokens where exact wording matters."""


def sentenceize(passages: list[dict], min_words: int = 6, cap: int = 500) -> tuple[str, dict[str, str]]:
    """Numbered-extract block + ref->verbatim-sentence table."""
    table: dict[str, str] = {}
    blocks = []
    n_sent = 0
    for e, p in enumerate(passages, 1):
        sents = [s.strip() for s in SENT_RE.split(p["text"]) if len(s.split()) >= min_words]
        lines = []
        for s_i, s in enumerate(sents, 1):
            if n_sent >= cap:
                break
            ref = f"[E{e}.S{s_i}]"
            table[ref] = s
            lines.append(f"{ref} {s}")
            n_sent += 1
        if lines:
            blocks.append(f"[Extract {e} | {p['source']}]\n" + "\n".join(lines))
        if n_sent >= cap:
            break
    return "\n\n".join(blocks), table


def splice(draft: str, table: dict[str, str]) -> tuple[str, int, int]:
    """Replace reference tokens with quoted verbatim sentences.
    Returns (spliced, substituted, invalid_refs)."""
    used: dict[str, int] = {}
    invalid = 0

    def rep(m: re.Match) -> str:
        ref = m.group(0)
        if ref in table:
            used[ref] = used.get(ref, 0) + 1
            return f"\"{table[ref]}\""
        nonlocal invalid_flag
        invalid_flag += 1
        return ref
    invalid_flag = 0
    spliced = re.sub(r"\[E\d+\.S\d+\]", rep, draft)
    return spliced, sum(used.values()), invalid_flag


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cases = load_cases(REPO / "data/golden_cases")
    if args.limit:
        cases = cases[:args.limit]

    # reuse the max-RAG retrieval (same wide20 passages — the arm to beat)
    retr_path = REPO / "data/eval/R1-MAXRAG-2026-10-13/retrieval.json"
    if not retr_path.exists():
        raise SystemExit(f"missing {retr_path} — run bench_r1_maxrag.py retrieval first")
    retrieval = json.loads(retr_path.read_text(encoding="utf-8"))

    gate, _rt, _al = build_gate(OUT_DIR / "trace.sqlite3", ROUTING)
    gate.registry.get("ollama-local").admitted = "full"   # recorded 2026-08-28 precedent

    sidecar = OUT_DIR / "sidecar.jsonl"
    done: set[str] = set()
    if sidecar.exists():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["case_id"])

    for case in cases:
        if case.id in done:
            continue
        ps = retrieval[case.id]["wide20"]
        block, table = sentenceize(ps)
        t_c = time.perf_counter()
        row: dict = {"case_id": case.id, "arm": "selectcompose", "stage": "draft1",
                     "date": date.today().isoformat(), "model": MODEL_DRAFT,
                     "ceiling": retrieval[case.id]["ceiling_wide20"],
                     "sentences_offered": len(table)}
        try:
            for _ in range(2):                      # one retry on empty content (S7j lesson)
                res = asyncio.run(gate.dispatch(LLMRequest(
                    matter_ref=MATTER, task_class="research", model=MODEL_DRAFT,
                    messages=[{"role": "user", "content": PROMPT.format(
                        extracts=block, prompt=case.prompt)}], max_tokens=16384)))
                if (res.content or "").strip():
                    break
            content = res.content or ""
            spliced, subbed, invalid = splice(content, table)
            sc = score_case(spliced, case)
            qv, qn = quote_verification(spliced, [p["text"] for p in ps])
            row |= {"status": sc.status, "citation_accuracy": sc.citation_accuracy,
                    "grounding_score": sc.grounding_score, "persona": sc.checks,
                    "passed": sc.passed, "quotes_verified": f"{qv}/{qn}",
                    "refs_valid": subbed, "refs_invalid": invalid,
                    "refs_pct": f"{subbed}/{max(1, subbed + invalid)}",
                    "words": len(spliced.split()), "wall_s": round(time.perf_counter() - t_c, 1),
                    "content": spliced}
        except Exception as ex:                          # noqa: BLE001 — recorded, keep going
            row |= {"status": "error", "error": str(ex)[:400]}
        with sidecar.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  [selectcompose] {case.id}: ca={row.get('citation_accuracy')} "
              f"gs={row.get('grounding_score')} qv={row.get('quotes_verified')} "
              f"refs={row.get('refs_pct')} sentences={len(table)} "
              f"({row.get('wall_s')}s)", flush=True)

    rows = [json.loads(l) for l in sidecar.read_text(encoding="utf-8").splitlines() if l.strip()]
    rs = [r for r in rows if r.get("status") == "scored"]
    if rs:
        n = len(rs)
        ca = sum(r["citation_accuracy"] for r in rs) / n
        gs = sum(r["grounding_score"] for r in rs) / n
        qv = sum(int(r["quotes_verified"].split("/")[0]) for r in rs)
        qn = sum(int(r["quotes_verified"].split("/")[1]) for r in rs)
        inv = sum(r.get("refs_invalid", 0) for r in rs)
        sub = sum(r.get("refs_valid", 0) for r in rs)
        lines = [f"# R1 select-compose — {date.today().isoformat()}", "",
                 f"Baseline to beat (wide20): ca {BASELINE['ca']} gs {BASELINE['gs']} "
                 f"qv {BASELINE['qv']}.", "",
                 f"| n | ca | gs | qv | refs valid/invalid |",
                 f"|---|---|---|---|---|",
                 f"| {n} | {ca:.3f} | {gs:.3f} | {qv}/{qn} ({qv/qn if qn else 0:.0%}) "
                 f"| {sub}/{inv} |"]
        (OUT_DIR / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
        print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
