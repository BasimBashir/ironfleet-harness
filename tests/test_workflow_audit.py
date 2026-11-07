"""M4 commit 2: the hash-chained audit log — append-only by trigger, tamper
detection by verify(). stdlib hashlib only."""
from __future__ import annotations

import sqlite3

import pytest

from harness.workflow import audit
from harness.workflow.db import connect


@pytest.fixture
def con(tmp_path):
    c = connect(tmp_path / "platform.db")
    yield c
    c.close()


def test_append_builds_a_verifying_chain(con):
    for i in range(5):
        audit.append(con, matter_id="m1", actor="tester", action="task.completed",
                     target=f"t{i}", inputs_digest="in", outputs_digest="out")
    ok, bad = audit.verify(con)
    assert ok and bad is None
    rows = con.execute("SELECT prev_hash, hash FROM audit_events ORDER BY rowid").fetchall()
    assert rows[0]["prev_hash"] == "0" * 64
    for prev, cur in zip(rows, rows[1:]):
        assert cur["prev_hash"] == prev["hash"]


def test_update_and_delete_raise_via_triggers(con):
    aid = audit.append(con, matter_id="m1", actor="a", action="execution.started",
                       target="e1", inputs_digest="", outputs_digest="")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE audit_events SET target='x' WHERE audit_id=?", (aid,))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM audit_events WHERE audit_id=?", (aid,))


def test_tampered_row_is_named_by_verify(con):
    ids = [audit.append(con, matter_id="m1", actor="a", action="task.completed",
                        target=f"t{i}", inputs_digest="", outputs_digest="")
           for i in range(4)]
    # an attacker with the file drops the triggers and edits one row
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("DROP TRIGGER audit_no_delete")
    con.execute("UPDATE audit_events SET target='forged' WHERE audit_id=?", (ids[2],))
    con.commit()
    ok, bad = audit.verify(con)
    assert not ok and bad == ids[2]


def test_deleted_middle_row_is_named_by_verify(con):
    ids = [audit.append(con, matter_id="m1", actor="a", action="task.completed",
                        target=f"t{i}", inputs_digest="", outputs_digest="")
           for i in range(4)]
    con.execute("DROP TRIGGER audit_no_update")
    con.execute("DROP TRIGGER audit_no_delete")
    con.execute("DELETE FROM audit_events WHERE audit_id=?", (ids[1],))
    con.commit()
    ok, bad = audit.verify(con)
    assert not ok and bad == ids[2]      # the row after the gap breaks the chain
