# src/harness/eval/runner.py
from __future__ import annotations
from pathlib import Path
from harness.eval.golden_case import load_cases
from harness.eval.scorers import score_case, write_report, CaseScore
from harness.gate import EgressGate, LLMRequest

async def run_eval(gate: EgressGate, cases_dir: Path, report_path: Path) -> list[CaseScore]:
    scores = []
    for case in load_cases(cases_dir):
        resp = await gate.dispatch(LLMRequest(matter_ref=f"eval:{case.id}", task_class=case.task_class,
                                              messages=[{"role": "user", "content": case.prompt}]))
        scores.append(score_case(resp.content, case))
    write_report(scores, report_path)
    return scores
