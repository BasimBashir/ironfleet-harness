"""S7i: the memory store, rendering, validation, comparator (spec 12 §§3.1-3.4)."""
from __future__ import annotations

import pytest

from harness.agent_memory import (MAX_MEMORY_CHARS, PROBE_SIZE, LegMeans, MemoryStore,
                                  select_probe)


@pytest.fixture()
def store(tmp_path):
    s = MemoryStore(tmp_path / "agent_memory.db")
    s.init(["adversary", "hunter"])
    return s


def test_genesis_is_idempotent_and_version_zero(store):
    store.init(["adversary", "hunter"])          # second call must not reset or duplicate
    assert store.get("adversary") == ("", 0)
    store.set("adversary", "note one", "first")
    store.init(["adversary", "hunter"])          # re-init keeps canon
    assert store.get("adversary") == ("note one", 1)


def test_set_bumps_version_and_snapshots_exact_bytes(store):
    assert store.set("adversary", "v1 body", "reason A") == 1
    assert store.set("adversary", "v2 body", "reason B") == 2
    chain = store.versions("adversary")
    assert [(v["version"], v["body"]) for v in chain] == [(2, "v2 body"), (1, "v1 body")]
    assert chain[1]["reason"] == "reason A"


def test_get_unknown_agent_is_genesis_shape(store):
    assert store.get("nobody") == ("", 0)


def test_open_existing_returns_none_without_db(tmp_path):
    assert MemoryStore.open_existing(tmp_path / "missing.db") is None
    s = MemoryStore(tmp_path / "agent_memory.db")
    s.init(["hunter"])
    assert MemoryStore.open_existing(tmp_path / "agent_memory.db") is not None


def test_probe_suite_is_deterministic_and_recorded_once(store):
    ids = [f"case-{i:02d}" for i in range(30)]
    store.seed_suite("adversary", select_probe("adversary", ids))
    first = store.suite("adversary")
    assert len(first) == PROBE_SIZE and set(first) <= set(ids)
    # same agent name → same selection (spec §3.1: re-selection would invalidate comparisons)
    assert select_probe("adversary", ids) == first
    # a different agent name selects a different subset (real spread, not the first 5 sorted)
    store.seed_suite("hunter", select_probe("hunter", ids))
    assert store.suite("hunter") != first
    with pytest.raises(RuntimeError):            # genesis is the only writer (spec §3.1)
        store.seed_suite("adversary", first)


def test_at_store_root_honours_harness_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_HOME", str(tmp_path))
    s = MemoryStore.at_store_root()
    s.init(["hunter"])
    assert (tmp_path / "agent_memory.db").exists()


def test_propose_and_decide_lifecycle(store):
    pid = store.propose("adversary", "proposed body")
    assert store.proposal(pid)["status"] == "pending"
    store.decide(pid, "kept", "confirm deltas")
    row = store.proposal(pid)
    assert row["status"] == "kept" and row["reason"] == "confirm deltas"
    assert row["decided_at"] is not None


def test_proposal_of_unknown_agent_refuses(store):
    with pytest.raises(ValueError):
        store.propose("nobody", "body")


def test_record_leg_and_read_back(store):
    pid = store.propose("adversary", "b")
    m = LegMeans(n_cases=5, n_scored=5, mean_citations=0.2, mean_grounding=0.4, mean_persona=1.0)
    store.record_leg("adversary", pid, "screen", "proposed", m)
    back = store.legs(pid, "screen")
    assert back["proposed"] == m
    assert store.legs(pid, "confirm") == {}


def test_history_merges_versions_and_decisions(store):
    pid = store.propose("adversary", "b")
    store.set("adversary", "kept body", f"proposal {pid} confirmed")
    store.decide(pid, "kept", "ok")
    entries = store.history("adversary")
    kinds = [e["kind"] for e in entries]
    assert set(kinds) == {"version", "decision"}
    assert any(e["kind"] == "decision" and e["status"] == "kept" for e in entries)
