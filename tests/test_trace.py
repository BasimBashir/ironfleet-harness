# tests/test_trace.py
import sqlite3

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
    assert s["by_engine"]["mlx-lm"] == 2 and s["by_engine"]["cloud"] == 1   # rec 3 keeps engine=mlx-lm

# The dispatches table EXACTLY as it existed before S7d (trace.py at b9590b9).
LEGACY_DDL = """CREATE TABLE dispatches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
  matter_ref TEXT, task_class TEXT, classification TEXT,
  provider TEXT, model TEXT, weights_revision TEXT, engine TEXT, verified INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, tokens_cache INTEGER,
  latency_ms INTEGER, status TEXT, error TEXT);"""

def _seed_legacy(db):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(LEGACY_DDL)
    con.execute(
        "INSERT INTO dispatches(ts,matter_ref,task_class,classification,provider,model,"
        "weights_revision,engine,verified,tokens_in,tokens_out,tokens_cache,latency_ms,status,error)"
        " VALUES('2026-09-22T00:00:00+00:00','M-old','drafting','LOCAL_PREFERRED',"
        "'ollama-local','thomson1-chat:latest','','',0,1,1,0,5,'ok','')")
    con.commit()
    con.close()

def _columns(db):
    con = sqlite3.connect(db)
    try:
        return [r[1] for r in con.execute("PRAGMA table_info(dispatches)").fetchall()]
    finally:
        con.close()

def test_legacy_db_migrates_backend_column_in_place(tmp_path):
    db = tmp_path / "trace.db"
    _seed_legacy(db)
    ts = TraceStore(db)                      # opens the LEGACY DB — must migrate, not crash
    assert _columns(db).count("backend") == 1
    did = ts.append(_rec(backend="llamacpp-b123", engine="llamacpp"))   # new writes carry backend
    assert ts.get(did).backend == "llamacpp-b123"
    legacy = ts.by_matter("M-old")           # old rows survive, backend honestly ''
    assert len(legacy) == 1 and legacy[0].backend == "" and legacy[0].provider == "ollama-local"

def test_fresh_and_migrated_dbs_read_identically(tmp_path):
    # _row must resolve by column NAME: ALTER TABLE appends `backend` at the END, so a
    # migrated DB's column order differs from a fresh DB's — positional zip would
    # silently misalign one of them.
    fresh = TraceStore(tmp_path / "fresh.db")
    fresh.append(_rec())
    db = tmp_path / "migrated.db"
    _seed_legacy(db)
    mig = TraceStore(db)
    mig.append(_rec())
    assert fresh.by_matter("M-001")[0] == mig.by_matter("M-001")[0]

def test_migration_is_idempotent(tmp_path):
    db = tmp_path / "trace.db"
    _seed_legacy(db)
    TraceStore(db)
    TraceStore(db)                           # second open must not re-add the column
    assert _columns(db).count("backend") == 1


def test_attr_writes_agent_and_session_onto_the_span(tmp_path):
    """F1's columns are write-when-supplied; the SHELL owns the before/after span
    and attributes it post-turn — the meter's per-agent ledger reads these."""
    ts = TraceStore(tmp_path / "trace.db")
    a = ts.append(_rec())
    b = ts.append(_rec())
    ts.attr("hunter", "ses-1", [a, b])
    rows = ts.by_ids([a, b])
    assert all(r.agent == "hunter" and r.session_id == "ses-1" for r in rows)
    ts.attr("clerk", "ses-2", [])   # empty span: no-op, no crash
