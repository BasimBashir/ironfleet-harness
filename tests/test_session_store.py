# tests/test_session_store.py
"""The session store is the R3 shell's memory: one JSONL per session (the durable
record, Claude-Code-shaped rows), a SQLite index for --list/--resume, and the jobs
table S7f deferred into this step. Colon-free ids are a Windows constraint, not a
preference — registry directory names forbid ':'."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.session.store import SessionStore, TurnRow


def _row(sid="ses-test", matter="m1", agent="hunter"):
    return TurnRow(ts="2026-10-19T00:00:00Z", session_id=sid, matter_ref=matter,
                   display="task", agent=agent, tools_used=["read"],
                   output_summary="done", docs_touched=[], trace_refs=[1])


def test_new_session_rejects_colons(tmp_path):
    s = SessionStore(tmp_path)
    with pytest.raises(ValueError, match="colon-free"):
        s.new_session("bad:ref")


def test_new_session_returns_colon_free_id(tmp_path):
    s = SessionStore(tmp_path)
    sid = s.new_session("m1", "first task")
    assert ":" not in sid and sid.startswith("ses-")
    assert (tmp_path / "sessions" / f"{sid}.jsonl").parent.is_dir()


def test_append_and_read_back_roundtrip(tmp_path):
    s = SessionStore(tmp_path)
    sid = s.new_session("m1", "first task")
    s.append_turn(_row(sid))
    s.append_turn(_row(sid, agent="clerk"))
    rows = s.turns(sid)
    assert [r.agent for r in rows] == ["hunter", "clerk"]
    # the JSONL is the durable record — one line per turn, parsed back
    lines = (tmp_path / "sessions" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["agent"] == "hunter"


def test_index_tracks_turns_and_last(tmp_path):
    s = SessionStore(tmp_path)
    a = s.new_session("m1")
    s.append_turn(_row(a))
    b = s.new_session("m2")
    s.append_turn(_row(b, matter="m2"))
    assert s.last() == b                     # newest overall
    assert s.last("m1") == a                 # filtered by matter
    listed = {r["session_id"]: r for r in s.sessions()}
    assert listed[a]["turns"] == 1
    assert listed[a]["matter_ref"] == "m1"


def test_turns_unknown_session_is_empty(tmp_path):
    s = SessionStore(tmp_path)
    assert s.turns("ses-nope") == []
    assert s.last() is None


def test_jobs_table_roundtrip(tmp_path):
    s = SessionStore(tmp_path)
    sid = s.new_session("m1")
    s.add_job(sid, "gather", "hunter", "running")
    s.add_job(sid, "draft", "clerk", "done", detail="handoff.md")
    js = s.jobs(sid)
    assert [(j["stage"], j["status"]) for j in js] == [("gather", "running"),
                                                       ("draft", "done")]


def test_sessions_list_is_ordered_newest_first(tmp_path):
    s = SessionStore(tmp_path)
    a = s.new_session("m1")
    b = s.new_session("m1")
    assert [r["session_id"] for r in s.sessions()] == [b, a]
