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


class ProposalRejected(ValueError):
    """A proposal that touches the delimiter namespace or blows the size cap (spec §3.1)."""


def validate_proposal(body: str) -> str:
    if BEGIN_PREFIX in body or END_MARKER in body:
        raise ProposalRejected("proposal embeds a memory delimiter — rejected before it can "
                               "ever nest or forge a section boundary")
    if len(body) > MAX_MEMORY_CHARS:
        raise ProposalRejected(f"oversize: {len(body)} > MAX_MEMORY_CHARS({MAX_MEMORY_CHARS})")
    return body


def render_appendix(body: str, version: int) -> str:
    return f"{BEGIN_PREFIX}v{version} begin -->\n{body.rstrip()}\n{END_MARKER}\n"


def apply_to_agent_md(md: str, body: str, version: int) -> str:
    """Idempotent full-section replace (spec §3.2). No markers → append; markers present →
    replace the span (a begin without an end is stale/corrupt and is rewritten from begin to
    EOF — nothing may follow the section by construction). Empty body REMOVES the section."""
    lines = md.splitlines(keepends=True)
    start = next((i for i, l in enumerate(lines) if l.startswith(BEGIN_PREFIX)), None)
    if start is None:
        return md if not body else md.rstrip("\n") + "\n\n" + render_appendix(body, version)
    end = next((i for i in range(start, len(lines))
                if lines[i].startswith(END_MARKER)), len(lines) - 1)
    head = "".join(lines[:start]).rstrip("\n")
    if not body:
        return head + "\n" if head else ""
    return head + "\n\n" + render_appendix(body, version)


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

    # --- proposals ---
    def propose(self, agent: str, body: str) -> int:
        if self._db.execute("SELECT 1 FROM agent_memory WHERE agent = ?",
                            (agent,)).fetchone() is None:
            raise ValueError(f"unknown agent {agent!r} — genesis (init) first")
        cur = self._db.execute(
            "INSERT INTO agent_edit_proposals(agent, body, status, proposed_at) "
            "VALUES (?, ?, 'pending', ?)", (agent, body, _now()))
        self._db.commit()
        return int(cur.lastrowid)

    def proposal(self, proposal_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM agent_edit_proposals WHERE id = ?",
                               (proposal_id,)).fetchone()
        return dict(row) if row else None

    def decide(self, proposal_id: int, status: str, reason: str = "") -> None:
        if status not in ("kept", "rolled_back", "rejected"):
            raise ValueError(f"bad decision status {status!r}")
        with self._db:
            self._db.execute(
                "UPDATE agent_edit_proposals SET status = ?, reason = ?, decided_at = ? "
                "WHERE id = ?", (status, reason, _now(), proposal_id))

    # --- benchmark legs ---
    def record_leg(self, agent: str, proposal_id: int | None, stage: str, leg: str,
                   means: LegMeans) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO benchmark_runs(agent, proposal_id, stage, leg, n_cases, n_scored,"
                " mean_citations, mean_grounding, mean_persona, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent, proposal_id, stage, leg, means.n_cases, means.n_scored,
                 means.mean_citations, means.mean_grounding, means.mean_persona, _now()))

    def legs(self, proposal_id: int, stage: str) -> dict[str, LegMeans]:
        rows = self._db.execute(
            "SELECT * FROM benchmark_runs WHERE proposal_id = ? AND stage = ?",
            (proposal_id, stage)).fetchall()
        return {r["leg"]: LegMeans(n_cases=r["n_cases"], n_scored=r["n_scored"],
                                   mean_citations=r["mean_citations"],
                                   mean_grounding=r["mean_grounding"],
                                   mean_persona=r["mean_persona"]) for r in rows}

    # --- audit ---
    def history(self, agent: str) -> list[dict]:
        versions = [{**v, "kind": "version"} for v in self.versions(agent)]
        rows = self._db.execute(
            "SELECT id, status, reason, proposed_at, decided_at FROM agent_edit_proposals "
            "WHERE agent = ? ORDER BY id DESC", (agent,)).fetchall()
        decisions = [{**dict(r), "kind": "decision"} for r in rows]
        return sorted(versions + decisions,
                      key=lambda e: e.get("created_at") or e.get("proposed_at") or "",
                      reverse=True)
