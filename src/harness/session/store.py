# src/harness/session/store.py
"""The R3 session store: one JSONL per session (the durable, Claude-Code-shaped
record), a SQLite index for --list/--resume, and the jobs table S7f deferred into
this step.

Design rules, each one load-bearing:
- The JSONL file IS the record; the index is a convenience for listing and the
  last-session lookup. A lost index is rebuilt from the files, never the reverse.
- Colon-free ids (Windows registry directory names — sync_mount works under the
  store root): rejected at creation, not sanitised, so a bad id fails loudly.
- Every write carries encoding="utf-8" (silent truncation without it on Windows).
- No ORM: plain sqlite3, connections opened and closed per call, so the store is
  safe to read from the TUI while the factory writes.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TurnRow:
    """One completed turn, exactly the shape spec 16 agreed (do not trim): the
    session store's row and the acceptance checks read these fields by name."""
    ts: str
    session_id: str
    matter_ref: str
    display: str
    agent: str
    tools_used: list[str] = field(default_factory=list)
    output_summary: str = ""
    docs_touched: list[str] = field(default_factory=list)
    trace_refs: list[int] = field(default_factory=list)


def _require_colon_free(*values: str, what: str = "id") -> None:
    for v in values:
        if ":" in v:
            raise ValueError(
                f"{what} must be colon-free (Windows registry directory names): {v!r}")


class SessionStore:
    """Sessions under <root>/sessions/. Thread-safe enough for the TUI + factory
    pattern: every method opens its own connection and the JSONL append is a
    single short write."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index = self.root / "sessions" / "index.sqlite3"
        with self._c() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(
              session_id TEXT PRIMARY KEY, matter_ref TEXT, display TEXT,
              turns INTEGER DEFAULT 0, started TEXT, updated TEXT,
              opencode_session TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS jobs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, stage TEXT,
              agent TEXT, status TEXT, detail TEXT, ts TEXT);
            CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id);
            """)
            # additive in-place migration (the S7d `backend` precedent): a store
            # written before the column existed gains it on open; old rows read ''
            cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)").fetchall()}
            if "opencode_session" not in cols:
                c.execute("ALTER TABLE sessions ADD COLUMN opencode_session"
                          " TEXT NOT NULL DEFAULT ''")

    def _c(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.index)
        con.row_factory = sqlite3.Row
        return con

    # -- sessions -----------------------------------------------------------

    def new_session(self, matter_ref: str, display: str = "") -> str:
        _require_colon_free(matter_ref, what="matter ref")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        sid = f"ses-{stamp}-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._c() as c:
            c.execute("INSERT INTO sessions(session_id, matter_ref, display, turns,"
                      " started, updated) VALUES(?,?,?,0,?,?)",
                      (sid, matter_ref, display, now, now))
        # create the JSONL so a later append never races a reader on a missing file
        (self.dir / f"{sid}.jsonl").write_text("", encoding="utf-8")
        return sid

    def sessions(self) -> list[dict]:
        with self._c() as c:
            rows = c.execute("SELECT session_id, matter_ref, display, turns, started,"
                             " updated, opencode_session FROM sessions"
                             " ORDER BY started DESC").fetchall()
        return [dict(r) for r in rows]

    def set_opencode_session(self, session_id: str, opencode_session: str) -> None:
        """The resume handle (F6): the opencode session id `--session <id>` needs
        (P3 — `--continue`/`-c` are dead on 1.18.25). Written by the driver after
        each spawn; the newest id wins."""
        with self._c() as c:
            c.execute("UPDATE sessions SET opencode_session = ? WHERE session_id = ?",
                      (opencode_session, session_id))

    def last(self, matter_ref: str | None = None) -> str | None:
        rows = self.sessions()
        if matter_ref is not None:
            rows = [r for r in rows if r["matter_ref"] == matter_ref]
        return rows[0]["session_id"] if rows else None

    # -- turns ---------------------------------------------------------------

    def append_turn(self, row: TurnRow) -> None:
        path = self.dir / f"{row.session_id}.jsonl"
        # the JSONL is the record — a first turn on a pre-existing session appends;
        # a session that lost its file gets it recreated (index says it exists).
        line = json.dumps(asdict(row), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        with self._c() as c:
            c.execute("UPDATE sessions SET turns = turns + 1, updated = ?"
                      " WHERE session_id = ?", (row.ts, row.session_id))

    def turns(self, session_id: str) -> list[TurnRow]:
        path = self.dir / f"{session_id}.jsonl"
        if not path.is_file():
            return []
        out: list[TurnRow] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(TurnRow(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                # a torn line loses ONE turn's row, never the file — mirror
                # parse_events' skip-the-unreadable-line convention.
                continue
        return out

    # -- the jobs table (S7f's deferral lands here) ---------------------------

    def add_job(self, session_id: str, stage: str, agent: str, status: str,
                detail: str = "") -> int:
        with self._c() as c:
            cur = c.execute("INSERT INTO jobs(session_id, stage, agent, status,"
                            " detail, ts) VALUES(?,?,?,?,?,?)",
                            (session_id, stage, agent, status, detail,
                             datetime.now(timezone.utc).isoformat()))
            return int(cur.lastrowid)

    def jobs(self, session_id: str) -> list[dict]:
        with self._c() as c:
            rows = c.execute("SELECT id, stage, agent, status, detail, ts FROM jobs"
                             " WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
        return [dict(r) for r in rows]
