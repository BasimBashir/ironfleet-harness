# tests/test_trace_identity.py
"""Finding F1: DispatchRecord carried only matter_ref, so D-T3's per-agent token
ledger and the session store's JSONL join had nothing to join ON. Additive
agent + session_id columns, the S7d `backend` migration's precedent: in-place,
by-name row reads, old rows read '' — the honest value (identity was never
recorded, so '' is what the truth looks like)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harness.trace import DispatchRecord, TraceStore


def _rec(**kw):
    base = dict(matter_ref="m1", task_class="extraction",
                classification="LOCAL_PREFERRED", provider="nvidia-nim",
                model="step-5", tokens_in=10, tokens_out=5)
    base.update(kw)
    return DispatchRecord(**base)


def test_agent_and_session_identity_land_on_the_row(tmp_path):
    store = TraceStore(tmp_path / "t.db")
    rid = store.append(_rec(agent="hunter", session_id="ses-1"))
    row = store.get(rid)
    assert row.agent == "hunter" and row.session_id == "ses-1"


def test_identity_defaults_to_empty_not_missing(tmp_path):
    """A dispatch without identity must still record — '' is honest ('never
    recorded'), and readers must never crash on the missing case."""
    store = TraceStore(tmp_path / "t.db")
    rid = store.append(_rec())
    row = store.get(rid)
    assert row.agent == "" and row.session_id == ""


def test_by_session_joins_turns(tmp_path):
    store = TraceStore(tmp_path / "t.db")
    store.append(_rec(session_id="ses-1", agent="hunter"))
    store.append(_rec(session_id="ses-1", agent="hunter"))
    store.append(_rec(session_id="ses-2", agent="clerk"))
    assert len(store.by_session("ses-1")) == 2
    assert len(store.by_session("ses-2")) == 1
    assert store.by_session("ses-nope") == []


def test_legacy_store_upgrades_in_place(tmp_path):
    """The S7d precedent, re-proven for identity: a store written by the OLD
    schema (no agent/session_id columns) is upgraded by the live run itself,
    and its old rows read back '' rather than erroring."""
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE dispatches(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
          matter_ref TEXT, task_class TEXT, classification TEXT,
          provider TEXT, model TEXT, weights_revision TEXT, engine TEXT,
          verified INTEGER, tokens_in INTEGER, tokens_out INTEGER,
          tokens_cache INTEGER, latency_ms INTEGER, status TEXT, error TEXT);
        -- Written the way TraceStore.append writes: EVERY column named, strings
        -- for text fields. A synthetic NULL row would be an unrealistic fixture
        -- (real legacy stores never contain NULLs) and would prove nothing.
        INSERT INTO dispatches(ts, matter_ref, task_class, classification, provider,
          model, weights_revision, engine, verified, tokens_in, tokens_out,
          tokens_cache, latency_ms, status, error)
          VALUES('2026-10-19T00:00:00Z', 'm-old', 'extraction', 'LOCAL_PREFERRED',
                 'ollama-local', 'thomson1', '', '', 0, 7, 3, 0, 12, 'ok', '');
    """)
    con.commit(); con.close()

    store = TraceStore(db)                      # the live run opens the old store
    rows = store.by_matter("m-old")
    assert len(rows) == 1
    assert rows[0].agent == "" and rows[0].session_id == ""   # honest, not an error
    rid = store.append(_rec(agent="hunter", session_id="ses-1"))
    assert store.get(rid).agent == "hunter"                  # new rows carry identity
