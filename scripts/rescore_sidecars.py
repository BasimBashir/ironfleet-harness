"""Re-score committed eval sidecars with the current scorer — no model re-run.

The S2 baseline (and later runs) commit `<out-stem>.jsonl` sidecars carrying each
case's raw completion precisely so scoring changes can be re-applied offline
(S6-5 citation normaliser is the first consumer). This script joins every sidecar
line back to its golden case by id, re-scores citations AND grounding with the
current scorers, and writes a comparison report. Grounding is expected to be
unchanged by the normaliser — the report says so with numbers, not assumption.

Usage:
    python scripts/rescore_sidecars.py [--sidecars GLOB] [--cases DIR] [--out FILE]

Defaults re-score the committed 2026-09-01 Ollama baseline chunks (2..6; chunk 1
has no sidecar — it ran pre-hardening; see BASELINE-OLLAMA-2026-09-01.md).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from harness.eval.golden_case import load_cases
from harness.eval.scorers import citation_accuracy, grounding_score

ROOT = Path(__file__).resolve().parents[1]


def rescore(records: list[dict], cases: dict) -> list[dict]:
    """One output record per input record: new_* scores where the raw completion
    exists and the case is known; None otherwise (skipped, never guessed)."""
    out = []
    for rec in records:
        case = cases.get(rec.get("id"))
        content = rec.get("content")
        if case is None or content is None:
            out.append({**rec, "new_citation_accuracy": None, "new_grounding_score": None})
            continue
        out.append({**rec,
                    "new_citation_accuracy": citation_accuracy(content, case.expected_citations),
                    "new_grounding_score": grounding_score(content, case.required_grounding)})
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sidecars", nargs="*", type=Path, default=None,
                    help="sidecar .jsonl files (default: committed baseline chunks 2..6)")
    ap.add_argument("--cases", type=Path, default=ROOT / "data" / "golden_cases")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data" / "eval" / "BASELINE-RESCORE-S6-2026-09-03.md")
    args = ap.parse_args()
    sidecars = args.sidecars or sorted(
        (ROOT / "data" / "eval").glob("baseline-ollama-chunk-*.jsonl"))

    cases = {c.id: c for c in load_cases(args.cases)}
    lines = ["# Baseline re-score — S6 citation normaliser (no model re-run)", "",
             f"- generated: {datetime.now().isoformat(timespec='seconds')}",
             f"- scorer: `citation_accuracy` with S6-5 variants (see `src/harness/eval/scorers.py`)",
             f"- sidecars: {len(sidecars)} file(s); cases dir: `{args.cases}`",
             "- chunk 1 of the baseline has no sidecar (ran pre-hardening) — its 5 cases stay on"
             " the as-run scores", "",
             "| id | old citations | new citations | old grounding | new grounding |",
             "|---|---|---|---|---|"]
    old_c: list[float] = []
    new_c: list[float] = []
    old_g: list[float] = []
    new_g: list[float] = []
    n_skipped = 0
    for path in sidecars:
        for rec in rescore([json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()],
                           cases):
            if rec["new_citation_accuracy"] is None:
                n_skipped += 1
                lines.append(f"| {rec.get('id')} | {rec.get('citation_accuracy')} | skipped"
                             f" | {rec.get('grounding_score')} | skipped |")
                continue
            for acc, val in ((old_c, rec["citation_accuracy"]), (new_c, rec["new_citation_accuracy"]),
                             (old_g, rec["grounding_score"]), (new_g, rec["new_grounding_score"])):
                acc.append(val if val is not None else 0.0)
            lines.append(f"| {rec['id']} | {rec['citation_accuracy']:.2f} | {rec['new_citation_accuracy']:.2f}"
                         f" | {rec['grounding_score']:.2f} | {rec['new_grounding_score']:.2f} |")
    lines += ["", f"- re-scored: {len(new_c)} cases ({n_skipped} skipped — no sidecar content or"
                  f" unknown id)",
              f"- mean citation_accuracy: **{_mean(old_c):.3f} -> {_mean(new_c):.3f}**",
              f"- mean grounding_score: {_mean(old_g):.3f} -> {_mean(new_g):.3f}"
              f" (expected unchanged — the normaliser touches citations only)"]
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"re-scored {len(new_c)} cases ({n_skipped} skipped); "
          f"citations {_mean(old_c):.3f} -> {_mean(new_c):.3f}; "
          f"grounding {_mean(old_g):.3f} -> {_mean(new_g):.3f}")
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
