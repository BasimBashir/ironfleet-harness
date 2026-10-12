"""S7i: per-agent memory canon, versioned and benchmarked (spec 12 §§3.1-3.4).

Three responsibilities live here and nowhere else: the SQLite canon (current body,
append-only snapshots, proposals, benchmark legs, probe suites), the delimited-section
rendering that projects canon into generated agent files, and the keep-if-better
comparator. The corpus body above the markers is NEVER stored, never editable, never
rendered by this module — protected fields by construction (spec §3.1).

The mount reads (open_existing, never creating); the CLI writes. A mount against a
missing store is genesis, not an error (spec §5).
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness.paths import resolve_store_root

MAX_MEMORY_CHARS = 2000        # canon cap — the reflector prompt promises it, the store enforces it
PROBE_SIZE = 5                 # per-agent screen subset; selection is seeded once (spec §3.1)
BEGIN_PREFIX = "<!-- ironfleet:memory:"         # followed by f"v{version} begin -->"
END_MARKER = "<!-- ironfleet:memory end -->"
AXES = ("mean_citations", "mean_grounding", "mean_persona")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_memory(
  agent TEXT PRIMARY KEY, body TEXT NOT NULL DEFAULT '',
  version INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_versions(
  agent TEXT, version INTEGER, body TEXT, created_at TEXT, reason TEXT,
  PRIMARY KEY(agent, version));
CREATE TABLE IF NOT EXISTS agent_edit_proposals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, body TEXT, status TEXT,
  reason TEXT DEFAULT '', proposed_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS benchmark_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, proposal_id INTEGER, stage TEXT,
  leg TEXT, n_cases INTEGER, n_scored INTEGER,
  mean_citations REAL, mean_grounding REAL, mean_persona REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS agent_probe_suites(
  agent TEXT PRIMARY KEY, case_ids TEXT NOT NULL, created_at TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def select_probe(agent: str, case_ids: list[str], k: int = PROBE_SIZE) -> list[str]:
    """Deterministic per-agent subset (spec §3.1): sort by sha256(f"{agent}:{case_id}"), take k.
    Same agent name → same subset forever; the suite is recorded at genesis and never re-selected."""
    selected = sorted(case_ids,
                      key=lambda cid: hashlib.sha256(f"{agent}:{cid}".encode("utf-8")).hexdigest())[:k]
    return sorted(selected)   # lexical: the stored suite and fresh selections must compare equal


@dataclass
class LegMeans:
    """One leg's per-axis means over its n_cases (spec §3.4 as tightened in the plan's Global
    Constraints: unscored cases cost their score — sum(scored axes)/n_cases)."""
    n_cases: int
    n_scored: int
    mean_citations: float
    mean_grounding: float
    mean_persona: float


class MemoryStore:
    """The canon. One row per persona in agent_memory; everything else hangs off it."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._db = sqlite3.connect(str(self.db_path))
        self._db.row_factory = sqlite3.Row

    @classmethod
    def at_store_root(cls) -> "MemoryStore":
        root, _source = resolve_store_root()
        return cls(root / "agent_memory.db")

    @classmethod
    def open_existing(cls, db_path: Path) -> "MemoryStore | None":
        """The mount's read path: None when the store does not exist yet — never create from a
        mount (spec §5: the mount reads, the CLI writes)."""
        if not Path(db_path).exists():
            return None
        return cls(db_path)

    # --- genesis ---
    def init(self, persona_names: list[str]) -> None:
        self._db.executescript(_SCHEMA)
        for name in persona_names:
            self._db.execute(
                "INSERT OR IGNORE INTO agent_memory(agent, body, version, updated_at) "
                "VALUES (?, '', 0, ?)", (name, _now()))
        self._db.commit()

    # --- canon ---
    def get(self, agent: str) -> tuple[str, int]:
        row = self._db.execute(
            "SELECT body, version FROM agent_memory WHERE agent = ?", (agent,)).fetchone()
        return ("", 0) if row is None else (row["body"], row["version"])

    def set(self, agent: str, body: str, reason: str) -> int:
        """New version: canon updated AND full snapshot appended. History is never rewritten;
        revert (CLI) writes old bytes forward as a new version."""
        _body, version = self.get(agent)
        version += 1
        with self._db:
            self._db.execute("INSERT INTO memory_versions(agent, version, body, created_at, reason) "
                             "VALUES (?, ?, ?, ?, ?)", (agent, version, body, _now(), reason))
            self._db.execute("UPDATE agent_memory SET body = ?, version = ?, updated_at = ? "
                             "WHERE agent = ?", (body, version, _now(), agent))
        return version

    def versions(self, agent: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT version, body, created_at, reason FROM memory_versions "
            "WHERE agent = ? ORDER BY version DESC", (agent,)).fetchall()
        return [dict(r) for r in rows]

    # --- probe suites ---
    def seed_suite(self, agent: str, case_ids: list[str]) -> None:
        """Genesis is the only writer: an existing suite means a caller is trying to invalidate
        recorded comparisons — refuse (spec §3.1)."""
        try:
            with self._db:
                self._db.execute("INSERT INTO agent_probe_suites(agent, case_ids, created_at) "
                                 "VALUES (?, ?, ?)", (agent, repr(sorted(case_ids)), _now()))
        except sqlite3.IntegrityError as ex:
            raise RuntimeError(f"{agent}: probe suite already seeded — genesis is the only "
                               f"writer (spec §3.1)") from ex

    def suite(self, agent: str) -> list[str]:
        row = self._db.execute("SELECT case_ids FROM agent_probe_suites WHERE agent = ?",
                               (agent,)).fetchone()
        return list(eval(row["case_ids"])) if row else []   # noqa: S307 — repr of a list we wrote
