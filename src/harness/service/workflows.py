# src/harness/service/workflows.py — the restart path (06 Phase 3/4)
"""resume(runner, session_id): run whatever is claimable right now. The caller
decides WHEN to call it (M4 wires no automatic caller — that is a UI/CLI
decision, not part of the durable core). Returns the rows the resumed run
produced."""
from __future__ import annotations

from harness.workflow import orchestrator
from harness.workflow.db import connect


async def resume(runner, session_id: str) -> list:
    """Re-open platform.db at the runner's store root and drive every claimable
    task through the runner's own _run_stage — the same body run_task uses."""
    store = getattr(runner, "store", None)
    if store is None:
        return []
    con = connect(orchestrator.platform_db(store.root))
    rows: list = []
    try:
        executions = con.execute(
            "SELECT execution_id, matter_id, input_task_text, compiled_plan_json"
            " FROM executions WHERE state='executing' AND session_id=?",
            (session_id,)).fetchall()
        import json
        for ex in executions:
            stages = json.loads(ex["compiled_plan_json"])

            async def body(task_row, prev_summary, _ex=ex, _stages=stages):
                stage = next(s for s in _stages if s["stage"] == task_row["key"])
                row = await runner._run_stage(session_id, ex["matter_id"],
                                              ex["input_task_text"], stage,
                                              "", prev_summary)
                rows.append(row)
                return row.output_summary

            await orchestrator.run(con, ex["execution_id"], body,
                                   owner=orchestrator.new_owner())
    finally:
        con.close()
    return rows
