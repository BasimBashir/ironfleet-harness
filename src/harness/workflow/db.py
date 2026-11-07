# src/harness/workflow/db.py — platform.db (03 data model, the M4 subset)
"""One connection factory for platform.db. WAL + isolation_level=None: every
claim is an explicit BEGIN IMMEDIATE, so two owners on one file serialize at
the write lock and exactly one wins the task (tested)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS executions(
  execution_id TEXT PRIMARY KEY, matter_id TEXT, session_id TEXT, state TEXT,
  compiled_plan_json TEXT, input_task_text TEXT, current_wait_ref TEXT,
  started_at TEXT, ended_at TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  task_id TEXT PRIMARY KEY, execution_id TEXT, seq INTEGER, key TEXT,
  agent_id TEXT, instruction TEXT, approval_kind TEXT, state TEXT,
  lease_owner TEXT, lease_expires_at REAL, attempts INTEGER DEFAULT 0,
  max_attempts INTEGER DEFAULT 3, result_summary TEXT);
CREATE INDEX IF NOT EXISTS idx_tasks_exec ON tasks(execution_id, seq);
CREATE TABLE IF NOT EXISTS approvals(
  approval_id TEXT PRIMARY KEY, matter_id TEXT, execution_id TEXT, task_id TEXT,
  kind TEXT, request_payload_json TEXT, state TEXT, decided_by TEXT,
  decision_note TEXT, requested_at TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS audit_events(
  audit_id TEXT PRIMARY KEY, matter_id TEXT, actor TEXT, action TEXT, target TEXT,
  inputs_digest TEXT, outputs_digest TEXT, prev_hash TEXT, hash TEXT, ts TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
-- M5 case-lifecycle tables (docs/enterprise/07): same platform.db, additive only.
CREATE TABLE IF NOT EXISTS cases(
  matter_id TEXT PRIMARY KEY, state TEXT, lawyer_now INTEGER DEFAULT 0,
  lawyer_now_reason TEXT, needs_restrategy INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS case_events(
  event_id TEXT PRIMARY KEY, matter_id TEXT, event_type TEXT, event_date TEXT,
  payload_json TEXT, actor TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS idx_case_events_matter ON case_events(matter_id);
CREATE TABLE IF NOT EXISTS strategy_versions(
  matter_id TEXT, version INTEGER, file TEXT, why_changed TEXT,
  next_actions_json TEXT, actor TEXT, ts TEXT,
  PRIMARY KEY(matter_id, version));
CREATE TABLE IF NOT EXISTS proposals(
  proposal_id TEXT PRIMARY KEY, matter_id TEXT, what TEXT, why TEXT,
  asked_at_ts TEXT, response TEXT, responded_at_ts TEXT, actor TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS predictions(
  prediction_id TEXT PRIMARY KEY, matter_id TEXT, strategy_version INTEGER,
  claim TEXT, actor TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS outcomes(
  outcome_id TEXT PRIMARY KEY, prediction_id TEXT UNIQUE, match INTEGER,
  actual TEXT, court_date TEXT, actor TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS deadlines(
  deadline_id TEXT PRIMARY KEY, matter_id TEXT, what TEXT, due TEXT, rule TEXT,
  source TEXT, service_date TEXT, kind TEXT, status TEXT,
  missed_consequence TEXT, actor TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS idx_deadlines_matter ON deadlines(matter_id);
CREATE TABLE IF NOT EXISTS flaws(
  flaw_id TEXT, matter_id TEXT, class TEXT, severity TEXT, doc TEXT,
  status TEXT, detector TEXT, detail TEXT, actor TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS idx_flaws_matter ON flaws(matter_id, flaw_id);
CREATE TABLE IF NOT EXISTS facts(
  matter_id TEXT, field TEXT, op TEXT, value_json TEXT, actor TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS idx_facts_matter ON facts(matter_id, field);
CREATE TABLE IF NOT EXISTS evidence(
  evidence_id TEXT PRIMARY KEY, matter_id TEXT, op TEXT, label TEXT, file TEXT,
  sha256 TEXT, actor TEXT, ts TEXT);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open (and create) platform.db at `path`. WAL so a reader never blocks a
    claim; timeout=30 so a racing writer waits instead of raising."""
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con
