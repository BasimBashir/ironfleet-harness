"""The live agent/LLM log (harness/live.py): one JSONL per matter under <store>/live,
written while a turn runs (opencode events line by line, gate calls start/end) and
tailed by GET /matters/{mid}/live; GET /usage totals per provider/model and per user."""
from __future__ import annotations

import json
import sys

import pytest

from harness import live
from harness.trace import DispatchRecord, TraceStore


def test_append_creates_missing_dirs_and_reads_back(tmp_path):
    root = tmp_path / "not" / "yet"                       # nothing exists on disk
    live.append(root, "m-1", "turn.start", prompt="go")
    live.append(root, "m-1", "agent", event={"type": "text", "part": {"text": "hi"}})
    recs, end = live.read_from(root, "m-1", 0)
    assert [r["kind"] for _, r in recs] == ["turn.start", "agent"]
    assert end == live.path(root, "m-1").stat().st_size and recs[-1][0] == end
    assert recs[0][1]["prompt"] == "go" and recs[0][1]["ts"]


def test_current_agent_rides_every_record(tmp_path):
    live.current["m-2"] = {"agent": "hunter", "session_id": "s1", "model": "gate/x"}
    try:
        live.append(tmp_path, "m-2", "llm.start", provider="p")
    finally:
        live.current.pop("m-2")
    (_, rec), = live.read_from(tmp_path, "m-2", 0)[0]
    assert rec["agent"] == "hunter" and rec["session_id"] == "s1" and rec["provider"] == "p"


def test_path_never_escapes_the_live_dir(tmp_path):
    assert live.path(tmp_path, "../../etc/x").parent == tmp_path / "live"
    assert live.path(tmp_path, "eval:case 1").name == "eval_case_1.jsonl"
    for bad in ("", "..", "."):
        with pytest.raises(ValueError):
            live.path(tmp_path, bad)
    live.append(tmp_path, "..", "x")                      # a writer never raises
    assert not (tmp_path / "live").exists()


def test_read_edges_missing_partial_shrunk(tmp_path):
    assert live.read_from(tmp_path, "m-3", None) == ([], 0)     # no file yet
    live.append(tmp_path, "m-3", "a")
    p = live.path(tmp_path, "m-3")
    with open(p, "a", encoding="utf-8", newline="") as f:
        f.write('{"kind": "half')                               # a write in progress
    recs, end = live.read_from(tmp_path, "m-3", 0)
    assert [r["kind"] for _, r in recs] == ["a"]                # the half line waits
    with open(p, "a", encoding="utf-8", newline="") as f:
        f.write('"}\n')
    recs, end2 = live.read_from(tmp_path, "m-3", end)
    assert [r["kind"] for _, r in recs] == ["half"] and end2 > end
    p.write_text("", encoding="utf-8")                          # re-created / truncated
    live.append(tmp_path, "m-3", "b")
    recs, _ = live.read_from(tmp_path, "m-3", end2)
    assert [r["kind"] for _, r in recs] == ["b"]


def test_first_connect_replays_only_the_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "REPLAY_BYTES", 120)
    for i in range(20):
        live.append(tmp_path, "m-4", "k", i=i)
    recs, end = live.read_from(tmp_path, "m-4", None)
    assert recs and recs[-1][1]["i"] == 19 and recs[0][1]["i"] > 0   # whole lines only
    assert end == live.path(tmp_path, "m-4").stat().st_size


def test_run_opencode_hands_each_line_over_while_the_child_runs(tmp_path, monkeypatch):
    """The child prints one event, then waits for proof the parent saw it: only a
    line-by-line drain lets it print 'seen' (a read-to-EOF drain gives 'late')."""
    import harness.substrate.run as run_mod
    flag = tmp_path / "flag"
    child = ("import json,os,time,sys\n"
             "print(json.dumps({'type':'step_start'}), flush=True)\n"
             f"f={str(flag)!r}\n"
             "t=time.time()\n"
             "while not os.path.exists(f) and time.time()-t<10: time.sleep(0.05)\n"
             "print(json.dumps({'type':'text','part':{'text':'seen' if os.path.exists(f) else 'late'}}))\n")
    monkeypatch.setattr(run_mod, "opencode_cmd", lambda: [sys.executable, "-c", child])
    got = []

    def on_line(line):
        got.append(json.loads(line))
        flag.touch()
    code, out = run_mod.run_opencode(tmp_path, [], timeout=30, on_line=on_line)
    assert code == 0
    assert [e["type"] for e in got] == ["step_start", "text"]
    assert got[1]["part"]["text"] == "seen"
    assert run_mod.parse_events(out) == got                     # the return value is unchanged


