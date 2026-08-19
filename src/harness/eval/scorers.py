# src/harness/eval/scorers.py
from __future__ import annotations
from pathlib import Path
from pydantic import BaseModel
from harness.eval.golden_case import GoldenCase

class CaseScore(BaseModel):
    case_id: str
    citation_accuracy: float
    grounding_score: float
    checks: dict[str, bool]
    passed: bool

def citation_accuracy(output: str, expected: list[str]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for c in expected if c in output)         # plain substring, no regex (house rule)
    return hits / len(expected)

def grounding_score(output: str, required: list[str]) -> float:
    if not required:
        return 1.0
    return sum(1 for g in required if g.lower() in output.lower()) / len(required)

def persona_checks_pass(output: str, checks: dict[str, str]) -> dict[str, bool]:
    return {name: needle in output for name, needle in checks.items()}

def score_case(output: str, case: GoldenCase, pass_threshold: float = 0.999) -> CaseScore:
    ca, gs = citation_accuracy(output, case.expected_citations), grounding_score(output, case.required_grounding)
    checks = persona_checks_pass(output, case.persona_checks)
    passed = ca >= pass_threshold and gs >= pass_threshold and all(checks.values())
    return CaseScore(case_id=case.id, citation_accuracy=ca, grounding_score=gs,
                     checks=checks, passed=passed)

def write_report(scores: list[CaseScore], path: Path) -> None:
    lines = ["# Eval report", "", "| case | citations | grounding | checks | passed |", "|---|---|---|---|---|"]
    for s in scores:
        lines.append(f"| {s.case_id} | {s.citation_accuracy:.2f} | {s.grounding_score:.2f} "
                     f"| {sum(s.checks.values())}/{len(s.checks)} | {'✅' if s.passed else '❌'} |")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
