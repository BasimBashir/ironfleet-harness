# src/harness/eval/scorers.py
from __future__ import annotations
import re
from pathlib import Path
from pydantic import BaseModel
from harness.eval.golden_case import GoldenCase

class CaseScore(BaseModel):
    case_id: str
    citation_accuracy: float
    grounding_score: float
    checks: dict[str, bool]
    passed: bool
    status: str = "scored"              # scored | refused (S6-3: refusal still reports)
    error: str = ""                     # refusal reason when status == "refused"

# --- S6-5 citation normaliser ---------------------------------------------------
# The exact-substring citation scorer was brittle to citation-form variants (S2
# findings: parallel cites, party-name short/full forms, statute word order,
# hyphenation, year-fragile instrument pins). citation_accuracy now accepts the
# documented families via CONSERVATIVE textual variants of the AUTHORED needle.
# Regex parses the needle only (it is controlled input); the model output is
# still matched by plain substring — the house rule holds.

_YEAR_STYLE = {"[": "]", "(": ")"}
# a law-report citation span: [2006] 3 NZLR 225 / (1979) 144 CLR 360 / (2008) 23 NZTC 22,074
_REPORT_CITE = re.compile(
    r"(?P<open>[\[(])(?P<year>\d{4})(?P<close>[\])])\s+(?P<vol>\d+)\s+(?P<rep>[A-Z][A-Za-z&.]*)\s+(?P<page>[\d,]+)")
_CITE_SPAN = re.compile(r"[\[(]\d{4}[\])]\s+(?:\d+\s+)?[A-Z][A-Za-z&.]*\s+[\d,]+")
# "Companies Act 1993, s 135" — act (may itself contain parens/commas), year, section
_ACT_PIN = re.compile(r"^(?P<act>.+?)\s+(?P<year>\d{4}),\s*(?P<sec>s(?:ection)?\.?\s+\S+)$")
_BARE_ACT = re.compile(r"^.+\s+Act\s+\d{4}$")

def _norm(text: str) -> str:
    """Hyphen/dash-bridged comparison: case-folded, hyphens removed, whitespace collapsed."""
    return " ".join(re.sub(r"[-‐-―]+", "", text).lower().split())

def citation_variants(needle: str) -> list[str]:
    """Conservative textual variants of an AUTHORED citation needle."""
    vs = {needle}
    m = _ACT_PIN.match(needle)                           # statute pin, comma form
    if m:
        act, sec = f"{m['act']} {m['year']}", m["sec"]
        vs.add(f"{sec} of {act}")                        # prose order
        vs.add(f"{sec} of the {act}")                    # prose order with article
        vs.add(f"{sec} {act}")                           # comma-less order
    if _BARE_ACT.match(needle):                          # year-fragile bare instrument pin
        vs.add(re.sub(r"\s+\d{4}$", "", needle))
    for m in _REPORT_CITE.finditer(needle):              # law-report cite families
        open_, year, close_, vol, rep, page = (m["open"], m["year"], m["close"], m["vol"], m["rep"], m["page"])
        other_open = "(" if open_ == "[" else "["
        vs.add(f"{open_}{year}{close_} {rep} {page}")                      # volume dropped
        vs.add(f"{other_open}{year}{_YEAR_STYLE[other_open]} {vol} {rep} {page}")  # year-style swap
        vs.add(f"{other_open}{year}{_YEAR_STYLE[other_open]} {rep} {page}")        # both
    m = _CITE_SPAN.search(needle)                        # cite alone carries the hit when the
    if m and m.start() > 0:                              # model writes FULL party names
        vs.add(m.group(0))
    return sorted(vs)

def citation_hit(output: str, needle: str) -> bool:
    norm_out = _norm(output)
    return any(v in output or _norm(v) in norm_out for v in citation_variants(needle))

def citation_accuracy(output: str, expected: list[str]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for c in expected if citation_hit(output, c))   # variant-tolerant substring
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
    lines = ["# Eval report", "",
             "| case | citations | grounding | checks | status | passed |",
             "|---|---|---|---|---|---|"]
    for s in scores:
        lines.append(f"| {s.case_id} | {s.citation_accuracy:.2f} | {s.grounding_score:.2f} "
                     f"| {sum(s.checks.values())}/{len(s.checks)} | {s.status} "
                     f"| {'✅' if s.passed else '❌'} |")
    refused = [s for s in scores if s.status == "refused"]
    if refused:                                            # S6-3: reasons below the table
        lines += ["", "## Refused cases", ""]
        lines += [f"- {s.case_id}: {s.error}" for s in refused]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
