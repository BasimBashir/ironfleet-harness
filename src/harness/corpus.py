# src/harness/corpus.py
"""R1 (spec 14): the citation-exact legal corpus layer — store, retrieval, composition.

Task 1: the structure-aware splitter, promoted verbatim from the research bench
(scripts/bench_r1_ingest.py, which now imports this module). D2: paragraph- AND
heading-aware; every chunk carries its section heading as provenance.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from harness.gate import EmbeddingRequest, RerankRequest

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


# ------------------------------------------------------------------ R1 Task 2: the store

import hashlib  # noqa: E402
import sqlite3  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402


@dataclass
class DocRecord:
    doc_id: str
    text: str
    source_name: str


@dataclass
class CorpusHit:
    doc_id: str
    heading: str
    text: str
    source_name: str
    score: float


def _mtable(matter_ref: str, kind: str) -> str:
    """Colon-free per-matter table names (Windows rule; D1: one table PER MATTER —
    FTS5 BM25 statistics span the whole table even under a column filter, so shared
    tables degrade ranking and leak corpus shape across matters; measured 2026-10-13)."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", matter_ref)
    return f"{kind}_{name}"


def _fts_query(query: str, max_terms: int = 24) -> str:
    """FTS5 OR of the alphanumeric tokens — FTS5 query syntax chokes on legal punctuation."""
    terms = [t for t in re.findall(r"[A-Za-z0-9]{3,}", query)][:max_terms]
    return " OR ".join(f'"{t}"' for t in terms)


# ------------------------------------------------- R1 Task-3 amendment: citation injection
_ACT_RE = re.compile(
    r"((?:[A-Z][A-Za-z’'\-\.]*\s+){0,11}(?:Act|Acts|Regulations|Rules)\s+"
    r"(?:19\d\d|20\d\d))")
_SECT_RE = re.compile(
    r"(?:ss\.?|s\.?|sections?\.?)\s+(\d+[A-Za-z()]*(?:\s+(?:and|to)\s+\d+[A-Za-z()]*"
    r"|\s+\d+[A-Za-z()]*){0,3})", re.IGNORECASE)


def _cit_key(title: str, year: str, section: str) -> str:
    return f"{re.sub(r'[^a-z ]', '', title.lower().strip())}|{year}|{section}"


def _citation_keys(text: str) -> set[str]:
    """Citation spans -> canonical 'act title|year|section' join keys.

    The measured failure this closes (2026-10-14, live on the 36k-chunk acceptance
    corpus): for a query naming 'Companies Act 1993 s 135' exactly, BM25 ranked the
    containing provision chunk 41st among 24,343 OR-matches — 'Act' alone is in 65% of
    chunks and BM25's length normalisation lifts short amendment stubs over the real
    400-word provision. A citation is a JOIN KEY, not a prose match: section spans are
    found in a window around the act-year match, so 's 135 ... Companies Act 1993'
    (query order) and 'Companies Act 1993, s 135' (DLM anchor body) canonicalise alike.
    """
    keys: set[str] = set()
    for act in _ACT_RE.finditer(text):
        window = text[max(0, act.start() - 60):act.end() + 60]
        span = act.group(1)
        year, title = span[-4:], span[:-4].strip()
        secs = _SECT_RE.findall(window)
        if not secs:
            continue   # no section in scope: leave the whole-act match to BM25
        for _s in [_s for sec in secs for _s in re.findall(r"\d+[A-Za-z()]*", sec)]:
            keys.add(_cit_key(title, year, _s))
    return keys


