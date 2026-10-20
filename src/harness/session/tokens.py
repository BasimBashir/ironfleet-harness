# src/harness/session/tokens.py
"""The D-T3 meter + auto-compact (spec 17 s5.5, plan Task 10).

Two measured facts shape this module. P5: the --format json event stream's token
fields are ZEROS while trace.db carries the real tokens_in/out/cache — so the
meter reads the TRACE, never the event stream. F7: one `opencode run` produces
1-2 dispatch rows, so accounting that counts rows lies; everything here
AGGREGATES rows by session (F1's identity columns provide the split per agent).

The compact threshold is the provider row's `safe_fill` — derived from the
model's MEASURED reliability on this box (S7h: empty-content cap failures,
mid-generation deaths, reasoning-token burn), never a fixed percentage in code.
"""
from __future__ import annotations

from datetime import datetime, timezone

COMPACT_MARKER = "/compact"
COMPACT_MODEL = "gate-local/gate/summarization"
# The fallback when a provider row declares no safe_fill — data may always override.
DEFAULT_SAFE_FILL = 0.8


def should_compact(used: int, window: int, safe_fill: float) -> bool:
    """Auto-/compact's trigger: the session's projected footprint has reached the
    model's safe fraction of its declared window. No window declared -> never
    fire (the meter shows used/— and compaction would be guessing)."""
    if window <= 0:
        return False
    return used >= safe_fill * window


def window_for(provider_name: str) -> tuple[int, float]:
    """(context_window, safe_fill) from the provider registry (data/providers.yaml,
    read through bootstrap._provider_specs so the env overrides apply). Unknown
    provider or undeclared window -> (0, DEFAULT_SAFE_FILL) — the honest dash."""
    from harness.bootstrap import _provider_specs
    for spec in _provider_specs():
        if spec["name"] == provider_name:
            return int(spec.get("context_window", 0) or 0), float(
                spec.get("safe_fill") or DEFAULT_SAFE_FILL)
    return 0, DEFAULT_SAFE_FILL


def usage_for_session(trace, session_id: str) -> dict:
    """The session's token ledger: totals plus the per-agent split — both summed
    from the session's dispatch ROWS (F7), never counted."""
    totals = {"in": 0, "out": 0, "cache": 0}
    per_agent: dict[str, dict[str, int]] = {}
    for r in trace.by_session(session_id):
        totals["in"] += r.tokens_in
        totals["out"] += r.tokens_out
        totals["cache"] += r.tokens_cache
        bucket = per_agent.setdefault(
            r.agent or "unknown", {"in": 0, "out": 0, "cache": 0})
        bucket["in"] += r.tokens_in
        bucket["out"] += r.tokens_out
        bucket["cache"] += r.tokens_cache
    return {**totals, "per_agent": per_agent}


def build_checkpoint_row(*, session_id: str, matter_ref: str, summary: str,
                         note: str, ts: str):
    """/compact's checkpoint row: the marker in `display` is what /resume (and the
    acceptance driver) match on; the summary is the model's handoff text."""
    from harness.session.store import TurnRow
    display = f"{COMPACT_MARKER} {note}".strip()
    return TurnRow(ts=ts, session_id=session_id, matter_ref=matter_ref,
                   display=display, agent="compact", tools_used=[],
                   output_summary=summary, docs_touched=[], trace_refs=[])


async def compact_session(driver, session_id: str, note: str = ""):
    """A model-summarized checkpoint, written through the gate (never by the
    shell's own summarization — every model call rides the proven path).

    The summarization turn is an ordinary driver turn (JSONL row + trace rows);
    the checkpoint row is appended after it, marked with COMPACT_MARKER, so
    /resume continues from the last checkpoint's summary. Live path — exercised
    by the acceptance driver's `compact` check, never the suite."""
    rows = driver.store.turns(session_id)
    if not rows:
        raise ValueError(f"nothing to compact: session {session_id!r} has no turns")
    matter_ref = rows[-1].matter_ref
    digest = " | ".join(r.output_summary[:200] for r in rows[-10:] if r.output_summary)
    prompt = ("Summarize this session for continuation. Note: "
              f"{note or 'none'}. Recent turns: {digest}. "
              "Reply with a compact handoff: matter state, decisions taken, next step.")
    turn = await driver.run_turn(session_id, matter_ref, "clerk", prompt,
                                 model=COMPACT_MODEL)
    checkpoint = build_checkpoint_row(
        session_id=session_id, matter_ref=matter_ref,
        summary=turn.output_summary, note=note,
        ts=datetime.now(timezone.utc).isoformat())
    driver.store.append_turn(checkpoint)
    return checkpoint
