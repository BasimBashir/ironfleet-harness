"""In-house HUNTER persona reference run for the S4 spike (SPIKE_PROTOCOL criterion (b)).

The 2026-09-01 baseline (data/eval/BASELINE-OLLAMA-2026-09-01.md) measured the BARE model
on the 30 golden cases — no persona mounted. Persona parity needs the "in-house HUNTER"
side of the comparison on the same model: this script dispatches each case with the spike
persona (PERSONA_PORT["system_prompt"], verbatim) as the system message through the SAME
production eval path (load_cases -> EgressGate.dispatch -> score_case -> write_report).

Deviations vs the baseline run (agent-recorded 2026-09-01, background S4 session —
full trail in the spike report):
1. PARITY SUBSET: one case per matter cluster (first by id within the cluster), 5 cases.
   The baseline ran ~35 min/case (~4.3 tok/s on the RTX 3090); 30-case reruns across three
   parity runs (in-house + 2 candidates) would be 30-90 h wall. The full 30 stay covered
   by the committed baseline; --all restores them here if ever needed.
2. max_tokens capped at 8192 by default (baseline used the 128k gate default): the SAME
   cap is configured on every candidate parity run, so both sides of every comparison
   share conditions; absolute numbers are NOT directly comparable to the 128k baseline.

The baseline's recorded in-memory admission override applies here too (same reason: CR-3
says Ollama is mechanical-only; Jonathan's real-testing direction of 2026-08-28; probe,
CR-3 and src/ untouched; every dispatch traced verified=0).

Usage:
  .venv/Scripts/python.exe scripts/run_eval_persona_ollama.py
  .venv/Scripts/python.exe scripts/run_eval_persona_ollama.py --only gc-ppsa-001
  .venv/Scripts/python.exe scripts/run_eval_persona_ollama.py --all

Exit codes: 0 = run completed (cases may still fail the rubric); 1 = setup failure.
Sidecar: `<out-stem>.jsonl`, one re-scorable record per case (same schema as the baseline
sidecars, `persona` noted in `model`-adjacent fields), appended per case like the baseline.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
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
from harness.providers.probe import register_provider                  # noqa: E402
from harness.spike.persona_port import PERSONA_PORT                    # noqa: E402
from harness.trace import TraceStore                                   # noqa: E402

# Reuse the baseline runner's tested helpers (detect_model, sidecar/report plumbing) —
# it is a committed artifact, so this script imports rather than edits it.
_SPEC = importlib.util.spec_from_file_location(
    "run_eval_ollama", Path(__file__).resolve().parent / "run_eval_ollama.py")
_base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_base)

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "data" / "golden_cases"
PROVIDER_NAME = "ollama-local"
DEVIATION = ("DEVIATION (spike parity run, agent-recorded 2026-09-01): baseline's in-memory "
             "admission override inherited (CR-3 unchanged, verified=0 traced); parity subset "
             "5 cases (one per matter cluster, first by id); max_tokens capped 8192 — same cap "
             "on every candidate run; see the S4 spike report for the full trail.")


def select_parity_subset(cases: list[GoldenCase]) -> list[GoldenCase]:
    """One case per matter cluster — the first by id within each cluster, output sorted by id.
    Deterministic so all three parity runs (in-house, OpenCode, OpenHands) see identical prompts."""
    first: dict[str, GoldenCase] = {}
    for case in sorted(cases, key=lambda c: c.id):     # key off the ID, not glob/filename order
        first.setdefault(case.matter_type, case)
    return sorted(first.values(), key=lambda c: c.id)


def build_messages(case: GoldenCase) -> list[dict]:
    """[system: HUNTER persona verbatim] + [user: case prompt] — the in-house mount whose
    candidate-side equivalent is the hunter subagent (persona_port.PERSONA_PORT["configs"])."""
    return [{"role": "system", "content": PERSONA_PORT["system_prompt"]},
            {"role": "user", "content": case.prompt}]


async def build_reference_gate(base_url: str, model: str,
                               db_path: Path) -> tuple["EgressGate | None", str]:
    """The in-house HUNTER reference dispatch point: real probe -> honest verdict printed ->
    the recorded in-memory admission override -> routing that makes this provider the only
    candidate for EVERY task class (defaults, not rules — the golden cases span `analysis` and
    `detection`, and a rules-only table with no `detection` row would refuse one case).

    Extracted 2026-10-01 (S7c Task 13) so the acceptance driver can drive the reference
    dispatch PER CASE — interleaved with the mount side, so a crash costs one case-pair, not
    one side of thirty — instead of this script's whole-loop CLI run. run() calls this, so the
    setup has exactly one definition and the two callers cannot drift."""
    registry = ProviderRegistry()
    keys: dict[str, str] = {}
    res = await register_provider(
        PROVIDER_NAME, base_url, "ollama-nokey-needed", model=model, engine="ollama",
        declared={"weights_revision": ""}, registry=registry, keychain_set=keys,
    )
    print(f"[probe] reachable={res.reachable} auth_ok={res.auth_ok} "
          f"provenance.verified={res.provenance.verified} -> admission={res.admission}")
    if res.admission == "refused":
        return None, ""
    honest = registry.get(PROVIDER_NAME).admitted
    registry.get(PROVIDER_NAME).admitted = "full"
    routing = RoutingTable(rules=[], defaults={
        "local_only": [PROVIDER_NAME], "local_preferred": [PROVIDER_NAME],
        "cloud_permitted": [PROVIDER_NAME]})
    gate = EgressGate(registry=registry, routing=routing, trace=TraceStore(db_path))
    return gate, honest


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the in-house HUNTER persona reference eval against local Ollama.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--base-url", default="http://127.0.0.1:11434/v1",
                   help="OpenAI-compatible Ollama endpoint (default: %(default)s)")
    p.add_argument("--model", default="", metavar="ID",
                   help="explicit model id (default: auto-detect, preferring qwen — "
                        "used for the legal-model comparison runs)")
    p.add_argument("--max-tokens", type=int, default=8192, metavar="N",
                   help="output cap, identical on every parity run (default: %(default)s)")
    p.add_argument("--all", action="store_true",
                   help="run all cases, not just the parity subset")
    p.add_argument("--only", action="append", default=[], metavar="ID-SUBSTR",
                   help="run cases whose id contains this substring (repeatable)")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="run only the first N cases after filtering (0 = all)")
    p.add_argument("--out", default="data/eval/spike-persona-ref-ollama.md", metavar="PATH",
                   help="report path (default: %(default)s)")
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    model = args.model or await _base.detect_model(args.base_url)
    print(f"[setup] using model: {model}")

    # 1-2. Real probe, then the inherited recorded override (verbatim pattern from the baseline).
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_path = ROOT / "data" / "eval" / f"trace-{stamp}.db"
    gate, honest = await build_reference_gate(args.base_url, model, db_path)
    if gate is None:
        print(f"FAIL: probe refused {PROVIDER_NAME}")
        return 1
    print(f"[deviation] {DEVIATION}")

    all_cases = load_cases(CASES_DIR)
    cases = all_cases if args.all else select_parity_subset(all_cases)
    if args.only:
        cases = [c for c in cases if any(s in c.id for s in args.only)]
    if args.limit and args.limit > 0:
        cases = cases[:args.limit]
    if not cases:
        print(f"FAIL: no cases selected from {CASES_DIR} "
              f"({len(all_cases)} available; only={args.only} limit={args.limit})")
        return 1
    print(f"[setup] {len(cases)}/{len(all_cases)} case(s) from {CASES_DIR}")

    print(f"[setup] trace db: {db_path}")

    scores: list[CaseScore] = []
    rows: list[list[str]] = []
    verified_rows = 0
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path = out_path.with_suffix(".jsonl")
    sidecar = sidecar_path.open("a", encoding="utf-8")
    try:
        for case in cases:
            matter = f"spike-persona:{case.id}"
            failure = ""
            try:
                resp = await gate.dispatch(LLMRequest(
                    matter_ref=matter, task_class=case.task_class, max_tokens=args.max_tokens,
                    messages=build_messages(case)))
                sc = score_case(resp.content, case)
            except GateRefusal as ex:
                failure = f"dispatch failed (GateRefusal): {ex}"
            except Exception as ex:                         # noqa: BLE001 — record, keep going
                failure = f"dispatch/scoring failed ({type(ex).__name__}): {ex}"

            if failure:
                print(f"[eval ] {case.id}: FAILED {failure}")
                rows.append(_base.fail_row(case.id, failure))
                rec = _base.case_record(case.id, tr=_base.last_trace(gate.trace, matter),
                                        error=failure)
            else:
                scores.append(sc)
                oks = [r for r in gate.trace.by_matter(matter) if r.status == "ok"]
                tr = oks[-1] if oks else None
                if tr is not None and tr.verified:
                    verified_rows += 1
                rows.append(_base.ok_row(case, sc, tr))
                rec = _base.case_record(case.id, model=resp.model, content=resp.content,
                                        sc=sc, tr=tr)
                print(f"[eval ] {case.id}: {'PASS' if sc.passed else 'FAIL'} "
                      f"citations={sc.citation_accuracy:.2f} grounding={sc.grounding_score:.2f} "
                      f"checks={sum(sc.checks.values())}/{len(sc.checks)} "
                      f"latency_ms={tr.latency_ms if tr else '-'} via {resp.provider}/{resp.model}")
            sidecar.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sidecar.flush()
    finally:
        sidecar.close()

    write_report(scores, out_path)
    std = out_path.read_text(encoding="utf-8").splitlines()
    meta = [f"- provider: {PROVIDER_NAME} ({args.base_url}), engine ollama, model `{model}`",
            f"- persona: `PERSONA_PORT[system_prompt]` verbatim as system message "
            f"(src/harness/spike/persona_port.py)",
            f"- max_tokens: {args.max_tokens} (identical cap on every spike parity run)",
            f"- cases: {len(scores)} scored, {len(rows) - len(scores)} failed "
            f"(parity subset: one per matter cluster, first by id)",
            f"- probe admission (honest): {honest}; provenance unverifiable -> verified=0",
            f"- trace db: `{db_path}`",
            f"- generated: {datetime.now().isoformat(timespec='seconds')}"]
    body = std[:1] + ["", DEVIATION, ""] + meta + [""] + std[2:]
    body += ["", "## Per-case appendix", "",
             "| id | passed | citation_accuracy | grounding_score | checks | status "
             "| latency_ms | tokens_out |",
             "|---|---|---|---|---|---|---|---|"]
    body += ["| " + " | ".join(_base.cell(c) for c in r) + " |" for r in rows]
    summary = gate.trace.summary()
    body += ["", "## Trace summary", "",
             f"- dispatches: {summary['dispatches']}, traced errors: {summary['errors']}, "
             f"by_engine: {summary['by_engine']}",
             f"- dispatches with verified=1: {verified_rows} (expected 0 for Ollama)"]
    out_path.write_text("\n".join(body), encoding="utf-8")

    n_pass = sum(1 for s in scores if s.passed)
    print()
    print(DEVIATION)
    print(f"SUMMARY: {n_pass} passed / {len(scores) - n_pass} failed / "
          f"{len(rows) - len(scores)} dispatch-errors of {len(cases)} cases")
    print(f"REPORT : {out_path}")
    print(f"SCORES : {sidecar_path}")
    return 0


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)      # hours-long runs must survive redirection
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
