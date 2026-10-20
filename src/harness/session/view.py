# src/harness/session/view.py
"""The global view + drill-down + doc pane (spec 17 s5.4, plan Task 12).

Pure readers over the visibility substrate that already exists — trace.db (with
the F1 identity columns), the per-workspace guard-log.jsonl, and the workspace
git tree. P5 proved live that drill-down on these matches the event stream
where it matters and beats it where it counts (tokens): this module is that
contract, in code. No new seam, ever.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _session_rows(trace, session_id: str, refs: list[int] | None) -> list:
    """The session's dispatch rows: by the gate-side identity column when the
    caller has it, else by the shell's OWN recorded refs (the live mount does
    not carry session identity to the gate — F1's columns are
    write-when-supplied)."""
    if refs is not None:
        return trace.by_ids(refs)
    return trace.by_session(session_id)


def agent_status(trace, session_id: str, base: Path | None = None,
                 refs: list[int] | None = None) -> list[dict]:
    """One row per agent seen in the session's dispatches: identity (F1), the
    honest serving tier (provider/model/verified straight from the trace), the
    token sums (F7: rows aggregated, never counted), the last dispatch's status,
    and the agent's guard-log line count (every line is a guard event; block
    decisions throw into the event stream, not this log — a recorded substrate
    fact, so the count is activity, not blocks). `base` is the session's
    workspace root (`<base>/<session>/<agent>/guard-log.jsonl`); None -> 0.
    `refs` switches the join to the shell's recorded trace ids (live path)."""
    per: dict[str, dict] = {}
    for r in _session_rows(trace, session_id, refs):
        row = per.setdefault(r.agent or "unknown", {
            "agent": r.agent or "unknown", "provider": r.provider,
            "model": r.model, "verified": r.verified,
            "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0,
            "guard_flags": 0,
            "last_status": ""})
        row["tokens_in"] += r.tokens_in
        row["tokens_out"] += r.tokens_out
        row["tokens_reasoning"] += getattr(r, "tokens_reasoning", 0)
        row["last_status"] = r.status
        row["provider"], row["model"], row["verified"] = r.provider, r.model, r.verified
    if base is not None:
        for name, row in per.items():
            row["guard_flags"] = _guard_lines(Path(base) / session_id / name)
    return list(per.values())


def drilldown(trace, session_id: str, agent: str,
              refs: list[int] | None = None) -> list[dict]:
    """One agent's dispatch rows in dispatch order — the drill-down pane's data,
    matching trace.db by construction (P5's contract, in code). by_session /
    by_ids already return id order (the trace's own). `refs` switches the join
    to the shell's recorded trace ids (live path)."""
    return [dict(task_class=r.task_class, provider=r.provider,
                 model=r.model, verified=r.verified, tokens_in=r.tokens_in,
                 tokens_out=r.tokens_out, status=r.status, error=r.error,
                 agent=r.agent, session_id=r.session_id)
            for r in _session_rows(trace, session_id, refs) if r.agent == agent]


def doc_tree(ws: Path) -> list[str]:
    """The workspace's tracked files — reused from the spawn substrate's snapshot
    helper (one implementation of 'what files does this agent's tree hold')."""
    from harness.session.workspace import git_snapshot_paths
    return git_snapshot_paths(Path(ws))


def doc_diff(ws: Path) -> str:
    """The workspace's uncommitted changes — the live doc pane. Empty (never a
    crash) for a clean tree or a directory that is not a git repo."""
    r = subprocess.run(["git", "diff"], cwd=str(ws), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", check=False)
    return (r.stdout or "") if r.returncode == 0 else ""


def doc_changes(ws: Path) -> list[str]:
    """Every file the agent touched (new, modified, staged) — `git status
    --porcelain`. A NEWLY-WRITTEN doc is untracked, invisible to ls-files and
    plain git diff alike; status is what 'the live view shows agent edits'
    honestly means. Empty (never a crash) off a repo."""
    r = subprocess.run(["git", "status", "--porcelain"], cwd=str(ws),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", check=False)
    if r.returncode != 0:
        return []
    return [ln[3:].strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def _guard_lines(ws: Path) -> int:
    """Lines in this workspace's guard-log — JSONL, one guard event per line."""
    f = ws / "guard-log.jsonl"
    if not f.is_file():
        return 0
    return sum(1 for line in f.read_text(encoding="utf-8").splitlines()
               if line.strip())
