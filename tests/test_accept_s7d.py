# tests/test_accept_s7d.py — the PURE parts of the S7d acceptance driver.
# main() drives real Ollama + the real opencode binary and is NEVER run in the suite.
import json, os, sqlite3
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data" / "opencode-a1"

def test_seed_legacy_db_then_tracestore_migrates_and_serves(tmp_path):
    from scripts.accept_s7d import seed_legacy_db, LEGACY_MATTER_REF
    db = tmp_path / "trace.db"
    seed_legacy_db(db)
    from harness.trace import TraceStore, DispatchRecord
    ts = TraceStore(db)                                    # migration happens here
    ts.append(DispatchRecord(matter_ref="m-new", task_class="drafting",
                             classification="LOCAL_PREFERRED", provider="ollama-local",
                             model="thomson1-chat:latest", backend="x", status="ok"))
    assert [r.backend for r in ts.by_matter(LEGACY_MATTER_REF)] == [""]   # legacy row honest
    assert ts.by_matter("m-new")[0].backend == "x"
    con = sqlite3.connect(db)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(dispatches)").fetchall()]
    finally:
        con.close()
    assert cols.count("backend") == 1

def test_check_mount_statics_passes_the_real_mount():
    from scripts.accept_s7d import check_mount_statics
    cfg = json.loads((DATA / "opencode.json").read_text(encoding="utf-8"))
    assert check_mount_statics(cfg, 7373) == []

@pytest.mark.parametrize("mutate,fragment", [
    (lambda c: c["provider"].update({"extra": {}}), "exactly one provider"),
    (lambda c: c["provider"]["gate-local"]["options"].pop("baseURL"), "baseURL"),
    (lambda c: c.update({"disabled_providers": []}), "disabled_providers"),
    (lambda c: c.update({"autoupdate": True}), "share/autoupdate"),
    (lambda c: c["agent"]["title"].update({"disable": False}), "title"),
    (lambda c: c["provider"]["gate-local"]["models"]["gate/extraction"].pop("limit"),
     "limit.context/output"),
])
def test_check_mount_statics_catches_mutations(mutate, fragment):
    from scripts.accept_s7d import check_mount_statics
    cfg = json.loads((DATA / "opencode.json").read_text(encoding="utf-8"))
    mutate(cfg)
    problems = check_mount_statics(cfg, 7373)
    assert problems and fragment in problems[0]

def test_adversarial_child_env_scrubs_and_restores_parent(monkeypatch, tmp_path):
    # The REAL child_env must run under injected credentials (reimplementing its body would
    # let the check and the scrub drift apart); the parent env must be restored afterwards.
    from scripts.accept_s7d import adversarial_child_env, ADVERSARIAL
    from scripts.stand_up_opencode import HARDEN_ENV
    from scripts.verify_opencode_mount import verify_child_env
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    env = adversarial_child_env(tmp_path)
    assert verify_child_env(env) == []            # nothing survived the scrub
    assert env["PWD"] == str(tmp_path) and all(env[k] == v for k, v in HARDEN_ENV.items())
    assert "AWS_ACCESS_KEY_ID" not in os.environ  # parent restored, no residue
