# src/harness/quote_check.py
"""R1 Task 7 (D6) + D9: the deterministic referee for quoted text.

Port source: the old tree's helpers/brain_grounding_guard.py normalized-span idea,
rebuilt for the harness (no LLM in the loop — mechanical-class, deterministic).

Two jobs:
  1. VERBATIM CHECK — is a draft's quoted span word-for-word in the retrieved corpus?
     (The D6 guard's refusal basis; the measured baseline is 66-76% honest, 24-34%
     fabricated — this check converts that defect into blocked-and-annotated output.)
  2. SPLICE SUPPORT — normalize() is shared with the select-compose splicer (D9), whose
     job is to make this check pass BY CONSTRUCTION.
"""
from __future__ import annotations

import re

_QUOTE_SPAN = re.compile(r'"([^"]{8,400})"|“([^”]{8,400})”|‘([^’]{8,400})’')
_HYPHENbreak = re.compile(r"([A-Za-z])-\s*\n\s*([a-z])")     # "bail- \nment" -> "bailment"
_WS = re.compile(r"\s+")
_SOFT = re.compile("­")                                  # soft hyphen


def normalize(text: str) -> str:
    """Case-folded, whitespace-collapsed, hyphen-linebreak-bridged comparison form."""
    t = _SOFT.sub("", text)
    t = _HYPHENbreak.sub(r"\1\2", t)
    t = t.replace("-", "").replace("‐", "").replace("–", "").replace("—", "")
    return " ".join(t.lower().split())


def extract_quotes(text: str) -> list[str]:
    """Straight, curly-double and curly-single quoted spans (8-400 chars — short spans
    are noise)."""
    return [next(g for g in m.groups() if g is not None)
            for m in _QUOTE_SPAN.finditer(text)]


def span_in_passages(quote: str, passages: list[str]) -> bool:
    """True iff the quoted span appears (normalised) inside any passage. A quote is a
    SUBSTRING of its source, never equal to it — containment, not equality."""
    if not quote or not passages:
        return False
    nq = normalize(quote)
    if not nq:
        return False
    return any(nq in normalize(p) for p in passages)


def quote_audit(draft: str, passages: list[str]) -> tuple[list[str], list[str]]:
    """(grounded, ungrounded) quoted spans of the draft against the passage set."""
    grounded, ungrounded = [], []
    for q in extract_quotes(draft):
        (grounded if span_in_passages(q, passages) else ungrounded).append(q)
    return grounded, ungrounded
