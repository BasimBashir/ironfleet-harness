# src/harness/vectors.py
"""A-4 thin local vector index — NOW on sqlite-vec (R1 plan Task 4, spec 14 D4).

The S7e interface is unchanged (add/search/count, per-matter confidentiality); the
engine underneath is swapped from pure-Python cosine to sqlite-vec 0.1.9 (pinned),
which the S7e spec pre-authorised as a store-internal change. D4: the extension is a
HARD dependency — fail-closed at construction, no silent pure-Python fallback (a slow
index that "works" is the S7e scaling lie again; the swap is justified by measurement:
pure-Python cosine 333 ms @ 2.4k chunks).

Vectors are normalised at add time, so sqlite-vec's L2 distance maps to exact cosine
by score = 1 - d²/2 (self-match → 1.0). A row whose vector is not `dim`-long is
REFUSED at add (fail loud), not silently skipped — an index that silently shrinks is
the prefix-embedding lie again.
"""
from __future__ import annotations

import sqlite3
from array import array
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


class SearchHit(BaseModel):
    seq: int
    text: str
    score: float


def _load_extension(con: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ImportError as ex:                              # pragma: no cover — pinned dep
        raise RuntimeError("sqlite-vec is a hard dependency (D4, pinned 0.1.9): "
                           "pip install sqlite-vec==0.1.9") from ex
    try:
        con.enable_load_extension(True)
        con.load_extension(sqlite_vec.loadable_path())
    except Exception as ex:                                # noqa: BLE001 — fail closed
        raise RuntimeError(f"sqlite-vec extension failed to load (D4 fail-closed): {ex}") from ex


def _unit(v: array) -> array:
    n = sum(x * x for x in v) ** 0.5
    if n == 0.0:
        return v
    return array("f", (x / n for x in v))


class VectorStore:
    def __init__(self, db_path: Path, dim: int = 1024) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.dim = dim
        self.last_skipped: list[int] = []      # interface compat: the vec0 engine has no
        con = self._c()                        # skippable rows — mismatches refuse at add
        with con:
            con.executescript(f"""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS embeddings(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
              matter_ref TEXT, seq INTEGER, text TEXT, model TEXT, provider TEXT);
            CREATE INDEX IF NOT EXISTS idx_emb_matter ON embeddings(matter_ref);
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_index USING vec0(
              embedding float[{dim}], matter_ref TEXT PARTITION KEY);
            """)

    def _c(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        _load_extension(con)
        return con

    def add(self, matter_ref: str, texts: list[str], vectors: list[list[float]],
            model: str, provider: str) -> int:
        if len(texts) != len(vectors):
            raise ValueError(f"{len(texts)} texts but {len(vectors)} vectors")
        ts = datetime.now(timezone.utc).isoformat()
        con = self._c()
        with con:
            for seq, (text, vec) in enumerate(zip(texts, vectors)):
                u = _unit(array("f", map(float, vec)))
                if len(u) != self.dim:
                    raise ValueError(f"vector {seq} is {len(u)}-dim; this store is "
                                     f"{self.dim}-dim (D4: refuse, never shrink)")
                cur = con.execute(
                    "INSERT INTO embeddings(ts,matter_ref,seq,text,model,provider)"
                    " VALUES(?,?,?,?,?,?)",
                    (ts, matter_ref, seq, text, model, provider))
                con.execute(
                    "INSERT INTO vec_index(rowid, matter_ref, embedding) VALUES(?,?,?)",
                    (cur.lastrowid, matter_ref, u.tobytes()))
        return len(texts)

    def search(self, matter_ref: str, query: list[float], k: int = 5) -> list[SearchHit]:
        q = _unit(array("f", map(float, query)))
        con = self._c()
        rows = con.execute(
            "SELECT v.rowid, v.distance FROM vec_index v "
            "WHERE v.matter_ref=? AND v.embedding MATCH ? "
            "ORDER BY distance LIMIT ?", (matter_ref, q.tobytes(), k)).fetchall()
        out: list[SearchHit] = []
        for rid, dist in rows:
            meta = con.execute(
                "SELECT seq, text FROM embeddings WHERE id=?", (rid,)).fetchone()
            if meta is None:                       # vec row without metadata: never surface
                continue
            # unit vectors: cosine = 1 - d²/2 (exact; self-match → 1.0)
            out.append(SearchHit(seq=meta[0], text=meta[1],
                                 score=1.0 - (dist ** 2) / 2.0))
        con.close()
        out.sort(key=lambda h: h.score, reverse=True)
        return out

    def count(self, matter_ref: str) -> int:
        con = self._c()
        try:
            return con.execute("SELECT COUNT(*) FROM embeddings WHERE matter_ref=?",
                               (matter_ref,)).fetchone()[0]
        finally:
            con.close()
