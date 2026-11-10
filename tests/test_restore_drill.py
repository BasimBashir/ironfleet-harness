# tests/test_restore_drill.py — M11 T3: the drill, run against fixture roots.
"""The live store is never touched here (or in production): every test drives
scripts/restore_drill.py main() against a tmp fixture root built with the real
store classes, asserting the pass path, the usage refusals, and the fail-loud
on a corrupt live store."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.restore_drill import main as drill


def _fixture_root(root: Path, with_trace: bool = True) -> None:
    from harness.trace import DispatchRecord, TraceStore
    from harness.workflow.audit import append as audit_append
    from harness.workflow.db import connect
    con = connect(root / "platform.db")
    audit_append(con, matter_id="m1", actor="tester", action="test", target="x",
                 inputs_digest="i", outputs_digest="o")
    con.close()
    if with_trace:
        TraceStore(root / "trace.db").append(DispatchRecord(
            matter_ref="m1", task_class="extraction", classification="LOCAL_ONLY",
            provider="ollama", model="thomson1-chat:latest"))
    (root / "matters" / "m1").mkdir(parents=True)
    (root / "matters" / "m1" / "matter.json").write_text("{}", encoding="utf-8")


def test_drill_roundtrip_passes(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    _fixture_root(root)
    bdir = tmp_path / "backup"
    assert drill(["--root", str(root), "--backup-dir", str(bdir)]) == 0
    manifest = json.loads((bdir / "manifest.json").read_text(encoding="utf-8"))
    assert {"platform.db", "trace.db", "matters/m1/matter.json"} <= set(manifest["files"])
    # the restored scratch root: audit chain intact, marker gone, migrate stamped
    scratch = bdir.with_name(bdir.name + "-restored")
    from harness.workflow.audit import verify as audit_verify
    from harness.workflow.db import connect
    con = connect(scratch / "platform.db")
    ok, why = audit_verify(con)
    n = con.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    ver = con.execute("PRAGMA user_version").fetchone()[0]
    con.close()
    assert ok and why is None and n == 1 and ver >= 1
    con = sqlite3.connect(scratch / "trace.db")
    assert con.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0] == 1
    con.close()


def test_drill_refuses_occupied_backup_dir(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    _fixture_root(root)
    bdir = tmp_path / "backup"
    bdir.mkdir()
    (bdir / "stale").write_text("x", encoding="utf-8")
    assert drill(["--root", str(root), "--backup-dir", str(bdir)]) == 2


def test_drill_refuses_missing_root(tmp_path):
    assert drill(["--root", str(tmp_path / "nope"), "--backup-dir",
                  str(tmp_path / "b")]) == 2


def test_drill_fails_loud_on_corrupt_live_store(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    # no TraceStore here: its constructor connection can outlive the call and
    # hold the Windows file lock. A plain sqlite3 db = no WAL sidecars either,
    # and real corruption has no sidecars to rescue the store from (a live WAL
    # resurrects a corrupted main file wholesale — SQLite recovers from them)
    _fixture_root(root, with_trace=False)
    victim = root / "trace.db"
    con = sqlite3.connect(victim)
    con.execute("CREATE TABLE dispatches(id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    victim.write_bytes(b"corrupted on the live side")
    bdir = tmp_path / "backup"
    assert drill(["--root", str(root), "--backup-dir", str(bdir)]) == 1
