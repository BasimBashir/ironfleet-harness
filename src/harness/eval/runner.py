# src/harness/eval/runner.py
from __future__ import annotations
from pathlib import Path
from harness.eval.golden_case import load_cases
from harness.eval.scorers import score_case, write_report, CaseScore
from harness.gate import EgressGate, GateRefusal, LLMRequest

async def run_eval(gate: EgressGate, cases_dir: Path, report_path: Path) -> list[CaseScore]:
    scores = []
    for case in load_cases(cases_dir):
        try:
            resp = await gate.dispatch(LLMRequest(matter_ref=f"eval:{case.id}", task_class=case.task_class,
                                                  messages=[{"role": "user", "content": case.prompt}]))
        except GateRefusal as ex:
            # S6-3: a refusal is a per-case outcome, not a run-killer — record it zeroed
            # with the reason and keep going, so the run still produces its report.
            scores.append(CaseScore(case_id=case.id, citation_accuracy=0.0, grounding_score=0.0,
                                    checks={}, passed=False, status="refused", error=str(ex)))
            continue
        scores.append(score_case(resp.content, case))
    write_report(scores, report_path)
    return scores