class CorpusStore:
    """One SQLite db at the store root; each matter gets its own docs + FTS tables (D1).

    The store never dispatches: the caller embeds (through the gate — D3/LOCAL_ONLY)
    and hands vectors in, aligned 1:1 with the doc's chunks. Vectors ride the existing
    VectorStore interface (Task 4 swaps its engine store-internally).
    """

    def __init__(self, db_path: Path, vectors: "VectorStore | None" = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._vectors = vectors
        with self._c() as c:
            c.executescript("PRAGMA journal_mode=WAL;")

    def _c(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def has_doc(self, matter_ref: str, sha256: str) -> bool:
        try:
            with self._c() as c:
                row = c.execute(
                    f"SELECT 1 FROM {_mtable(matter_ref, 'docs')} WHERE sha256=?",
                    (sha256,)).fetchone()
        except sqlite3.OperationalError:        # matter never ingested -> not present
            return False
        return row is not None

    def ingest(self, matter_ref: str, doc: DocRecord, vectors: list,
               model: str, provider: str) -> int:
        chunks = split_structure(doc.doc_id, doc.text)
        if len(vectors) != len(chunks):
            raise ValueError(f"{len(vectors)} vectors for {len(chunks)} chunks "
                             f"of {doc.doc_id} — the caller embeds 1:1 with the split")
        sha = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
        with self._c() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {_mtable(matter_ref, 'docs')}"
                      "(doc_id TEXT PRIMARY KEY, source_name TEXT, sha256 TEXT,"
                      " words INTEGER, chunk_count INTEGER, ts TEXT)")
            c.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {_mtable(matter_ref, 'fts')}"
                      " USING fts5(doc_id, heading, body)")
            c.execute(f"CREATE TABLE IF NOT EXISTS {_mtable(matter_ref, 'cites')}"
                      "(key TEXT, fts_rowid INTEGER, PRIMARY KEY(key, fts_rowid))")
            c.execute(f"INSERT OR REPLACE INTO {_mtable(matter_ref, 'docs')}"
                      " VALUES(?,?,?,?,?,?)",
                      (doc.doc_id, doc.source_name, sha, len(doc.text.split()),
                       len(chunks), datetime.now(timezone.utc).isoformat()))
            c.execute(f"DELETE FROM {_mtable(matter_ref, 'fts')} WHERE doc_id=?",
                      (doc.doc_id,))
            c.execute(f"DELETE FROM {_mtable(matter_ref, 'cites')} WHERE key IN "
                      f"(SELECT key FROM {_mtable(matter_ref, 'cites')} WHERE "
                      f"fts_rowid IN (SELECT rowid FROM {_mtable(matter_ref, 'fts')}"
                      " WHERE doc_id=?))", (doc.doc_id,))
            c.executemany(f"INSERT INTO {_mtable(matter_ref, 'fts')}"
                          "(doc_id, heading, body) VALUES(?,?,?)",
                          [(ch.doc_id, ch.heading, ch.text) for ch in chunks])
            rowids = [r[0] for r in c.execute(
                f"SELECT rowid FROM {_mtable(matter_ref, 'fts')} WHERE doc_id=? "
                f"ORDER BY rowid", (doc.doc_id,))]
            # the join keys: each chunk's own citation spans (the DLM provision anchor
            # lands in the body; judgment bodies cite provisions inline too)
            cite_rows = [(k, rid) for rid, ch in zip(rowids, chunks)
                         for k in _citation_keys(f"{ch.heading}\n{ch.text}")]
            c.executemany(f"INSERT OR REPLACE INTO {_mtable(matter_ref, 'cites')}"
                          " VALUES(?,?)", cite_rows)
        if self._vectors is not None:
            self._vectors.add(matter_ref,
                              chunk_text(doc.doc_id, doc.text),
                              [list(map(float, v)) for v in vectors], model, provider)
        return len(chunks)

    def search_lexical(self, matter_ref: str, query: str, k: int = 20) -> list[CorpusHit]:
        q = _fts_query(query)
        if not q:
            return []
        try:
            rows = self._c().execute(
                f"SELECT f.doc_id, f.heading, f.body, d.source_name, bm25({_mtable(matter_ref, 'fts')})"
                f" FROM {_mtable(matter_ref, 'fts')} f"
                f" JOIN {_mtable(matter_ref, 'docs')} d ON d.doc_id = f.doc_id"
                f" WHERE {_mtable(matter_ref, 'fts')} MATCH ? ORDER BY 5 LIMIT ?",
                (q, k)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [CorpusHit(doc_id=d, heading=h, text=b, source_name=s, score=-sc)
                for d, h, b, s, sc in rows]

    def reindex_cites(self, matter_ref: str) -> int:
        """(Re)derive cites_<m> from the stored chunks — keys are pure text, so no
        re-embedding. Runs after upgrading an already-ingested corpus to the
        citation-injection amendment (2026-10-14)."""
        with self._c() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {_mtable(matter_ref, 'cites')}"
                      "(key TEXT, fts_rowid INTEGER, PRIMARY KEY(key, fts_rowid))")
            c.execute(f"DELETE FROM {_mtable(matter_ref, 'cites')}")
            rows = c.execute(
                f"SELECT rowid, heading, body FROM {_mtable(matter_ref, 'fts')}"
            ).fetchall()
            c.executemany(
                f"INSERT OR REPLACE INTO {_mtable(matter_ref, 'cites')} VALUES(?,?)",
                [(k, r) for r, h, b in rows
                 for k in _citation_keys(f"{h}\n{b}")])
            return c.execute(f"SELECT COUNT(*) FROM {_mtable(matter_ref, 'cites')}"
                             ).fetchone()[0]


        try:
            with self._c() as c:
                return c.execute(
                    f"SELECT COUNT(*) FROM {_mtable(matter_ref, 'fts')}").fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def doc_count(self, matter_ref: str) -> int:
        try:
            with self._c() as c:
                return c.execute(
                    f"SELECT COUNT(*) FROM {_mtable(matter_ref, 'docs')}").fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def _cited_hits(self, matter_ref: str, query: str, k: int) -> list[CorpusHit]:
        """Citation-injected candidates: a citation named in the query is a join key on
        cites_<m>, bypassing BM25's length/IDF dilution — the amendment the measured
        rank-41-for-an-exact-name failure forced (2026-10-14). Empty when the query
        names no (act, section) pair."""
        keys = _citation_keys(query)
        if not keys:
            return []
        marks = ",".join("?" for _ in keys)
        try:
            rowids = [r[0] for r in self._c().execute(
                f"SELECT DISTINCT fts_rowid FROM {_mtable(matter_ref, 'cites')} "
                f"WHERE key IN ({marks}) ORDER BY fts_rowid", tuple(keys)).fetchall()]
        except sqlite3.OperationalError:
            return []   # no cites table for this matter yet
        if not rowids:
            return []
        marks = ",".join("?" for _ in rowids)
        rows = self._c().execute(
            f"SELECT f.doc_id, f.heading, f.body, d.source_name FROM "
            f"{_mtable(matter_ref, 'fts')} f JOIN {_mtable(matter_ref, 'docs')} d "
            f"ON d.doc_id = f.doc_id WHERE f.rowid IN ({marks}) ORDER BY f.rowid",
            tuple(rowids)).fetchall()
        return [CorpusHit(doc_id=d, heading=h, text=b, source_name=s,
                          score=1.0 - i / max(1, len(rows)))
                for i, (d, h, b, s) in enumerate(rows[:k])]

    def search(self, matter_ref: str, query_text: str, query_vector: list[float],
               k: int = 5, candidates: int = 20) -> list[CorpusHit]:
        """Hybrid: lexical BM25 + dense vector, fused by RRF (Task 3). Either leg may
        come back empty; the other carries alone. Per-matter by construction (D1).
        Citation-injected candidates ride a third ranking (Task-3 amendment) — a
        citation named in the query is a join key, not a prose match."""
        lex = self.search_lexical(matter_ref, query_text, candidates)
        vec: list[CorpusHit] = []
        if self._vectors is not None and query_vector:
            vec = self._vec_hits(matter_ref, list(query_vector), candidates)
        cit = self._cited_hits(matter_ref, query_text, candidates)
        lex_keys = [_hit_key(h) for h in lex]
        vec_keys = [_hit_key(h) for h in vec]
        cit_keys = [_hit_key(h) for h in cit]
        fused_keys = set(rrf([lex_keys, vec_keys, cit_keys]))
        by_key: dict[str, CorpusHit] = {}
        for h in lex + vec + cit:
            by_key.setdefault(_hit_key(h), h)
        fused = [h for hkey in rrf([lex_keys, vec_keys, cit_keys])
                 if hkey in fused_keys and (h := by_key.get(hkey)) is not None]
        return fused[:k]

    def _vec_hits(self, matter_ref: str, query_vector: list[float],
                  candidates: int) -> list[CorpusHit]:
        hits = self._vectors.search(matter_ref, query_vector, k=candidates)
        out: list[CorpusHit] = []
        if not hits:
            return out
        with self._c() as c:
            for h in hits:
                row = c.execute(
                    f"SELECT f.doc_id, f.heading, f.body, d.source_name FROM "
                    f"{_mtable(matter_ref, 'fts')} f JOIN "
                    f"{_mtable(matter_ref, 'docs')} d ON d.doc_id = f.doc_id "
                    f"WHERE (? = '' OR f.heading || char(10) || f.body = ? OR f.body = ?)",
                    (h.text, h.text, h.text)).fetchone()
                if row:
                    out.append(CorpusHit(doc_id=row[0], heading=row[1], text=row[2],
                                         source_name=row[3], score=h.score))
        return out


