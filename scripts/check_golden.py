# scripts/check_golden.py
"""S2 golden-case checker: manifest integrity + reference-answer satisfiability.

Verifies, for every manifest entry (optionally one cluster):
  1. every source file exists and its sha256 matches the manifest;
  2. a golden-case YAML and a reference answer exist for the id;
  3. the reference answer scores .passed with the production scorer;
  4. no gc-* YAML exists without a manifest entry.
Seed cases (seed-*) are ignored: they retire once this set is approved.
"""
from __future__ import annotations
import argparse
import hashlib
import sys
from pathlib import Path
import yaml

from harness.eval.golden_case import load_cases
from harness.eval.scorers import score_case

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "data" / "golden_cases"

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(cases_dir: Path, cluster: str | None = None) -> list[str]:
    cases_dir = Path(cases_dir)
    doc = yaml.safe_load((cases_dir / "sources" / "MANIFEST.yaml").read_text(encoding="utf-8"))
    all_manifest_ids = {e["id"] for e in doc["manifest"]}
    entries = [e for e in doc["manifest"] if cluster is None or e["cluster"] == cluster]
    if cluster is not None and not entries:
        return [f"cluster '{cluster}' matches no manifest entries"]
    cases = {c.id: c for c in load_cases(cases_dir) if c.id.startswith("gc-")}
    refs = {p.stem: p for p in (cases_dir / "references").glob("*.md")}
    problems: list[str] = []
    for e in entries:
        cid = e["id"]
        if len(e["sources"]) != len(e["sha256_per_source"]):
            problems.append(f"{cid}: sources/sha256_per_source length mismatch")
        else:
            for fname, declared in zip(e["sources"], e["sha256_per_source"]):
                src = cases_dir / "sources" / "Set_2" / fname
                if not src.exists():
                    problems.append(f"{cid}: missing source {fname}")
                elif _sha256(src) != declared:
                    problems.append(f"{cid}: sha256 mismatch {fname}")
        if cid not in cases:
            problems.append(f"{cid}: no golden-case YAML")
        elif cid not in refs:
            problems.append(f"{cid}: no reference answer")
        else:
            s = score_case(refs[cid].read_text(encoding="utf-8"), cases[cid])
            if not s.passed:
                problems.append(f"{cid}: reference answer fails "
                                f"(citations={s.citation_accuracy:.2f} grounding={s.grounding_score:.2f} checks={s.checks})")
    for cid in cases:
        if cid not in all_manifest_ids:
            problems.append(f"{cid}: YAML without manifest entry")
    return problems

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES)
    ap.add_argument("--cluster", default=None, help="check only this cluster (full matter_type name)")
    args = ap.parse_args()
    problems = check(args.cases_dir, args.cluster)
    for p in problems:
        print("FAIL:", p)
    scope = args.cluster or "all clusters"
    print(f"{'PROBLEMS' if problems else 'OK'} ({scope}): {len(problems)} problem(s)")
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main())
