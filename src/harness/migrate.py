# src/harness/migrate.py — M11 T2: the store migration mechanism (02 §15).
"""Upgrade every SQLite store in the privileged store root, versioned and
additive-only, in one transaction per database. Rollback is the P0-7 restore
path (never in-place downgrades — a downgrade is "restore the backup taken
before the upgrade", which the runbook and restore_drill.py own).

Rules, each one load-bearing:
- `PRAGMA user_version` is the per-file schema stamp — no extra table, no
  metadata drift between what a file claims and what it carries.
- Every step is ADDITIVE (CREATE/ADD COLUMN with a default / INSERT OR IGNORE
  of registry rows). No DROP, no column rewrite, no data migration inside a
  step; when a step someday must reshape data it stays additive (new table +
  copy + rename is the shape, and it gets its own review).
- Steps run in one transaction per file, ordered by version; the stamp moves
  only if every step committed. A failure mid-upgrade leaves the file at its
  old version, still openable by the old code.
- Known store files only. Absent files are reported `absent`, never created —
  the owning class creates its store on first open; migrate upgrades stores,
  it does not pre-seed them.
- Corruption fails loud naming the path (integrity_check before any write).

Historical note: the additive column-adds in trace.py (S7d `backend`, R3
identity columns) and session/store.py (`opencode_session`) predate this
module and stay — they are the self-heal on open. The steps below REPEAT
those ALTERs so `harness migrate` alone brings a pre-0.2 store current; the
guards make the repeats no-ops on stores the constructors already healed.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1


# Store-relative paths (posix separators) this module knows, with their ordered
# additive steps: (version, callable(con)). A step runs when version > stamp.
def _trace_v1(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(dispatches)").fetchall()}
    if cols:  # absent table = never a trace store; the constructor will create it
        if "backend" not in cols:
            con.execute("ALTER TABLE dispatches ADD COLUMN backend TEXT NOT NULL DEFAULT ''")
        if "agent" not in cols:
            con.execute("ALTER TABLE dispatches ADD COLUMN agent TEXT NOT NULL DEFAULT ''")
        if "session_id" not in cols:
            con.execute("ALTER TABLE dispatches ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
        if "tokens_reasoning" not in cols:
            con.execute("ALTER TABLE dispatches ADD COLUMN tokens_reasoning INTEGER NOT NULL DEFAULT 0")
        con.execute("CREATE INDEX IF NOT EXISTS idx_session ON dispatches(session_id)")


def _sessions_v1(con: sqlite3.Connection) -> None:
    cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)").fetchall()}
    if cols and "opencode_session" not in cols:
        con.execute("ALTER TABLE sessions ADD COLUMN opencode_session TEXT NOT NULL DEFAULT ''")


MIGRATIONS: dict[str, list[tuple[int, object]]] = {
    "trace.db": [(1, _trace_v1)],
    "sessions/index.sqlite3": [(1, _sessions_v1)],
    "platform.db": [],      # schema self-heals on connect (workflow.db SCHEMA); stamp + integrity here
    "corpus.sqlite3": [],
    "vectors.sqlite3": [],
}


class MigrationError(Exception):
    """A store could not be migrated; the message names the path and the reason."""


@dataclass
class MigrateReport:
    path: Path
    status: str            # ok | absent
    from_version: int
    to_version: int
    steps_applied: int


def migrate(root: Path) -> list[MigrateReport]:
    """Bring every known store file under `root` to SCHEMA_VERSION. Raises
    MigrationError on the first corrupt or unopenable file, naming the path."""
    root = Path(root)
    reports: list[MigrateReport] = []
    for rel, steps in MIGRATIONS.items():
        path = root / Path(rel)
        if not path.is_file():
            reports.append(MigrateReport(path, "absent", 0, 0, 0))
            continue
        try:
            con = sqlite3.connect(path)
            con.execute("PRAGMA journal_mode=WAL")
            result = con.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise MigrationError(f"{path}: integrity_check said {result!r} — refusing to migrate")
        except sqlite3.DatabaseError as ex:
            raise MigrationError(f"{path}: not a usable SQLite database ({ex})") from ex
        stamp = con.execute("PRAGMA user_version").fetchone()[0]
        applied = 0
        try:
            with con:  # one transaction per database; the stamp commits with the steps
                for version, fn in steps:
                    if version > stamp:
                        fn(con)
                        applied += 1
                if stamp != SCHEMA_VERSION:
                    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        except sqlite3.Error as ex:
            raise MigrationError(f"{path}: migration step failed ({ex})") from ex
        finally:
            con.close()
        reports.append(MigrateReport(path, "ok", stamp, SCHEMA_VERSION, applied))
    return reports
