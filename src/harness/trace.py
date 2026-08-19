# src/harness/trace.py
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from pydantic import BaseModel

class DispatchRecord(BaseModel):
    matter_ref: str
    task_class: str
    classification: str            # LOCAL_ONLY | LOCAL_PREFERRED | CLOUD_PERMITTED
    provider: str
    model: str
    weights_revision: str = ""
    engine: str = ""
    verified: int = 0              # 1 = provenance verified at dispatch time (CR-3)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache: int = 0
    latency_ms: int = 0
    status: str = "ok"             # ok | error | refused
    error: str = ""

class TraceStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._c() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS dispatches(
              id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
              matter_ref TEXT, task_class TEXT, classification TEXT,
              provider TEXT, model TEXT, weights_revision TEXT, engine TEXT, verified INTEGER,
              tokens_in INTEGER, tokens_out INTEGER, tokens_cache INTEGER,
              latency_ms INTEGER, status TEXT, error TEXT);
            CREATE INDEX IF NOT EXISTS idx_matter ON dispatches(matter_ref);
            """)

    def _c(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def append(self, r: DispatchRecord) -> int:
        with self._c() as c:
            cur = c.execute(
                "INSERT INTO dispatches(ts,matter_ref,task_class,classification,provider,model,"
                "weights_revision,engine,verified,tokens_in,tokens_out,tokens_cache,latency_ms,status,error)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (datetime.now(timezone.utc).isoformat(), r.matter_ref, r.task_class, r.classification,
                 r.provider, r.model, r.weights_revision, r.engine, r.verified,
                 r.tokens_in, r.tokens_out, r.tokens_cache, r.latency_ms, r.status, r.error))
            return cur.fetchone()[0]

    def _row(self, row) -> DispatchRecord:
        return DispatchRecord(**dict(zip(
            ["matter_ref","task_class","classification","provider","model","weights_revision",
             "engine","verified","tokens_in","tokens_out","tokens_cache","latency_ms","status","error"],
            row[2:])))

    def get(self, dispatch_id: int) -> DispatchRecord:
        with self._c() as c:
            row = c.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        return self._row(row)

    def by_matter(self, matter_ref: str) -> list[DispatchRecord]:
        with self._c() as c:
            rows = c.execute("SELECT * FROM dispatches WHERE matter_ref=? ORDER BY id", (matter_ref,)).fetchall()
        return [self._row(r) for r in rows]

    def summary(self) -> dict:
        with self._c() as c:
            n, errs = c.execute("SELECT COUNT(*), SUM(status='error') FROM dispatches").fetchone()
            engines = dict(c.execute("SELECT engine, COUNT(*) FROM dispatches GROUP BY engine").fetchall())
        return {"dispatches": n, "errors": int(errs or 0), "by_engine": engines}
