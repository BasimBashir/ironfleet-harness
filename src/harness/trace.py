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
    backend: str = ""              # S7d: executing backend as proven at dispatch (CR-3)
    verified: int = 0              # 1 = provenance verified at dispatch time (CR-3)
    # R3 (finding F1): which AGENT and which SESSION this dispatch belongs to. The
    # per-agent token ledger (D-T3) and the session store's JSONL join both key on
    # these; before they existed, dispatch rows carried only matter_ref and neither
    # join was possible.
    agent: str = ""
    session_id: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_cache: int = 0
    latency_ms: int = 0
    status: str = "ok"             # ok | error | refused
    error: str = ""
    # R3 refine: the provider's reasoning-token count (completion_tokens_details
    # .reasoning_tokens when the upstream reports it), 0 when it does not — the
    # per-agent ledger's "think" column. Additive column, in-place migration.
    tokens_reasoning: int = 0

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
            # S7d migration: stores written before the backend column existed upgrade in
            # place; old rows read '' — the honest value (backend was never recorded).
            cols = {row[1] for row in c.execute("PRAGMA table_info(dispatches)").fetchall()}
            if "backend" not in cols:
                c.execute("ALTER TABLE dispatches ADD COLUMN backend TEXT NOT NULL DEFAULT ''")
            # R3 (finding F1): the same additive, by-name, in-place pattern for the
            # agent + session identity columns. One block, ALTERs in the same order the
            # INSERT below lists them — a fresh CREATE already has them, so the ALTERs
            # are no-ops there.
            if "agent" not in cols:
                c.execute("ALTER TABLE dispatches ADD COLUMN agent TEXT NOT NULL DEFAULT ''")
            if "session_id" not in cols:
                c.execute("ALTER TABLE dispatches ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
            if "tokens_reasoning" not in cols:
                c.execute("ALTER TABLE dispatches ADD COLUMN tokens_reasoning INTEGER NOT NULL DEFAULT 0")
            c.execute("CREATE INDEX IF NOT EXISTS idx_session ON dispatches(session_id)")

    def _c(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def append(self, r: DispatchRecord) -> int:
        with self._c() as c:
            cur = c.execute(
                "INSERT INTO dispatches(ts,matter_ref,task_class,classification,provider,model,"
                "weights_revision,engine,backend,verified,agent,session_id,"
                "tokens_in,tokens_out,tokens_cache,"
                "latency_ms,status,error,tokens_reasoning)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (datetime.now(timezone.utc).isoformat(), r.matter_ref, r.task_class, r.classification,
                 r.provider, r.model, r.weights_revision, r.engine, r.backend, r.verified,
                 r.agent, r.session_id,
                 r.tokens_in, r.tokens_out, r.tokens_cache,
                 r.latency_ms, r.status, r.error, r.tokens_reasoning))
            return cur.fetchone()[0]

    _FIELDS = ("matter_ref", "task_class", "classification", "provider", "model",
               "weights_revision", "engine", "backend", "verified", "agent", "session_id",
               "tokens_in", "tokens_out", "tokens_cache", "latency_ms", "status", "error",
               "tokens_reasoning")

    def by_session(self, session_id: str) -> list[DispatchRecord]:
        """R3 (finding F1/F7): the session's dispatch rows — the D-T3 per-agent
        ledger and the turn-row join both read this. Rows are AGGREGATED (a turn
        can emit more than one dispatch — P4's finding), never counted."""
        with self._c() as c:
            return self._rows(c.execute(
                "SELECT * FROM dispatches WHERE session_id=? ORDER BY id", (session_id,)))

    def _rows(self, cur) -> list[DispatchRecord]:
        # By column NAME, never position: a migrated DB's column order (ALTER appends at
        # the end) differs from a fresh DB's. A missing column is schema drift — fail loud.
        by_name = {d[0]: i for i, d in enumerate(cur.description)}
        idx = [by_name[f] for f in self._FIELDS]
        return [DispatchRecord(**dict(zip(self._FIELDS, [r[i] for i in idx])))
                for r in cur.fetchall()]

    def by_ids(self, ids: list[int]) -> list[DispatchRecord]:
        """R3 (F1/F7 consumer): the dispatch rows for explicit ids — the shell's
        meter joins on its OWN recorded trace_refs (the live mount does not carry
        session identity to the gate), so this is the session-ledger read."""
        if not ids:
            return []
        with self._c() as c:
            marks = ",".join("?" * len(ids))
            return self._rows(c.execute(
                f"SELECT * FROM dispatches WHERE id IN ({marks}) ORDER BY id",
                [int(i) for i in ids]))

    def get(self, dispatch_id: int) -> DispatchRecord:
        with self._c() as c:
            rows = self._rows(c.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)))
        return rows[0]

    def attr(self, agent: str, session_id: str, ids: list[int]) -> None:
        """Attribute a turn's dispatch rows to the AGENT + SESSION that produced
        them. F1's columns are write-when-supplied and the live mount never
        supplies them — but the SHELL owns the before/after span of every turn it
        drives, so the span is attributed here, from the driver. The shell runs
        turns sequentially (one stage at a time), which is what makes the span
        unambiguous; a concurrent dispatch inside it would be mis-attributed."""
        if not ids:
            return
        with self._c() as c:
            marks = ",".join("?" * len(ids))
            c.execute(f"UPDATE dispatches SET agent=?, session_id=?"
                      f" WHERE id IN ({marks})",
                      [agent, session_id, *[int(i) for i in ids]])

    def by_matter(self, matter_ref: str) -> list[DispatchRecord]:
        with self._c() as c:
            return self._rows(c.execute(
                "SELECT * FROM dispatches WHERE matter_ref=? ORDER BY id", (matter_ref,)))

    def summary(self) -> dict:
        with self._c() as c:
            n, errs = c.execute("SELECT COUNT(*), SUM(status='error') FROM dispatches").fetchone()
            engines = dict(c.execute("SELECT engine, COUNT(*) FROM dispatches GROUP BY engine").fetchall())
        return {"dispatches": n, "errors": int(errs or 0), "by_engine": engines}
