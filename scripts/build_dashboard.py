"""A-7 dashboard — joins the A/B sidecars into the cost/performance verdict (spec §§2.4, 4, 5).

Reads one A7-<leg>.jsonl per leg plus the rate table, derives each LOCAL leg's blended rate from
its OWN measured throughput, prices every case, applies the relative bar, and writes a markdown
report whose every number traces to a sidecar record and a sourced rate.

The verdict is printed and sourced. It writes no config and changes no routing table or pin —
substitution is a human decision.

Usage: .venv/Scripts/python.exe scripts/build_dashboard.py [--sidecars GLOB] [--out FILE]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from harness.eval.substitute import (BarSpec, LegSummary, RateTable, amortized_rate_entry,  # noqa: E402
                                     cost_of, recommend)
import scripts.run_ab as run_ab                                             # noqa: E402

# The spike's measured ~8x prompt-scaffolding tax (9,279 vs 1,104 input tokens per legal query
# under opencode). NOT incurred here — this runner dispatches through the gate directly — but a
# reader comparing A-7 costs against an opencode-driven pipeline would otherwise misapply them.
SCAFFOLDING_TAX_NOTE = (
    "The ~8x prompt-scaffolding tax measured in the 2026-09-01 spike (9,279 vs 1,104 input tokens "
    "per legal query under opencode) is NOT incurred by this run, which dispatches through the "
    "gate directly. Do not apply A-7 per-case costs to an opencode-driven pipeline.")


def bar_for(summaries: list[LegSummary]) -> BarSpec:
    incumbent = [s for s in summaries if s.role == "incumbent"]
    if not incumbent:
        raise ValueError("no incumbent leg — the bar is relative and needs one")
    return BarSpec(incumbent=incumbent[0].label)          # default tolerances 0.0: match-or-beat


def leg_summaries(sidecars: dict[str, list[dict]], legs, table: RateTable) -> list[LegSummary]:
    """One summary per leg, priced. Local legs get their blended rate DERIVED from measured
    throughput; cloud legs take the published split rates."""
    out: list[LegSummary] = []
    for leg in legs:
        records = sidecars.get(leg.label, [])
        summary = LegSummary.from_records(leg.label, leg.role, records)
        if not summary.usable:
            out.append(summary)
            continue
        rate = table.require(leg.rate_key)
        if rate.blended:
            tin = sum(int(r.get("tokens_in") or 0) for r in records if r.get("status") == "ok")
            tout = sum(int(r.get("tokens_out") or 0) for r in records if r.get("status") == "ok")
            lat = sum(float(r.get("latency_ms") or 0) for r in records if r.get("status") == "ok")
            rate = amortized_rate_entry(rate, tin, tout, lat)
        total = sum(cost_of(int(r.get("tokens_in") or 0), int(r.get("tokens_out") or 0),
                            0, rate)["total"]
                    for r in records if r.get("status") == "ok")
        summary.mean_cost = total / summary.n_scored
        out.append(summary)
    return out


def _fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.4f}"


def render(summaries: list[LegSummary], table: RateTable, bar: BarSpec,
           scaffolding_tax_note: str) -> str:
    verdict = recommend(bar, summaries)
    inc = [s for s in summaries if s.label == bar.incumbent][0]
    lines = ["# A-7 model substitution — cost/performance dashboard", "",
             f"- generated: {datetime.now().isoformat(timespec='seconds')}",
             f"- corpus: 30 S2 golden cases, dispatched through the egress gate (no opencode)",
             f"- bar: match-or-beat the incumbent **{bar.incumbent}** on mean citation accuracy, "
             f"mean grounding and persona-check rate (tolerances "
             f"{bar.tolerance_citation}/{bar.tolerance_grounding}/{bar.tolerance_persona})",
             "- rubric pass rate is reported for context and is NOT a bar axis "
             "(0/30 on both previously-measured models)", "",
             "## Ranked comparison", "",
             "| leg | role | scored | mean citations | mean grounding | persona | "
             "mean $/case | mean latency ms | meets bar |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in sorted(summaries, key=lambda x: (x.mean_cost is None, x.mean_cost or 0)):
        if s.label == bar.incumbent:
            meets = "baseline (incumbent)"
        else:
            meets = "yes" if s.label in verdict["meeting_bar"] else "NO"
        lines.append(f"| {s.label} | {s.role} | {s.n_scored}/{s.n_cases} | "
                     f"{s.mean_citation:.3f} | {s.mean_grounding:.3f} | {s.mean_persona:.3f} | "
                     f"{_fmt(s.mean_cost)} | {s.mean_latency_ms:.0f} | {meets} |")
    lines += ["", "## Recommendation", "",
              f"**{verdict['recommendation']}** — {verdict['basis']}. "
              f"Ties break on {verdict['ties_broken_by']}."]
    if verdict["fallback"]:
        lines += ["", "No candidate meets the bar; the per-axis gaps:"]
        for label, problems in verdict["gaps"].items():
            lines.append(f"- **{label}**: {'; '.join(problems)}")
    elif verdict["gaps"]:
        lines += ["", "Candidates that did not meet the bar:"]
        for label, problems in verdict["gaps"].items():
            lines.append(f"- **{label}**: {'; '.join(problems)}")
    lines += ["", "## Cost provenance — every price and its source", ""]
    for leg in run_ab.LEGS:
        rate = table.rates.get(leg.rate_key)
        if rate is None:
            continue
        lines.append(f"- **{leg.label}**: {'blended (local, derived)' if rate.blended else 'split (cloud)'}"
                     f" — in ${rate.in_per_m:.2f}/M, out ${rate.out_per_m:.2f}/M"
                     + (f", cached ${rate.cached_in_per_m:.2f}/M" if not rate.blended else ""))
        lines.append(f"  - source: {rate.source}")
        if rate.as_billed_note:
            lines.append(f"  - as-billed: {rate.as_billed_note}")
        if rate.blended and rate.amortization:
            srcs = rate.amortization.get("sources", {})
            lines.append("  - amortization assumptions (DEFAULTS PENDING OPERATOR CONFIRMATION): "
                         + ", ".join(f"{k}={rate.amortization[k]}" for k in
                                     ("hardware_cost_usd", "service_life_hours", "utilization")))
            for k, v in srcs.items():
                lines.append(f"    - {k}: {v}")
    lines += ["", "### Sensitivity", "",
              "At these defaults the local rate is dominated by the utilization assumption, so the "
              "**ratio between two local legs is far more trustworthy than either absolute dollar "
              "figure** — read the ranking, not the price tag. Summed latency includes each local "
              "leg's cold weights load on its first case, which lowers measured throughput honestly.",
             "", f"### Scaffolding tax — {scaffolding_tax_note}", "",
             "## Honest provenance, per leg", "",
             "- local legs (`thomson1-chat`, `qwen3.8:27b`): Ollama cannot report its executing "
             "backend, so `verified=0` on every dispatch — the honest CR-3 reading. The legs ran "
             "under a recorded in-memory admission override (user-directed precedent), and CR-3, "
             "the probe and `src/` are untouched.",
             "- cloud leg (`Atria-Dawn-Preview`): `backend=\"saas\"`, `verified=1`. For a cloud "
             "provider this means **declared and recorded** (weights revision "
             f"`{run_ab.ATRIA_WEIGHTS_REVISION}`, per the user's 2026-10-06 identification) — the "
             "CR-3 cloud rule, NOT a cryptographic proof of the weights.",
             "", "## What this run does NOT claim", "",
             "- `minimax-m3:cloud` is excluded and was never dispatched: it is a 0-byte cloud-proxy "
             "entry on the local server, not local weights, and it is an unaudited third-party "
             "endpoint (CR-4). Its absence is a decision, not an oversight.",
             "- The strict rubric pass rate is 0/30 on previously-measured models; absolute "
             "citation accuracy near 0.1-0.2 is a property of these models under their output caps, "
             "not a port or harness defect.",
             "- The recommendation is not applied to any routing table or pin. It is an input to a "
             "human decision.",
             "", f"- sidecars: `data/eval/A7-<leg>.jsonl` (raw completions kept — re-scorable by "
                 f"`scripts/rescore_sidecars.py` without re-running any model)"]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sidecars", nargs="*", type=Path, default=None,
                   help="A7-*.jsonl files (default: all in data/eval/)")
    p.add_argument("--rates", type=Path, default=run_ab.RATES_PATH)
    p.add_argument("--out", type=Path, default=None,
                   help="report path (default: data/eval/A7-MODEL-SUBSTITUTION-YYYY-MM-DD.md)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    paths = args.sidecars or sorted((ROOT / "data" / "eval").glob("A7-*.jsonl"))
    if not paths:
        print("FAIL: no A7-*.jsonl sidecars found — run scripts/run_ab.py first")
        return 1
    table = RateTable.from_yaml(args.rates)
    sidecars: dict[str, list[dict]] = {}
    for p in paths:
        for rec in run_ab.load_sidecar(p):
            sidecars.setdefault(rec["leg"], []).append(rec)
    unknown = {k for k in sidecars if k not in {l.label for l in run_ab.LEGS}}
    if unknown:
        print(f"FAIL: sidecars reference legs not in the comparison set: {sorted(unknown)}")
        return 1
    summaries = leg_summaries(sidecars, run_ab.LEGS, table)
    bar = bar_for(summaries)
    md = render(summaries, table, bar, SCAFFOLDING_TAX_NOTE)
    out = args.out or (ROOT / "data" / "eval" /
                       f"A7-MODEL-SUBSTITUTION-{datetime.now().strftime('%Y-%m-%d')}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    verdict = recommend(bar, summaries)
    print(f"recommendation: {verdict['recommendation']} — {verdict['basis']}")
    for s in summaries:
        print(f"  {s.label}: scored {s.n_scored}/{s.n_cases}, cites {s.mean_citation:.3f}, "
              f"grounding {s.mean_grounding:.3f}, ${_fmt(s.mean_cost)}/case")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
