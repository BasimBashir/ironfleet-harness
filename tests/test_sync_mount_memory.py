"""S7i: memory projection into the synced mount (spec 12 §3.2).

Byte-locks under test: drive twins are NEVER touched (S7c parity comparability); a missing
store is genesis, not an error; sync_mount never creates the store (the mount reads, the CLI
writes)."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.agent_memory import (BEGIN_PREFIX, END_MARKER, MemoryStore,
                                  apply_to_agent_md)

MODULE_E = Path(__file__).resolve().parents[1] / "data" / "module-e"


@pytest.fixture()
def agent_dir(tmp_path):
    out = tmp_path / "agent"
    out.mkdir()
    # minimal stand-ins shaped exactly like generate_all writes them
    for name in ("adversary.md", "adversary-drive.md"):
        (out / name).write_text("---\ndescription: d\nmode: subagent\n---\nCORPUS\n",
                                encoding="utf-8")
    return out


def test_injection_hits_subagents_never_drive_twins(agent_dir, tmp_path):
    from scripts.stand_up_opencode import inject_memory
    store = MemoryStore(tmp_path / "agent_memory.db")
    store.init(["adversary"])
    store.set("adversary", "ALWAYS answer with a Sources section.", "test")
    inject_memory(agent_dir, MODULE_E / "personas.yaml", store)
    sub = (agent_dir / "adversary.md").read_text(encoding="utf-8")
    twin = (agent_dir / "adversary-drive.md").read_text(encoding="utf-8")
    assert "ALWAYS answer" in sub
    assert sub.count(BEGIN_PREFIX) == 1 and sub.rstrip().endswith(END_MARKER)
    assert twin == "---\ndescription: d\nmode: subagent\n---\nCORPUS\n"   # byte-exact twin


def test_injection_reprojects_on_resync(agent_dir, tmp_path):
    from scripts.stand_up_opencode import inject_memory
    store = MemoryStore(tmp_path / "agent_memory.db")
    store.init(["adversary"])
    store.set("adversary", "v1 note", "t")
    inject_memory(agent_dir, MODULE_E / "personas.yaml", store)
    store.set("adversary", "v2 note", "t")
    inject_memory(agent_dir, MODULE_E / "personas.yaml", store)   # resync of the same workspace
    sub = (agent_dir / "adversary.md").read_text(encoding="utf-8")
    assert sub.count(BEGIN_PREFIX) == 1 and "v2 note" in sub and "v1 note" not in sub


def test_missing_store_is_genesis_no_section_no_db_write(agent_dir, tmp_path):
    from scripts.stand_up_opencode import inject_memory
    inject_memory(agent_dir, MODULE_E / "personas.yaml", None)
    assert BEGIN_PREFIX not in (agent_dir / "adversary.md").read_text(encoding="utf-8")
    assert not (tmp_path / "agent_memory.db").exists()


def test_empty_canon_is_marker_less(agent_dir, tmp_path):
    from scripts.stand_up_opencode import inject_memory
    store = MemoryStore(tmp_path / "agent_memory.db")
    store.init(["adversary"])                      # genesis rows, empty canon
    inject_memory(agent_dir, MODULE_E / "personas.yaml", store)
    for f in agent_dir.glob("*.md"):
        assert BEGIN_PREFIX not in f.read_text(encoding="utf-8")
