# src/harness/corpus.py
"""R1 (spec 14): the citation-exact legal corpus layer — store, retrieval, composition.

Task 1: the structure-aware splitter, promoted verbatim from the research bench
(scripts/bench_r1_ingest.py, which now imports this module). D2: paragraph- AND
heading-aware; every chunk carries its section heading as provenance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(?:[IVXLC]+|\d+)[.\)]?\s+[A-Z].*[A-Z]{3}")   # "III. Title ..." / "12. Foo Bar"
_ALLCAPS = re.compile(r"^[^a-z]{6,}$")                                # "TITLE TO BULLION"


@dataclass
class Chunk:
    doc_id: str
    heading: str
    text: str


def split_structure(doc_id: str, text: str, target_words: int = 210) -> list[Chunk]:
    """Paragraph- AND heading-aware split; each chunk carries its section heading.

    Legal structure honoured: ALL-CAPS headings, roman/numbered headings ("III. Title"),
    and blank-line paragraphs. A paragraph is never split mid-way unless it alone exceeds
    2x target (hard-split then — judgments have some very long paragraphs).
    """
    chunks: list[Chunk] = []
    heading = ""
    para_buf: list[str] = []
    buf_words = 0

    def flush() -> None:
        nonlocal para_buf, buf_words
        body = "\n\n".join(para_buf).strip()
        if body:
            chunks.append(Chunk(doc_id, heading, body))
        para_buf, buf_words = [], 0

    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        first_line = para.splitlines()[0].strip()
        is_heading = (len(para) <= 120
                      and (_ALLCAPS.match(first_line) or _HEADING.match(first_line)))
        if is_heading:
            flush()
            heading = first_line
            continue
        words = len(para.split())
        if words > target_words * 2:                      # hard-split an outsized paragraph
            flush()
            cur: list[str] = []
            cur_w = 0
            for s in para.split(". "):
                cur.append(s)
                cur_w += len(s.split())
                if cur_w >= target_words:
                    chunks.append(Chunk(doc_id, heading, ". ".join(cur).strip()))
                    cur, cur_w = [], 0
            if cur:
                chunks.append(Chunk(doc_id, heading, ". ".join(cur).strip()))
            continue
        if buf_words and buf_words + words > target_words:
            flush()
        para_buf.append(para)
        buf_words += words
    flush()
    return chunks


def chunk_text(doc_id: str, text: str) -> list[str]:
    """The embedded form: heading-prefixed chunk bodies."""
    return [f"{c.heading}\n{c.text}" if c.heading else c.text
            for c in split_structure(doc_id, text)]
