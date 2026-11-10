# tests/test_pilot_weekly_report.py
import csv
import importlib.util
from datetime import date
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pilot_weekly_report.py"

def _load():
    spec = importlib.util.spec_from_file_location("pilot_weekly_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

WEEK = date(2026, 11, 9).isocalendar()[:2]
WEEK_LABEL = f"{WEEK[0]}-W{WEEK[1]:02d}"

OUTCOME = [
    {"matter_id": "M-001", "date": "2026-11-09", "stage": "DEBRIEF",
     "prediction": "adjournment sought", "outcome": "adjourned", "hit": "1", "notes": ""},
    {"matter_id": "M-001", "date": "2026-11-10", "stage": "STRATEGY",
     "prediction": "summary judgment", "outcome": "", "hit": "", "notes": "awaiting hearing"},
    {"matter_id": "M-002", "date": "2026-11-03", "stage": "DEBRIEF",
     "prediction": "costs awarded", "outcome": "costs reserved", "hit": "0", "notes": ""},
]
REVIEW = [
    {"date": "2026-11-09", "matter_id": "M-001", "output": "filing pack",
     "verdict": "approve", "fixes": "", "resolved": ""},
    {"date": "2026-11-09", "matter_id": "M-002", "output": "strategy v2",
     "verdict": "changes", "fixes": "tighten s 287 quote", "resolved": ""},
    {"date": "2026-11-04", "matter_id": "M-002", "output": "debrief memo",
     "verdict": "reject", "fixes": "wrong court named", "resolved": "2026-11-06"},
]

def test_week_scoped_summary():
    s = _load().summarize(OUTCOME, REVIEW, WEEK)
    assert s["outcome_rows"] == 2
    assert s["matters"] == ["M-001"]
    assert (s["known"], s["hits"], s["hit_rate"]) == (1, 1, 1.0)
    assert s["pending"] == 1
    assert s["review_rows"] == 2
    assert s["verdicts"] == {"approve": 1, "changes": 1}
    assert s["open_fixes"] == 1  # unresolved 'changes'; the old 'reject' is resolved

def test_all_rows_and_bad_rows():
    s = _load().summarize(OUTCOME, REVIEW, None)
    assert s["outcome_rows"] == 3
    assert s["hit_rate"] == 0.5  # 1 hit of 2 known outcomes
    bad = _load().summarize(
        [{"matter_id": "", "date": "nope", "stage": "", "prediction": "",
          "outcome": "", "hit": "", "notes": ""}], [], None)
    assert bad["skipped"] == 1

def test_render_and_cli(tmp_path):
    d = tmp_path / "PILOT-X"
    d.mkdir()
    for name, rows in (("outcome-log.csv", OUTCOME), ("review-log.csv", REVIEW)):
        with (d / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    assert _load().main(["--pilot-dir", str(d), "--week", WEEK_LABEL]) == 0
    text = (d / f"WEEKLY-{WEEK_LABEL}.md").read_text(encoding="utf-8")
    assert "LAUNCH: BLOCKED" in text  # safety string must survive every render
    assert f"hit rate 100% (1/1)" in text
    assert "open fixes: 1" in text
