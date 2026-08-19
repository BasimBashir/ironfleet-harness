from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel

class GoldenCase(BaseModel):
    id: str
    matter_type: str
    task_class: str
    prompt: str
    expected_citations: list[str] = []
    required_grounding: list[str] = []
    persona_checks: dict[str, str] = {}     # check-name -> pass condition (deterministic string checks)

def load_cases(directory: Path) -> list[GoldenCase]:
    cases = []
    for p in sorted(Path(directory).glob("*.yaml")):
        cases.append(GoldenCase.model_validate(yaml.safe_load(p.read_text())))
    return cases