# ---------------------------------------------------------------- R1 Task 3: hybrid search

def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion (k=60, the 2026 standard): no score normalisation needed
    between BM25 (negative-better) and cosine (positive-better)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return [item for item, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def _hit_key(hit: CorpusHit) -> str:
    return f"{hit.doc_id}\x1f{hit.heading}\x1f{hit.text}"


# ---------------------------------------------------------------- R1 Task 6: the tool

_TOOL_GATE = None          # lazily built once; probing Ollama is seconds, not per-call


def _default_gate():
    global _TOOL_GATE
    if _TOOL_GATE is None:
        from scripts.stand_up_opencode import ROUTING, build_gate
        _TOOL_GATE, _rt, _al = build_gate(
            Path(__file__).resolve().parents[2] / "data" / "eval" / "corpus_tool_trace.sqlite3",
            ROUTING)
    return _TOOL_GATE


def ironfleet_corpus_search(query: str, k: int = 5, rerank: bool = True,
                            store: "CorpusStore | None" = None,
                            embed_fn=None, rerank_fn=None,
                            matter: str | None = None) -> dict:
    """The gated ported tool (D5): matter-scoped hybrid corpus search whose result
    carries the AUTHORITIES list — the verbatim passage texts the guard checks quotes
    against. Fail-closed: no matter bound -> an honest empty envelope, never another
    matter's text. The store never dispatches; embeddings and rerank go through the
    injected callables (the gate in production, fakes in tests)."""
    matter = matter or os.environ.get("IRONFLEET_MATTER", "")
    if not matter:
        return {"passages": [], "authorities": [], "error": "no matter bound"}
    if store is None:
        from harness.paths import resolve_store_root
        root = resolve_store_root()
        store = CorpusStore(Path(root) / "corpus.sqlite3",
                            vectors=VectorStore(Path(root) / "vectors.sqlite3"))
    if embed_fn is None:
        gate = _default_gate()

        def embed_fn(texts):
            import asyncio
            res = asyncio.run(gate.embed(
                EmbeddingRequest(matter_ref=matter, texts=texts)))
            return res.vectors
    qvec = embed_fn([query[:1200]])[0]
    hits = store.search(matter, query, qvec, k=max(k * 4, 20))
    if rerank and rerank_fn is None:
        gate = _default_gate()

        def rerank_fn(query, texts):
            import asyncio
            res = asyncio.run(gate.rerank(
                RerankRequest(matter_ref=matter, query=query, texts=texts)))
            return res.scores
    if rerank and rerank_fn is not None and hits:
        scores = rerank_fn(query[:1200], [h.text[:4000] for h in hits])
        hits = [h for _, h in sorted(zip(scores, hits), key=lambda p: -p[0])]
    top = hits[:k]
    return {"passages": [{"doc_id": h.doc_id, "heading": h.heading, "text": h.text,
                          "source_name": h.source_name, "score": h.score} for h in top],
            "authorities": [h.text for h in top]}


# ------------------------------------------------- R1 Task 10: D9 select-compose support

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z“(\[])")
_REF_TOKEN = re.compile(r"\[E\d+\.S\d+\]")


def evidence_window(passages: list[dict], min_words: int = 6, cap: int = 500
                    ) -> tuple[str, dict[str, str]]:
    """D9: render the numbered evidence window the drafting model composes against.

    Returns (block, table): the block numbers every sentence [E<extract>.S<sent>]; the
    table maps each reference to its VERBATIM sentence. The model never copies quoted
    prose — it emits references, and splice_references() restores the exact text, making
    quote-fidelity a construction property (measured 781/0 valid on a 30B model)."""
    table: dict[str, str] = {}
    blocks: list[str] = []
    offered = 0
    for e, p in enumerate(passages, 1):
        lines = []
        for s_i, sent in enumerate(
                (s.strip() for s in _SENT_SPLIT.split(p["text"])), 1):
            if len(sent.split()) < min_words:
                continue
            if offered >= cap:
                break
            ref = f"[E{e}.S{s_i}]"
            table[ref] = sent
            lines.append(f"{ref} {sent}")
            offered += 1
        if lines:
            blocks.append(f"[Extract {e} | {p.get('source', '')}]\n" + "\n".join(lines))
        if offered >= cap:
            break
    return "\n\n".join(blocks), table


def splice_references(draft: str, table: dict[str, str]) -> tuple[str, int, int]:
    """Substitute every valid reference with its verbatim sentence, in quotes.
    Returns (spliced, substituted, invalid). Invalid references stay VISIBLE in the
    output (never silently dropped — the D9 contract) and are counted for the repair
    pass / guard."""
    invalid = 0
    substituted = 0

    def rep(m: re.Match) -> str:
        nonlocal invalid, substituted
        ref = m.group(0)
        if ref in table:
            substituted += 1
            return f"\"{table[ref]}\""
        invalid += 1
        return ref

    spliced = _REF_TOKEN.sub(rep, draft)
    return spliced, substituted, invalid