@pytest.mark.asyncio
async def test_gate_logs_each_llm_call_with_thinking_and_ms(tmp_path):
    from harness.gate import LLMRequest
    from test_gate import _gate

    async def transport(provider, payload):
        return {"model": payload["model"],
                "choices": [{"finish_reason": "tool_calls", "message": {
                    "content": "answer", "reasoning_content": "because s 9",
                    "tool_calls": [{"function": {"name": "search", "arguments": "{}"}}]}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3,
                          "completion_tokens_details": {"reasoning_tokens": 2}}}
    gate = _gate(tmp_path, transport)
    await gate.dispatch(LLMRequest(matter_ref="M-9", task_class="drafting",
                                   messages=[{"role": "user", "content": "draft it"}]))
    recs = [r for _, r in live.read_from(tmp_path, "M-9", 0)[0]]
    assert [r["kind"] for r in recs] == ["llm.start", "llm.end"]
    start, end = recs
    assert start["provider"] == "mini1" and start["input"]["content"] == "draft it"
    assert end["status"] == "ok" and end["tokens_in"] == 12 and end["tokens_reasoning"] == 2
    assert end["reasoning"] == "because s 9" and end["content"] == "answer"
    assert end["tool_calls"][0]["function"]["name"] == "search" and end["ms"] >= 0


@pytest.mark.asyncio
async def test_gate_logs_a_failed_call(tmp_path):
    from harness.gate import LLMRequest
    from test_gate import _gate

    async def boom(provider, payload):
        raise RuntimeError("upstream 503")
    gate = _gate(tmp_path, boom)
    with pytest.raises(Exception):
        await gate.dispatch(LLMRequest(matter_ref="M-8", task_class="drafting",
                                       messages=[{"role": "user", "content": "x"}]))
    ends = [r for _, r in live.read_from(tmp_path, "M-8", 0)[0] if r["kind"] == "llm.end"]
    assert ends and all(r["status"] == "error" and "503" in r["error"] for r in ends)


def _sse(text):
    return [(int(b.split("id: ")[1].split("\n")[0]), json.loads(b.split("data: ")[1]))
            for b in text.split("\n\n") if b.startswith("id: ")]


def test_live_route_streams_and_resumes(api_world):
    w = api_world
    mid = w.A["mid"]
    live.append(w.root, mid, "turn.start", agent="clerk", prompt="p")
    live.append(w.root, mid, "llm.end", agent="clerk", ms=40, status="ok")
    r = w.client.get(f"/api/v1/matters/{mid}/live", headers=w.h("reader"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    frames = _sse(r.text)
    assert [d["kind"] for _, d in frames] == ["turn.start", "llm.end"]
    assert "event: llm.end" in r.text
    again = w.client.get(f"/api/v1/matters/{mid}/live",
                         headers={**w.h("reader"), "Last-Event-ID": str(frames[0][0])})
    assert [d["kind"] for _, d in _sse(again.text)] == ["llm.end"]


def test_live_route_with_no_log_yet_is_an_empty_stream(api_world):
    r = api_world.client.get(f"/api/v1/matters/{api_world.B['mid']}/live",
                             headers=api_world.h("admin"))
    assert r.status_code == 200 and _sse(r.text) == []


def test_usage_per_model_and_per_user(api_world):
    w = api_world
    t = TraceStore(w.root / "trace.db")

    def rec(matter, prov, model, tin, tout, ms, status="ok", think=0):
        t.append(DispatchRecord(matter_ref=matter, task_class="drafting",
                                classification="LOCAL_ONLY", provider=prov, model=model,
                                tokens_in=tin, tokens_out=tout, tokens_reasoning=think,
                                latency_ms=ms, status=status))
    rec(w.A["mid"], "nim", "big", 100, 10, 1000, think=4)
    rec(w.B["mid"], "nim", "big", 50, 5, 500)
    rec(w.A["mid"], "ollama", "small", 7, 3, 70, status="error")
    rec("eval:x", "ollama", "small", 1, 1, 10)
    body = w.client.get("/api/v1/usage", headers=w.h("admin")).json()
    assert body["total"] == {"calls": 4, "errors": 1, "in": 158, "out": 19, "thinking": 4,
                             "cache": 0, "ms": 1580, "all": 177}
    by_model = {(r["provider"], r["model"]): r for r in body["by_model"]}
    assert by_model[("nim", "big")]["calls"] == 2 and by_model[("nim", "big")]["ms"] == 1500
    assert by_model[("ollama", "small")]["errors"] == 1
    by_user = {r["user"]: r for r in body["by_user"]}
    assert by_user["admin"]["calls"] == 3 and by_user["admin"]["all"] == 175   # A + B are admin's
    assert by_user["(no matter)"]["calls"] == 1
