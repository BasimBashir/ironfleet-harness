# src/harness/lifecycle/debrief.py — court-event intake + the prediction diff (M5).
# Ported from ironfleet-legal/mcp/dossier.py::debrief: `date` is required (it
# anchors the diff and the outcome log); the diff pairs every unresolved
# prediction with what the court actually said; whether a prediction MATCHED
# is judgement supplied as DATA via record_outcome — never computed here.
from __future__ import annotations

from harness.lifecycle import dossier, statemachine


def ingest_court_event(con, matter: str, event: dict, *,
                       actor: str = "case-manager") -> dict:
    """Append the court event, walk COURT -> DEBRIEF -> RE_STRATEGY, and return
    the mechanical prediction-vs-outcome diff."""
    if not isinstance(event, dict) or not event.get("date"):
        raise RuntimeError("court event needs a `date` (YYYY-MM-DD) — it anchors the "
                           "prediction diff and the outcome log")
    payload = {k: v for k, v in event.items() if k not in ("date",)}
    row = dossier.append(con, matter, "court_events",
                         {"event_type": event.get("event_type", "hearing"),
                          "event_date": event["date"], "payload": payload},
                         actor=actor)
    cur = statemachine.state(con, matter)
    if cur == "COURT":
        statemachine.transition(con, matter, "DEBRIEF", actor=actor,
                                note=f"debrief of {event['date']}")
        statemachine.transition(con, matter, "RE_STRATEGY", actor=actor,
                                note="court decided; re-plan")
    preds = dossier.read(con, matter, "predictions")
    diff = [{"prediction_id": ev.get("prediction_id"),
             "strategy_version": ev.get("strategy_version"),
             "claim": ev.get("claim"),
             "court_said": {"event_type": event.get("event_type", "hearing"),
                            "date": event.get("date"),
                            "judge_said": event.get("judge_said", ""),
                            "orders": event.get("orders", [])}}
            for ev in preds["events"] if ev.get("prediction_id") in preds["unresolved"]]
    return {"court_event": row, "diff": diff, "open_count": len(diff),
            "state": statemachine.state(con, matter),
            "note": "record one outcomes row per diff entry (match true/false, "
                    "actual) via record_outcome, then cut strategy vN+1"}


def record_outcome(con, matter: str, prediction_id: str, match, actual: str,
                   court_date: str, *, actor: str = "case-manager") -> dict:
    """Record the verdict on one prediction. `match` is judgement supplied as
    data — this function stores it, it never computes it."""
    row = dossier.append(con, matter, "outcomes",
                         {"prediction_id": prediction_id, "match": 1 if match else 0,
                          "actual": actual, "court_date": court_date},
                         actor=actor)
    return row
