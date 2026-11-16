"""M8 (D-3 pick: C's token meters on B; 05 §13 "now via the API"): token usage
per matter and per agent, read from <store>/trace.db dispatches — the same rows
the TUI meter aggregates. Read-only; a store with no trace.db reads as zeros."""
from __future__ import annotations

from harness.trace import DispatchRecord, TraceStore


def _rec(matter, agent, tin, tout, cache=0, reasoning=0):
    return DispatchRecord(matter_ref=matter, task_class="drafting",
                          classification="LOCAL_ONLY", provider="p", model="m",
                          tokens_in=tin, tokens_out=tout, tokens_cache=cache,
                          agent=agent, tokens_reasoning=reasoning)


def test_tokens_per_matter_and_agent(api_world):
    w = api_world
    t = TraceStore(w.root / "trace.db")
    t.append(_rec(w.A["mid"], "clerk", 100, 20, reasoning=5))
    t.append(_rec(w.A["mid"], "clerk", 50, 10))
    t.append(_rec(w.A["mid"], "hunter", 7, 3))
    t.append(_rec(w.B["mid"], "clerk", 999, 999))              # never leaks into A

    r = w.client.get(f"/api/v1/matters/{w.A['mid']}/tokens", headers=w.h("reader"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == {"in": 157, "out": 33, "cache": 0, "thinking": 5,
                             "all": 190, "dispatches": 3, "ms": 0}
    assert [(a["agent"], a["in"], a["out"], a["thinking"]) for a in body["agents"]] == [
        ("clerk", 150, 30, 5), ("hunter", 7, 3, 0)]

    rows = w.client.get("/api/v1/matters", headers=w.h("admin")).json()["items"]
    assert {m["matter_id"]: m["tokens_total"] for m in rows} == {
        w.A["mid"]: 190, w.B["mid"]: 1998}


def test_no_trace_store_reads_as_zero(api_world):
    w = api_world
    body = w.client.get(f"/api/v1/matters/{w.A['mid']}/tokens", headers=w.h("admin")).json()
    assert body["total"]["all"] == 0 and body["agents"] == []
