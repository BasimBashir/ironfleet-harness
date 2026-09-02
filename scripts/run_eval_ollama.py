"""Ollama baseline runner for the S2 golden-case eval.

Runs the production eval path (load_cases -> EgressGate.dispatch -> score_case ->
write_report) against a local Ollama server, with ONE recorded, user-directed deviation.

Why the deviation: the provenance probe admits Ollama as "mechanical-only" (CR-3 — Ollama
does not report the executing backend per request, so provenance is unverifiable), and
routing skips mechanical-only providers for non-mechanical task classes. Every S2 golden
case is task_class "analysis" or "detection", so the honest verdict would route-refuse the
whole baseline. Jonathan directed 2026-08-28 to run the baseline on Ollama "for real
testing for now": the probe verdict is printed honestly and then overridden IN MEMORY ONLY
for this run. CR-3, the probe, and src/ are untouched; every dispatch is still traced with
verified=0.

Usage:
  .venv/Scripts/python.exe scripts/run_eval_ollama.py
  .venv/Scripts/python.exe scripts/run_eval_ollama.py --only gc-ppsa-001-goldcorp

Exit codes: 0 = run completed (individual cases may still fail the rubric or error);
            1 = setup failure (server unreachable, no usable model, no cases matched).

Alongside the report a `<out-stem>.jsonl` sidecar records one line per case (scores, trace
stats, status/error and the raw completion), appended and flushed as each case lands — an
interrupted or chunked run keeps what it finished, and the completions can be re-scored later
without re-running the model.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.eval.golden_case import GoldenCase, load_cases            # noqa: E402
from harness.eval.scorers import CaseScore, score_case, write_report   # noqa: E402
from harness.gate import EgressGate, GateRefusal, LLMRequest           # noqa: E402
from harness.policy import RoutingTable                                # noqa: E402
from harness.providers.config import ProviderRegistry                  # noqa: E402
from harness.providers.http_fetch import openai_fetch                  # noqa: E402
from harness.providers.probe import register_provider                  # noqa: E402
from harness.trace import TraceStore, DispatchRecord                   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data" / "golden_cases"
PROVIDER_NAME = "ollama-local"
DEVIATION = ("DEVIATION (user-directed 2026-08-28, real-testing-only): probe verdict "
             "'mechanical-only' overridden in-memory for this run; CR-3, probe, and src/ "
             "unchanged; every dispatch still traced with verified=0.")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the S2 golden-case baseline against a local Ollama server.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:11434/v1",
                   help="OpenAI-compatible Ollama endpoint (default: %(default)s)")
    p.add_argument("--model", default="", metavar="ID",
                   help="explicit model id (default: auto-detect, preferring the system "
                        "base model thomson1, then qwen)")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="run only the first N cases after filtering (0 = all)")
    p.add_argument("--only", action="append", default=[], metavar="ID-SUBSTR",
                   help="run cases whose id contains this substring (repeatable)")
    p.add_argument("--out", default="data/eval/baseline-ollama.md", metavar="PATH",
                   help="report path (default: %(default)s)")
    return p.parse_args()


async def detect_model(base_url: str) -> str:
    """Like scripts/live_ollama_smoke.py: /models, prefer the system BASE MODEL —
    thomson1 (Thomson-1.0-Small) since 2026-09-02, qwen3.8 before that; never auto-pick a
    model that would be useless or unsafe here: embedding models cannot answer, and a
    cloud-proxied id would let this provider (force-admitted as tier=local, in-memory) egress
    the case prompts to the internet. NOTE thomson1 needs a >=16k output cap (3k+ reasoning
    tokens precede content) — the default cap here is generous enough, but pass --model to
    override if ever needed."""
    payload = await openai_fetch(f"{base_url.rstrip('/')}/models", {})
    if not payload:
        print(f"FAIL: cannot reach {base_url}/models — is Ollama running?")
        sys.exit(1)
    models = [m.get("id", "") for m in payload.get("data", [])]
    print(f"[probe] models on {base_url}: {models}")
    candidates = [m for m in models
                  if not any(bad in m.lower() for bad in ("embed", "bge", "cloud"))]
    preferred = [m for m in candidates if "thomson" in m.lower()]
    if not preferred:
        preferred = [m for m in candidates if "qwen" in m.lower()]
    model = preferred[0] if preferred else (candidates[0] if candidates else "")
    if not model:
        print(f"FAIL: no usable local LLM among {models} — auto-pick excludes ids containing "
              f"embed/bge/cloud and will not guess a cloud or embedding model")
        sys.exit(1)
    return model


def cell(text: object) -> str:
    """Markdown-table safety: a pipe or a newline inside a cell breaks the appendix table
    (error strings come straight from exceptions/providers, so assume nothing about them)."""
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def fail_row(case_id: str, why: str) -> list[str]:
    return [case_id, "-", "-", "-", "-", f"FAILED: {why}", "-", "-"]


def last_trace(trace: TraceStore, matter: str) -> DispatchRecord | None:
    rows = trace.by_matter(matter)
    return rows[-1] if rows else None


def ok_row(case: GoldenCase, sc: CaseScore, tr: DispatchRecord | None) -> list[str]:
    return [case.id, "yes" if sc.passed else "no", f"{sc.citation_accuracy:.2f}",
            f"{sc.grounding_score:.2f}", f"{sum(sc.checks.values())}/{len(sc.checks)}", "ok",
            str(tr.latency_ms) if tr else "-", str(tr.tokens_out) if tr else "-"]


def case_record(case_id: str, *, model: str = "", content: str | None = None,
                sc: CaseScore | None = None, tr: DispatchRecord | None = None,
                error: str = "") -> dict:
    """One re-scorable record per case. The raw completion is kept so scores can be
    recomputed later (e.g. after the S6 citation normaliser) without re-running the model."""
    return {
        "id": case_id,
        "passed": None if sc is None else sc.passed,
        "citation_accuracy": None if sc is None else sc.citation_accuracy,
        "grounding_score": None if sc is None else sc.grounding_score,
        "checks": {} if sc is None else sc.checks,
        "status": "failed" if sc is None else "ok",
        "error": error,
        "latency_ms": None if tr is None else tr.latency_ms,
        "tokens_in": None if tr is None else tr.tokens_in,
        "tokens_out": None if tr is None else tr.tokens_out,
        "model": model,
        "content": content,
    }


async def run(args: argparse.Namespace) -> int:
    model = args.model or await detect_model(args.base_url)
    print(f"[setup] using model: {model}")

    # 1. Register through the REAL probe — the honest verdict, unchanged.
    registry = ProviderRegistry()
    keys: dict[str, str] = {}                      # in-memory keychain: nothing persisted
    res = await register_provider(
        PROVIDER_NAME, args.base_url, "ollama-nokey-needed", model=model, engine="ollama",
        declared={"weights_revision": ""},         # nothing declared: Ollama cannot verify anyway
        registry=registry, keychain_set=keys,
    )
    print(f"[probe] reachable={res.reachable} auth_ok={res.auth_ok} models={res.models}")
    print(f"[probe] provenance.verified={res.provenance.verified} "
          f"backend={res.provenance.backend!r} -> admission={res.admission}")
    if res.admission == "refused":
        print(f"FAIL: probe refused {PROVIDER_NAME}; no baseline is possible against it")
        return 1

    # 2. The single deviation: in-memory config only, recorded loudly.
    honest = registry.get(PROVIDER_NAME).admitted
    print(f"[probe] honest admission recorded: {honest}")
    registry.get(PROVIDER_NAME).admitted = "full"
    print(f"[deviation] {DEVIATION}")

    # 3. Routing: this provider is the only candidate for every classification.
    routing = RoutingTable(rules=[], defaults={
        "local_only": [PROVIDER_NAME],
        "local_preferred": [PROVIDER_NAME],
        "cloud_permitted": [PROVIDER_NAME],
    })

    all_cases = load_cases(CASES_DIR)
    cases = all_cases
    if args.only:
        cases = [c for c in cases if any(s in c.id for s in args.only)]
    if args.limit and args.limit > 0:
        cases = cases[:args.limit]
    if not cases:
        print(f"FAIL: no cases selected from {CASES_DIR} "
              f"({len(all_cases)} available; only={args.only} limit={args.limit})")
        return 1
    print(f"[setup] {len(cases)}/{len(all_cases)} case(s) from {CASES_DIR}")

    # 4. Real TraceStore (TraceStore mkdirs its parent).
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_path = ROOT / "data" / "eval" / f"trace-{stamp}.db"
    gate = EgressGate(registry=registry, routing=routing, trace=TraceStore(db_path))
    print(f"[setup] trace db: {db_path}")

    # 5. Per-case loop (mirrors run_eval) with resilience: a failed case never aborts the run.
    #    The try covers dispatch AND scoring — score_case does plain substring checks, so a
    #    null/absent completion (documented for thinking models) would raise TypeError there;
    #    that must cost one row, not the chunk.
    scores: list[CaseScore] = []
    rows: list[list[str]] = []
    verified_rows = 0
    out_path = Path(args.out)                  # resolved before the loop: sidecar is per-case
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # JSONL sidecar, one line per case, flushed as it lands: scores are not lost with the
    # process, and an interrupted or chunked run keeps every case it already finished.
    sidecar_path = out_path.with_suffix(".jsonl")
    sidecar = sidecar_path.open("a", encoding="utf-8")
    try:
        for case in cases:
            matter = f"eval:{case.id}"
            failure = ""
            try:
                resp = await gate.dispatch(LLMRequest(      # default max_tokens (128k) applies
                    matter_ref=matter, task_class=case.task_class,
                    messages=[{"role": "user", "content": case.prompt}]))
                sc = score_case(resp.content, case)
            except GateRefusal as ex:
                failure = f"dispatch failed (GateRefusal): {ex}"
            except Exception as ex:                         # noqa: BLE001 — record, keep going
                failure = f"dispatch/scoring failed ({type(ex).__name__}): {ex}"

            if failure:
                print(f"[eval ] {case.id}: FAILED {failure}")
                rows.append(fail_row(case.id, failure))
                rec = case_record(case.id, tr=last_trace(gate.trace, matter), error=failure)
            else:
                scores.append(sc)
                oks = [r for r in gate.trace.by_matter(matter) if r.status == "ok"]
                tr = oks[-1] if oks else None
                if tr is not None and tr.verified:
                    verified_rows += 1
                rows.append(ok_row(case, sc, tr))
                rec = case_record(case.id, model=resp.model, content=resp.content, sc=sc, tr=tr)
                print(f"[eval ] {case.id}: {'PASS' if sc.passed else 'FAIL'} "
                      f"citations={sc.citation_accuracy:.2f} grounding={sc.grounding_score:.2f} "
                      f"checks={sum(sc.checks.values())}/{len(sc.checks)} "
                      f"latency_ms={tr.latency_ms if tr else '-'} via {resp.provider}/{resp.model}")
            sidecar.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sidecar.flush()
    finally:
        sidecar.close()

    # 6. Report: production write_report first (standard table stays first), then augment.
    write_report(scores, out_path)
    std = out_path.read_text(encoding="utf-8").splitlines()   # "# Eval report", "", table...
    meta = [f"- provider: {PROVIDER_NAME} ({args.base_url}), engine ollama, model `{model}`",
            f"- probe admission (honest): {honest}; provenance unverifiable -> verified=0",
            f"- cases: {len(scores)} scored, {len(rows) - len(scores)} failed",
            f"- trace db: `{db_path}`",
            f"- generated: {datetime.now().isoformat(timespec='seconds')}"]
    body = std[:1] + ["", DEVIATION, ""] + meta + [""] + std[2:]
    body += ["", "## Per-case appendix", "",
             "| id | passed | citation_accuracy | grounding_score | checks | status "
             "| latency_ms | tokens_out |",
             "|---|---|---|---|---|---|---|---|"]
    body += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    summary = gate.trace.summary()
    body += ["", "## Trace summary", "",
             f"- dispatches: {summary['dispatches']}, traced errors: {summary['errors']}, "
             f"by_engine: {summary['by_engine']}",
             f"- dispatches with verified=1: {verified_rows} (expected 0 for Ollama)"]
    out_path.write_text("\n".join(body), encoding="utf-8")

    # 7. Summary.
    n_pass = sum(1 for s in scores if s.passed)
    n_fail = len(scores) - n_pass
    n_err = len(rows) - len(scores)
    print()
    print(DEVIATION)
    print(f"SUMMARY: {n_pass} passed / {n_fail} failed / {n_err} dispatch-errors "
          f"of {len(cases)} cases")
    print(f"REPORT : {out_path}")
    print(f"SCORES : {sidecar_path} (one JSON line per case, incl. raw completion)")
    print(f"TRACE  : {summary}; verified=1 rows: {verified_rows}")
    return 0


def main() -> None:
    # A local baseline can run for hours per case; progress lines must survive redirection.
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
