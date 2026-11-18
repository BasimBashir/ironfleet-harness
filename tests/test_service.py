# tests/test_service.py — M3 commit 3, test-first: harness.service use-cases are
# drivable with NO Textual import (that is the extraction's point — the CLI or a
# future API can call the same functions). Existing test_session_tui /
# test_session_commands stay unchanged; they are the behaviour-preservation proof.
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from harness.service import split_plan
from harness.service.personas import add_persona
from harness.service.sessions import deliverables, dispatch_task, session_digest
from harness.service.system import provider_lines
from harness.session.store import SessionStore, TurnRow


# -- split_plan (moved verbatim from tui.py; tui re-exports it) -------------------

def test_split_plan_moves_the_fenced_block():
    text = "process the docs\n```plan\nstage|agent|prompt\n```\ntrailing note"
    task, plan = split_plan(text)
    assert plan.startswith("```plan") and plan.endswith("```")
    assert "stage|agent|prompt" in plan
    assert "process the docs" in task and "trailing note" in task
    assert "```plan" not in task


def test_split_plan_without_a_block_is_verbatim():
    assert split_plan("just process the docs") == ("just process the docs", "")


def test_split_plan_only_a_block_becomes_run_the_plan():
    task, plan = split_plan("```plan\na|b|c\n```")
    assert task == "(run the plan)"
    assert "a|b|c" in plan


# -- personas ---------------------------------------------------------------------

@pytest.fixture
def personas_yaml(tmp_path):
    p = tmp_path / "personas.yaml"
    p.write_text(yaml.safe_dump({"personas": []}, allow_unicode=True), encoding="utf-8")
    return p


def test_add_persona_appends_a_validated_row(personas_yaml):
    name = add_persona("hunter|hunts citations|spawn_agent|You are HUNTER.",
                       path=personas_yaml)
    assert name == "hunter"
    doc = yaml.safe_load(personas_yaml.read_text(encoding="utf-8"))
    row = doc["personas"][-1]
    assert row["name"] == "hunter"
    assert row["description"] == "hunts citations"
    assert row["allowed_tools"] == ["spawn_agent"]
    assert row["primary"] == "You are HUNTER."


def test_add_persona_rejects_a_bad_row_and_writes_nothing(personas_yaml):
    before = personas_yaml.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        add_persona("only-two-parts|here", path=personas_yaml)
    assert personas_yaml.read_text(encoding="utf-8") == before


def test_add_persona_rejects_unknown_tools(personas_yaml):
    with pytest.raises(ValueError):
        add_persona("x|d|not_a_real_tool|prompt", path=personas_yaml)


# -- sessions ---------------------------------------------------------------------

def _store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path / "store")


def _turn(sid: str, agent: str, display: str, summary: str) -> TurnRow:
    return TurnRow(ts="2026-11-05T00:00:00+00:00", session_id=sid,
                   matter_ref="m-test", display=display, agent=agent,
                   tools_used=[], output_summary=summary, docs_touched=[],
                   trace_refs=[])


def test_session_digest_prefers_the_last_checkpoint(tmp_path):
    store = _store(tmp_path)
    sid = store.new_session("m-test")
    store.append_turn(_turn(sid, "clerk", "a plain turn", "plain summary"))
    store.append_turn(_turn(sid, "compact", "/compact note", "CHECKPOINT SUMMARY"))
    digest = session_digest(store, tmp_path / "base", sid)
    assert "Last checkpoint: CHECKPOINT SUMMARY" in digest
    assert "plain summary" not in digest


def test_session_digest_falls_back_to_the_last_two_turns(tmp_path):
    store = _store(tmp_path)
    sid = store.new_session("m-test")
    store.append_turn(_turn(sid, "hunter", "t1", "first report"))
    store.append_turn(_turn(sid, "clerk", "t2", "second report"))
    store.append_turn(_turn(sid, "drafter", "t3", "third report"))
    digest = session_digest(store, tmp_path / "base", sid)
    assert "second report" in digest and "third report" in digest
    assert "first report" not in digest


def test_session_digest_lists_deliverables_and_caps(tmp_path):
    base = tmp_path / "base"
    sid_dir = base / "ses-x"
    (sid_dir / "hunter").mkdir(parents=True)
    (sid_dir / "hunter" / "notes.md").write_text("x", encoding="utf-8")
    (sid_dir / ".opencode" / "junk").mkdir(parents=True)
    (sid_dir / ".opencode" / "junk" / "hidden.md").write_text("x", encoding="utf-8")
    store = _store(tmp_path)
    sid = "ses-x"               # digest reads the base dir, not the store's session
    store.append_turn(_turn(sid, "hunter", "t1", "report"))
    digest = session_digest(store, base, sid)
    assert "hunter/notes.md" in digest
    assert "hidden.md" not in digest          # .opencode is skipped
    assert len(digest) <= 2000                # the seed cap


def test_session_digest_empty_without_turns(tmp_path):
    store = _store(tmp_path)
    sid = store.new_session("m-test")
    assert session_digest(store, tmp_path / "base", sid) == ""


def test_deliverables_globs_md_skipping_opencode(tmp_path):
    base = tmp_path / "base"
    sid_dir = base / "ses-x"
    (sid_dir / "hunter").mkdir(parents=True)
    (sid_dir / "hunter" / "a.md").write_text("x", encoding="utf-8")
    (sid_dir / ".opencode").mkdir(parents=True)
    (sid_dir / ".opencode" / "b.md").write_text("x", encoding="utf-8")
    found = deliverables(base, "ses-x")
    assert [f.name for f in found] == ["a.md"]


