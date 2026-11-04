# tests/test_session_view.py
"""Task 12 (spec 17 s5.4, the P5 contract): the global view + drill-down read
ONLY trace.db, the per-workspace guard-log and the workspace git tree — the
visibility data that already exists, no new seam. Drill-down rows must match
trace.db (P5's drilldown_equivalent, proven live); the doc pane is the
workspace's file list + git diff."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.trace import DispatchRecord, TraceStore
from harness.session.view import agent_status, doc_diff, doc_tree, drilldown


def _rec(**kw):
    base = dict(matter_ref="m1", task_class="extraction", classification="LOCAL_PREFERRED",
                provider="nvidia-nim", model="step-5", tokens_in=10, tokens_out=5)
    base.update(kw)
    return DispatchRecord(**base)


def _trace(tmp_path: Path) -> TraceStore:
    trace = TraceStore(tmp_path / "trace.db")
    trace.append(_rec(session_id="ses-1", agent="hunter", provider="nvidia-nim",
                      model="step-5", tokens_in=100, tokens_out=50, status="ok"))
    trace.append(_rec(session_id="ses-1", agent="clerk", provider="ollama-local",
                      model="thomson1-chat:latest", tokens_in=30, tokens_out=20,
                      status="ok"))
    trace.append(_rec(session_id="ses-1", agent="clerk", provider="ollama-local",
                      model="thomson1-chat:latest", tokens_in=7, tokens_out=3,
                      status="refused"))
    trace.append(_rec(session_id="ses-2", agent="hunter", tokens_in=999, tokens_out=999))
    return trace


# -- the global view: one row per agent ------------------------------------------

def test_agent_status_one_row_per_agent_aggregated(tmp_path):
    rows = {r["agent"]: r for r in agent_status(_trace(tmp_path), "ses-1")}
    assert set(rows) == {"hunter", "clerk"}
    assert rows["hunter"]["tokens_in"] == 100 and rows["hunter"]["tokens_out"] == 50
    assert rows["clerk"]["tokens_in"] == 37 and rows["clerk"]["tokens_out"] == 23
    # the honest tier read: whatever the trace recorded, per agent
    assert rows["hunter"]["provider"] == "nvidia-nim"
    assert rows["clerk"]["model"] == "thomson1-chat:latest"
    assert rows["clerk"]["last_status"] == "refused"      # the LAST dispatch's status


def test_agent_status_counts_guard_log_lines_per_agent(tmp_path):
    """Each agent's guard-log lives in the shared guard_dir (M1/S4); the view
    counts its lines (every line is a guard event). Another session's workspace
    — or a stray log in the shared parent — must not bleed in."""
    from harness.module_e.guard import guard_dir
    base = tmp_path / "base"
    for agent, n in (("hunter", 3), ("clerk", 1)):
        ws = base / "ses-1" / agent
        ws.mkdir(parents=True)
        guard_dir(ws).mkdir(parents=True, exist_ok=True)
        lines = [{"tag": f"tool.execute.before:{agent}", "retry": 3}] * n
        (guard_dir(ws) / "guard-log.jsonl").write_text(
            "".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    stray = guard_dir(base / "ses-1" / "hunter").parent   # the shared parent dir
    (stray / "guard-log.jsonl").write_text(json.dumps({"tag": "x"}) + "\n",
                                           encoding="utf-8")
    rows = {r["agent"]: r for r in agent_status(_trace(tmp_path), "ses-1", base)}
    assert rows["hunter"]["guard_flags"] == 3
    assert rows["clerk"]["guard_flags"] == 1


def test_agent_status_without_a_base_reports_zero_guard_flags(tmp_path):
    rows = agent_status(_trace(tmp_path), "ses-1")
    assert all(r["guard_flags"] == 0 for r in rows)


# -- drill-down: one agent's dispatch rows, matching trace.db (P5) ----------------

def test_drilldown_returns_that_agents_rows_only(tmp_path):
    rows = drilldown(_trace(tmp_path), "ses-1", "clerk")
    assert len(rows) == 2
    assert all(r["agent"] == "clerk" for r in rows)
    assert [r["status"] for r in rows] == ["ok", "refused"]     # dispatch order
    assert rows[0]["provider"] == "ollama-local"
    assert sum(r["tokens_in"] for r in rows) == 37
    assert all(r["session_id"] == "ses-1" for r in rows)


def test_drilldown_unknown_agent_is_empty(tmp_path):
    assert drilldown(_trace(tmp_path), "ses-1", "nobody") == []


# -- the doc pane: file list + git diff -------------------------------------------

def _git_repo_with_edit(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=str(ws), capture_output=True,
                              text=True, check=True)
    git("-c", "user.email=t@t", "-c", "user.name=t", "init", "-q")
    (ws / "draft.md").write_text("v1\n", encoding="utf-8")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1")
    (ws / "draft.md").write_text("v2 — agent edit\n", encoding="utf-8")
    (ws / "new.md").write_text("added\n", encoding="utf-8")
    return ws


def test_doc_diff_shows_the_agent_edit(tmp_path):
    ws = _git_repo_with_edit(tmp_path)
    diff = doc_diff(ws)
    assert "v2 — agent edit" in diff and "draft.md" in diff
    assert "v1\n" not in diff.replace("v1\n+", "+")  # the minus line, not noise


def test_doc_diff_clean_tree_is_empty(tmp_path):
    ws = _git_repo_with_edit(tmp_path)
    subprocess.run(["git", "add", "."], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "v2"], cwd=str(ws), check=True,
                   capture_output=True)
    assert doc_diff(ws) == ""


def test_doc_diff_non_repo_is_empty_not_a_crash(tmp_path):
    assert doc_diff(tmp_path) == ""


def test_doc_tree_lists_tracked_files(tmp_path):
    ws = _git_repo_with_edit(tmp_path)
    files = doc_tree(ws)
    assert "draft.md" in files


def test_doc_changes_sees_a_new_untracked_doc(tmp_path):
    """The live-view contract: an agent's NEWLY-WRITTEN file must appear — it is
    untracked, so ls-files and plain git diff both miss it; status sees it."""
    from harness.session.view import doc_changes
    ws = _git_repo_with_edit(tmp_path)
    (ws / "fresh-output.md").write_text("agent wrote this\n", encoding="utf-8")
    changes = doc_changes(ws)
    assert "fresh-output.md" in changes and "draft.md" in changes
