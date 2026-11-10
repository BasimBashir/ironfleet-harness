# tests/test_migrate.py — M11 T2: the store migration mechanism.
"""02 §15's contract, made executable: additive-only migrations, one transaction
per database, versioned by PRAGMA user_version, fail loud on corruption, never
create a store the owning class would create. Rollback stays "restore backup"
(migrate never rewrites history and the drill proves the restore path)."""
from __future__ import annotations

import sqlite3

import pytest

from harness.migrate import SCHEMA_VERSION, MigrationError, migrate


def _legacy_trace(tmp_path):
    """A trace store written before S7d's `backend` and R3's identity columns."""
    db = tmp_path / "trace.db"
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE dispatches(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
      matter_ref TEXT, task_class TEXT, classification TEXT,
      provider TEXT, model TEXT, weights_revision TEXT, engine TEXT, verified INTEGER,
      tokens_in INTEGER, tokens_out INTEGER, tokens_cache INTEGER,
      latency_ms INTEGER, status TEXT, error TEXT);
    """)
    con.execute(
        "INSERT INTO dispatches(ts, matter_ref, task_class, classification, provider,"
        " model, weights_revision, engine, verified, tokens_in, tokens_out,"
        " tokens_cache, latency_ms, status, error)"
        " VALUES('2026-01-01T00:00:00Z','m1','extraction','LOCAL_ONLY','ollama',"
        " 'thomson1-chat:latest','', '', 0, 1, 2, 0, 5, 'ok', '')")
    con.commit()
    con.close()
    return db


def _cols(db):
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(dispatches)").fetchall()}
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    return cols, ver


def test_fresh_root_migrates_nothing(tmp_path):
    # migrate never creates a store: the owning class creates it on first open.
    reports = migrate(tmp_path)
    assert {r.status for r in reports} == {"absent"}
    assert list(tmp_path.iterdir()) == []


def test_legacy_trace_db_gains_columns(tmp_path):
    db = _legacy_trace(tmp_path)
    migrate(tmp_path)
    cols, ver = _cols(db)
    assert {"backend", "agent", "session_id", "tokens_reasoning"} <= cols
    assert ver == SCHEMA_VERSION
    # the legacy row survives, reading the honest defaults
    con = sqlite3.connect(db)
    row = con.execute("SELECT backend, agent, tokens_reasoning FROM dispatches").fetchone()
    con.close()
    assert row == ("", "", 0)


def test_current_trace_db_is_noop_and_idempotent(tmp_path):
    from harness.trace import TraceStore
    TraceStore(tmp_path / "trace.db")  # constructor creates + heals the schema
    first = migrate(tmp_path)
    second = migrate(tmp_path)
    assert first[0].status == "ok" and second[0].status == "ok"
    assert second[0].steps_applied == 0, "re-running migrate on a current store must apply nothing"
    _, ver = _cols(tmp_path / "trace.db")
    assert ver == SCHEMA_VERSION


def test_corrupt_db_fails_loud_naming_the_path(tmp_path):
    (tmp_path / "trace.db").write_bytes(b"not a database at all")
    with pytest.raises(MigrationError) as ei:
        migrate(tmp_path)
    assert str(tmp_path / "trace.db") in str(ei.value)


def test_platform_db_stamped_and_audit_chain_intact(tmp_path):
    from harness.workflow.audit import append as audit_append, verify as audit_verify
    from harness.workflow.db import connect
    con = connect(tmp_path / "platform.db")
    audit_append(con, matter_id="m1", actor="tester", action="test", target="t",
                 inputs_digest="i", outputs_digest="o")
    con.close()
    reports = migrate(tmp_path)
    assert [r for r in reports if r.path.name == "platform.db"][0].status == "ok"
    con = connect(tmp_path / "platform.db")
    ok, why = audit_verify(con)
    con.close()
    assert ok and why is None, why


def test_cli_migrate_exit_codes(tmp_path):
    from harness.cli import main as cli_main
    assert cli_main(["migrate", "--root", str(tmp_path)]) == 0
    (tmp_path / "trace.db").write_bytes(b"garbage")
    assert cli_main(["migrate", "--root", str(tmp_path)]) == 1