def test_dispatch_task_runs_the_factory_with_the_chair_args(tmp_path):
    store = _store(tmp_path)
    sid = store.new_session("m-test")
    store.append_turn(_turn(sid, "hunter", "t1", "prior report"))

    class _Driver:
        def __init__(self):
            self.store = store
            self.base = tmp_path / "base"

        def resume(self, session_id):
            return {"matter_ref": "m-test"}

    class _Runner:
        def __init__(self):
            self.driver = _Driver()
            self.calls = []

        async def run_task(self, session_id, matter_ref, task, **kw):
            self.calls.append((session_id, matter_ref, task, kw))
            return ["row"]

    runner = _Runner()
    notified = []
    rows = asyncio.run(dispatch_task(
        runner, sid, "run the plan\n```plan\na|b|c\n```",
        used=0, window=0, provider_name="gate",
        notify=lambda msg: notified.append(msg)))
    assert rows == ["row"]
    assert notified == []          # window 0 -> should_compact never fires
    (called_sid, matter_ref, task, kw), = runner.calls
    assert called_sid == sid and matter_ref == "m-test"
    assert task == "run the plan"
    assert kw["plan_text"].startswith("```plan")
    assert kw["complexity"] == "HIGH"
    assert kw["classification"] == "CLOUD_PERMITTED"
    assert "prior report" in kw["session_digest"]


def test_dispatch_task_notifies_before_a_real_compact(tmp_path, monkeypatch):
    store = _store(tmp_path)
    sid = store.new_session("m-test")
    store.append_turn(_turn(sid, "hunter", "t1", "report"))

    class _Driver:
        def __init__(self):
            self.store = store
            self.base = tmp_path / "base"

        def resume(self, session_id):
            return {"matter_ref": "m-test"}

    class _Runner:
        def __init__(self):
            self.driver = _Driver()
            self.calls = []

        async def run_task(self, *a, **kw):
            self.calls.append((a, kw))
            return []

    notified = []

    async def fake_compact(driver, session_id, **kw):
        return object()          # a checkpoint landed

    import harness.service.sessions as svc
    monkeypatch.setattr(svc, "maybe_compact", fake_compact)
    runner = _Runner()
    rows = asyncio.run(dispatch_task(runner, sid, "task", used=90, window=100,
                                     provider_name="gate",
                                     notify=lambda m: notified.append(m)))
    assert notified == ["auto-compacting…"]   # echoed BEFORE the long task runs
    assert rows == []
    assert runner.calls                       # run_task still ran afterwards


def test_dispatch_task_without_a_driver_returns_none(tmp_path):
    class _Runner:
        driver = None

    assert asyncio.run(dispatch_task(_Runner(), "ses-x", "task", used=0, window=0,
                                     provider_name="gate", notify=lambda m: None)) is None


# -- system -----------------------------------------------------------------------

def test_doctor_report_names_the_pin_and_providers(monkeypatch, tmp_path):
    import harness.service.system as sys_mod
    monkeypatch.setattr(sys_mod, "installed_version", lambda: "1.18.25")
    monkeypatch.setattr(sys_mod, "_provider_specs",
                        lambda: [{"name": "gate", "tier": "local", "context_window": 256000}])
    monkeypatch.setattr(sys_mod, "PINS", {"opencode": "opencode@1.18.25"})
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text(
        '{"autoupdate": false}', encoding="utf-8")
    # Path.home() resolves via os.path.expanduser("~") — patch the env, not the
    # class (a class patch does not survive expanduser on this box).
    monkeypatch.setattr(sys_mod, "_home", lambda: home)   # the doctor's single read point
    cfg_probe = home / ".config" / "opencode" / "opencode.jsonc"
    assert cfg_probe.is_file()
    assert '"autoupdate": false' in cfg_probe.read_text(encoding="utf-8")
    errors = []
    text = sys_mod.doctor_report(on_error=lambda where, exc: errors.append((where, exc)))
    assert "1.18.25" in text and "installed 1.18.25 OK" in text
    # a correctly-disabled autoupdate is OK (the 2026-11-17 Win11 test caught the
    # inverted bool the M3 move had preserved and this test had locked in)
    assert "autoupdate: false OK" in text, f"cfg seen: {sys_mod._home()}, text={text!r}"
    assert any("gate" in ln and "256000" in ln or "declared" in ln for ln in text.splitlines())
    assert errors == []


def test_doctor_report_records_a_version_probe_failure(monkeypatch):
    import harness.service.system as sys_mod

    def boom():
        raise RuntimeError("no binary")

    monkeypatch.setattr(sys_mod, "installed_version", boom)
    monkeypatch.setattr(sys_mod, "_provider_specs", lambda: [])
    monkeypatch.setattr(sys_mod, "PINS", {"opencode": "opencode@1.18.25"})
    errors = []
    text = sys_mod.doctor_report(on_error=lambda where, exc: errors.append((where, exc)))
    assert "not found on PATH" in text or "DRIFT" in text or "opencode" in text
    assert len(errors) == 1 and errors[0][0] == "doctor_version" and "no binary" in str(errors[0])


def test_provider_lines_lists_the_registry(monkeypatch):
    import harness.service.system as sys_mod
    monkeypatch.setattr(sys_mod, "_provider_specs", lambda: [
        {"name": "gate", "model": "gate/extraction", "base_url": "http://127.0.0.1:7373",
         "tier": "local", "context_window": 256000},
        {"name": "cloud", "model": "big", "base_url": "https://api.example",
         "tier": "cloud", "context_window": 0},
    ])
    lines = provider_lines()
    assert "gate: gate/extraction @ http://127.0.0.1:7373 (tier local, window 256000)" in lines
    assert "cloud: big @ https://api.example (tier cloud, window —)" in lines
    assert lines.endswith("\n(route edits are data edits in data/routing-a1.yaml)")
