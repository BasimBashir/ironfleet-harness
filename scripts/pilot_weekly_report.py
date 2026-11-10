# scripts/pilot_weekly_report.py
"""Weekly Release A pilot measurement — reads a PILOT-<date>/ dir's CSVs, writes WEEKLY-<YYYY-Www>.md."""
import argparse
import csv
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def parse_week(text):
    m = re.fullmatch(r"(\d{4})-W(\d{2})", text.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def row_week(row):
    try:
        return date.fromisoformat(row.get("date", "").strip()).isocalendar()[:2]
    except ValueError:
        return None


def summarize(outcomes, reviews, week):
    """week: (year, iso_week) to scope, or None for every row."""
    oc = [r for r in outcomes if week is None or row_week(r) == week]
    rv = [r for r in reviews if week is None or row_week(r) == week]
    known = [r for r in oc if r.get("hit", "").strip() in ("0", "1")]
    hits = [r for r in known if r.get("hit", "").strip() == "1"]
    verdicts = Counter((r.get("verdict", "").strip() or "unknown") for r in rv)
    open_fixes = [r for r in rv
                  if r.get("verdict", "").strip() in ("changes", "reject")
                  and not r.get("resolved", "").strip()]
    skipped = [r for r in oc + rv
               if not (r.get("date", "").strip() and r.get("matter_id", "").strip())]
    return {
        "outcome_rows": len(oc),
        "matters": sorted({r["matter_id"].strip() for r in oc if r.get("matter_id", "").strip()}),
        "known": len(known),
        "hits": len(hits),
        "hit_rate": round(len(hits) / len(known), 3) if known else None,
        "pending": len(oc) - len(known),
        "review_rows": len(rv),
        "verdicts": dict(verdicts),
        "open_fixes": len(open_fixes),
        "skipped": len(skipped),
    }


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def render(s, week_label, pilot_name):
    hit = (f"{s['hit_rate'] * 100:.0f}% ({s['hits']}/{s['known']})"
           if s["hit_rate"] is not None else "no outcomes yet")
    lines = [
        f"# Pilot weekly — {week_label}",
        "",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} · pilot `{pilot_name}` · "
        "LAUNCH: BLOCKED (§7 Release A bars 2/5 MET — see BAR-TABLE.md).",
        "",
        "## Prediction vs outcome",
        f"- outcome rows: {s['outcome_rows']} across {len(s['matters'])} matter(s)",
        f"- known outcomes: {s['known']} — hit rate {hit}",
        f"- predictions awaiting outcome: {s['pending']}",
        "",
        "## Lawyer reviews",
        f"- outputs reviewed: {s['review_rows']}",
        "- verdicts: " + (", ".join(f"{k} {v}" for k, v in sorted(s["verdicts"].items())) or "none"),
        f"- open fixes: {s['open_fixes']}",
        "",
    ]
    if s["skipped"]:
        lines.append(f"> {s['skipped']} row(s) skipped for missing date or matter_id — fix them in the CSVs.")
    lines.append("Per-matter notes: `matters/<matter-id>/notes.md` · bar state: `BAR-TABLE.md`.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pilot-dir", type=Path, default=None,
                    help="PILOT-<date>/ dir (future packs; newest wins)")
    ap.add_argument("--week", default=None, help="YYYY-Www (default: current ISO week)")
    a = ap.parse_args(argv)
    if a.week:
        week = parse_week(a.week)
        if week is None:
            ap.error("--week must look like 2026-W46")
        label = a.week
    else:
        y, w, _ = date.today().isocalendar()
        week, label = (y, w), f"{y}-W{w:02d}"
    if a.pilot_dir:
        pilot = a.pilot_dir
    else:
        dirs = sorted(REPO.glob("data/eval/PILOT-*"))
        if not dirs:
            sys.exit("no data/eval/PILOT-<date>/ dir found — create the pack first")
        pilot = dirs[-1]
    s = summarize(read_csv(pilot / "outcome-log.csv"), read_csv(pilot / "review-log.csv"), week)
    out = pilot / f"WEEKLY-{label}.md"
    out.write_text(render(s, label, pilot.name), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
