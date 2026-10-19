"""The session layer's error log (the user's ruling: a caught error is recorded
with WHERE and WHY, never swallowed — a future failure is located from the log).

One small check per rule the module promises: the row carries location + cause +
line, a missing root still emits (stderr) instead of crashing, a torn line costs
one row, and record_error never raises even when the log is unwritable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.session.errors import FILENAME, read_errors, record_error


def test_row_carries_where_and_why(tmp_path):
    try:
        try:
            raise KeyError("inner cause")
        except KeyError as inner:
            raise RuntimeError("the outer failure") from inner
    except RuntimeError as exc:
        record_error(exc, where="session.factory.stage", root=tmp_path,
                     context={"stage": "draft"})

    rows = read_errors(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["where"] == "session.factory.stage"     # WHERE it happened
    assert row["exception"] == "RuntimeError" and row["message"] == "the outer failure"
    assert "KeyError" in row["cause"]                  # WHY (the chained cause)
    assert "raise RuntimeError" in row["line"]         # WHICH line
    assert row["context"] == {"stage": "draft"}


def test_missing_root_prints_instead_of_crashing(capsys):
    """The TUI catches before a store root exists — stderr beats silence."""
    try:
        raise ValueError("no store yet")
    except ValueError as exc:
        record_error(exc, where="session.tui.foo")     # no root -> stderr
    out = capsys.readouterr().err
    assert "[session-error]" in out and "no store yet" in out


def test_record_error_never_raises_on_unwritable_root(tmp_path):
    """Logging must not turn a caught error into a crash."""
    bad = tmp_path / "file-not-dir"
    bad.write_text("x", encoding="utf-8")
    try:
        raise ValueError("swallowed by a broken log target")
    except ValueError as exc:
        record_error(exc, where="session.cli.main", root=bad)   # no exception


def test_torn_line_costs_one_row(tmp_path):
    (tmp_path / FILENAME).write_text(
        json.dumps({"ts": "1", "where": "a"}) + "\n"
        + "{ this line is torn\n"
        + json.dumps({"ts": "2", "where": "b"}) + "\n",
        encoding="utf-8")
    rows = read_errors(tmp_path)
    assert [r["where"] for r in rows] == ["a", "b"]


def test_empty_log_reads_as_nothing(tmp_path):
    assert read_errors(tmp_path) == []
