# tests/test_trace.py
from harness.trace import TraceStore, DispatchRecord

def _rec(**kw):
    base = dict(matter_ref="M-001", task_class="drafting", classification="LOCAL_PREFERRED",
                provider="mini1-mlx", model="qwen-30b", weights_revision="rev-abc", engine="mlx-lm",
                verified=1, tokens_in=10, tokens_out=5, tokens_cache=0, latency_ms=120, status="ok")
    base.update(kw)
    return DispatchRecord(**base)

def test_append_and_get(tmp_path):
    ts = TraceStore(tmp_path / "trace.db")
    did = ts.append(_rec())
    got = ts.get(did)
    assert got.matter_ref == "M-001" and got.verified == 1 and got.weights_revision == "rev-abc"

def test_by_matter_and_summary(tmp_path):
    ts = TraceStore(tmp_path / "trace.db")
    ts.append(_rec())                                   # local ok
    ts.append(_rec(provider="cloud-x", engine="cloud", classification="CLOUD_PERMITTED"))
    ts.append(_rec(status="error", error="429"))
    rows = ts.by_matter("M-001")
    assert len(rows) == 3
    s = ts.summary()
    assert s["dispatches"] == 3 and s["errors"] == 1
    assert s["by_engine"]["mlx-lm"] == 1 and s["by_engine"]["cloud"] == 1
