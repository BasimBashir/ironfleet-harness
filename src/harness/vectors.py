# src/harness/vectors.py
"""A-4: the thin local vector index (spec §4).

Vectors are float32 BLOBs in SQLite; search is pure-Python cosine. This is the
index A-4 was priced for (thousands to tens of thousands of chunks per matter);
swapping in sqlite-vec or numpy later is a store-internal change behind the same
interface. matter_ref scoping is a confidentiality property — a search for one
matter must never surface another's vectors.
"""
from __future__ import annotations
import math
import sqlite3
from array import array
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel


class SearchHit(BaseModel):
    seq: int
    text: str
    score: float


def _cosine(a: array, b: array) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0                # a zero vector has no direction; score it 0, never raise
    return dot / (math.sqrt(na) * math.sqrt(nb))


class VectorStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_skipped: list[int] = []      # row ids skipped by the last search
        with self._c() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS embeddings(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
              matter_ref TEXT, seq INTEGER, text TEXT,
              model TEXT, provider TEXT, dim INTEGER, vector BLOB);
            CREATE INDEX IF NOT EXISTS idx_emb_matter ON embeddings(matter_ref);
            """)

    def _c(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def add(self, matter_ref: str, texts: list[str], vectors: list[list[float]],
            model: str, provider: str) -> int:
        if len(texts) != len(vectors):
            raise ValueError(f"{len(texts)} texts but {len(vectors)} vectors")
        ts = datetime.now(timezone.utc).isoformat()
        rows = [(matter_ref, seq, text, model, provider, len(vec),
                 array("f", vec).tobytes())
                for seq, (text, vec) in enumerate(zip(texts, vectors))]
        with self._c() as c:
            c.executemany(
                "INSERT INTO embeddings(ts,matter_ref,seq,text,model,provider,dim,vector)"
                " VALUES(?,?,?,?,?,?,?,?)", [(ts, *r) for r in rows])
        return len(rows)

    def search(self, matter_ref: str, query: list[float], k: int = 5) -> list[SearchHit]:
        q = array("f", query)
        self.last_skipped = []
        hits: list[SearchHit] = []
        with self._c() as c:
            cur = c.execute(
                "SELECT id, seq, text, dim, vector FROM embeddings WHERE matter_ref=?"
                " ORDER BY seq", (matter_ref,))
            for row in cur.fetchall():
                rid, seq, text, dim, blob = row
                if dim != len(q):
                    self.last_skipped.append(rid)
                    continue
                try:
                    v = array("f")
                    v.frombytes(blob)           # raises on a non-float32-multiple BLOB
                except (ValueError, TypeError):
                    self.last_skipped.append(rid)
                    continue
                if len(v) != dim:
                    self.last_skipped.append(rid)
                    continue
                hits.append(SearchHit(seq=seq, text=text, score=_cosine(v, q)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def count(self, matter_ref: str) -> int:
        with self._c() as c:
            return c.execute("SELECT COUNT(*) FROM embeddings WHERE matter_ref=?",
                             (matter_ref,)).fetchone()[0]
