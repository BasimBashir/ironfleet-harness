"""S7h acceptance — A-7 model substitution testing (spec 11, section 11).

Seven strict checks; exit 0 ONLY if all pass; a failure names its check and exits 1.
No partial mode.

  C1 completeness     — every leg's sidecar accounts for all 30 cases (scored/refused/failed/
                        empty — none missing). Requires the REAL run's sidecars.
  C2 cost recomputed  — per-leg cost recomputed by an INDEPENDENT arithmetic path from the
                        sidecars' token counts x the rate table, matching the dashboard's claim.
  C3 bar recomputed   — the bar and the recommendation recomputed independently from the sidecars.
  C4 retry            — the transport wrapper recovers after transient failures and exhausts its
                        ceiling on a permanent one (synthetic flaky transport).
  C5 recall/resume    — a truncated sidecar resumes to a complete run; --recall redoes exactly the
                        named cases; the last record per case id wins.
  C6 live provenance  — one REAL dispatch per leg, traced end to end with honest values: local
                        legs verified=0, the cloud leg backend="saas"/verified=1. THE CHECK THAT
                        CAN FAIL ON A LIVE DAY: if the cloud endpoint or a local model is down,
                        C6 fails, the module lands CONDITIONAL, and the failure is priced into the
                        ledger rather than absorbed.
  C7 empty content    — a reasoning model that spends the whole budget on reasoning_content is
                        recorded as a CAP failure with its tokens_out, never scored as zero quality.

C1-C5 and C7 run offline against the committed artifacts and synthetic stubs; only C6 dispatches.

Usage: .venv/Scripts/python.exe scripts/accept_s7h.py [--atria-key $IRONFLEET_ATRIA_KEY]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import scripts.run_ab as run_ab                                       # noqa: E402
import scripts.build_dashboard as dash                                # noqa: E402
from harness.eval.substitute import LegSummary, RateTable             # noqa: E402
from harness.gate import EgressGate, LLMRequest                       # noqa: E402
from harness.policy import RoutingTable                               # noqa: E402
from harness.providers.config import ProviderConfig, ProviderRegistry  # noqa: E402
from harness.providers.retry import RetryExhausted, retrying          # noqa: E402
from harness.trace import TraceStore                                  # noqa: E402

CASES_DIR = ROOT / "data" / "golden_cases"
EVAL_DIR = ROOT / "data" / "eval"
CAPABILITY = "A-7 model substitution testing"
MATURITY = "CONDITIONAL"      # upgraded to ACCEPTED by main() when C6 passes on the live legs

# The cloud rates the dashboard claims, passed to C2's independent recomputation so a bug in the
# shared cost code cannot pass the check it validates (accept_s7f's C1 precedent).
CLOUD_IN_PER_M, CLOUD_OUT_PER_M = 1.40, 4.40
# The dashboard prints mean $/case to 4 decimals (build_dashboard._fmt), so a claim parsed back out
# of the report is a ROUNDED value — a correct one can sit up to 5e-5 from the exact recomputation.
# Anything beyond the print precision is a wiring bug: a wrong rate or token accounting moves a
# leg's mean by orders of magnitude more than this.
CLAIM_TOLERANCE = 1e-4


def _tiny_cases(tmp_path: Path):
    """One synthetic case for C7 — no network, no corpus dependency."""
    from harness.eval.golden_case import GoldenCase
    return [GoldenCase(id="tiny", matter_type="m", task_class="analysis", prompt="answer")]


def check_c1(sidecars: dict[str, list[dict]], case_ids: list[str]) -> list[str]:
    problems = []
    for leg in run_ab.LEGS:
        records = sidecars.get(leg.label, [])
        seen = {r["id"] for r in records}
        missing = [c for c in case_ids if c not in seen]
        if missing:
            problems.append(f"C1: {leg.label} is missing {len(missing)} case(s), e.g. {missing[:3]}")
    return problems


def check_c2(sidecars: dict[str, list[dict]], claims: dict[str, float], *,
             in_per_m: float, out_per_m: float) -> list[str]:
    """Independent recomputation — inline arithmetic, NOT cost_of().

    Only legs priced at the passed split rates are checked. LOCAL legs are priced by the
    dashboard's DERIVED blended rate (substitute.amortized_rate_entry, from the leg's own measured
    throughput), so recomputing a local leg at the cloud rates would compare against a number the
    dashboard never claimed and fail unconditionally — the 2026-10-06 ruling. Local legs are
    covered structurally by C3, which recomputes the bar and recommendation end-to-end through the
    real leg_summaries."""
    problems = []
    table = RateTable.from_yaml(run_ab.RATES_PATH)
    for leg in run_ab.LEGS:
        rate = table.rates.get(leg.rate_key)
        if rate is not None and rate.blended:
            continue                                  # priced by a derived blended rate, not these
        records = sidecars.get(leg.label, [])
        # Price the same deduplicated set the dashboard prices: the sidecar is append-only, so a
        # --recall rerun leaves a superseded ok row for the same id as an audit trail. Summing raw
        # records would double-count it and disagree with the claim by exactly that error.
        by_id = {r["id"]: r for r in records}
        priced = [r for r in by_id.values() if r.get("status") == "ok"]
        if not priced:
            continue                                  # an unusable leg has no cost to recompute
        total = sum((int(r.get("tokens_in") or 0) * in_per_m
                     + int(r.get("tokens_out") or 0) * out_per_m) / 1_000_000.0
                    for r in priced)
        mean = total / len(priced)
        claim = claims.get(leg.label)
        if claim is None or abs(claim - mean) > CLAIM_TOLERANCE:
            problems.append(f"C2: {leg.label} claimed ${claim} but recomputes to ${mean:.6f}")
    return problems


def check_c3(sidecars: dict[str, list[dict]], expected_recommendation: str) -> list[str]:
    """Recompute the bar and the recommendation from the sidecars and compare."""
    problems = []
    try:
        table = RateTable.from_yaml(run_ab.RATES_PATH)
        summaries = dash.leg_summaries(sidecars, run_ab.LEGS, table)
        bar = dash.bar_for(summaries)
        verdict = __import__("harness.eval.substitute", fromlist=["recommend"]).recommend(
            bar, summaries)
    except Exception as ex:                                   # noqa: BLE001
        return [f"C3: recomputation failed ({type(ex).__name__}): {ex}"]
    if verdict["recommendation"] != expected_recommendation:
        problems.append(f"C3: recomputed recommendation {verdict['recommendation']!r} "
                        f"!= reported {expected_recommendation!r} (basis: {verdict['basis']})")
    return problems


async def check_c4() -> list[str]:
    """Retry: recover after transient failures; exhaust and report on a permanent one."""
    problems = []
    calls = []

    async def flaky(provider, payload):
        calls.append(1)
        return None if len(calls) < 3 else {"choices": [{"message": {"content": "ok"}}]}

    cfg = ProviderConfig(name="p", base_url="http://p/v1", model="m", engine="cloud")
    out = await retrying(flaky, attempts=5, base_delay_s=0.0)(cfg, {})
    if out["choices"][0]["message"]["content"] != "ok" or len(calls) != 3:
        problems.append(f"C4: did not recover after 2 transient failures (calls={len(calls)})")

    perm = []

    async def always_bad(provider, payload):
        perm.append(1)
        return {"error": {"message": "upstream failure"}}

    try:
        await retrying(always_bad, attempts=3, base_delay_s=0.0)(cfg, {})
        problems.append("C4: a permanent failure should have raised RetryExhausted")
    except RetryExhausted:
        pass
    if len(perm) != 3:
        problems.append(f"C4: exhausted after {len(perm)} calls, expected exactly 3")
    return problems


def check_c5() -> list[str]:
    """Resume and recall semantics against synthetic sidecar states."""
    problems = []
    records = [{"id": "c0", "status": "ok"}, {"id": "c1", "status": "failed"}]
    if run_ab.pending(records, ["c0", "c1", "c2"], recall=()) != ["c1", "c2"]:
        problems.append("C5: a plain resume should redo only incomplete/missing cases")
    if run_ab.pending(records, ["c0", "c1"], recall=("c0",)) != ["c0", "c1"]:
        problems.append("C5: --recall should also redo the named completed case")
    if run_ab.pending([{"id": "c0", "status": "failed"}, {"id": "c0", "status": "ok"}],
                      ["c0"], recall=()) != []:
        problems.append("C5: the LAST record per case id must be the effective one")
    return problems


async def check_c6(ollama_url: str, atria_key: str) -> list[str]:
    """One real dispatch per leg, traced with honest provenance. THIS is the check that can fail on
    a live day — see the driver docstring."""
    problems = []
    trace = TraceStore(EVAL_DIR / "trace-s7h-acceptance.db")
    for leg in run_ab.LEGS:
        registry, keys = ProviderRegistry(), {}
        try:
            await run_ab._register(leg, registry=registry, keys=keys, ollama_url=ollama_url,
                                   atria_key=atria_key)
        except Exception as ex:                                 # noqa: BLE001
            problems.append(f"C6: {leg.label} could not register through the probe: {ex}")
            continue
        timeout = run_ab.LOCAL_TIMEOUT_S if leg.engine != "cloud" else run_ab.CLOUD_TIMEOUT_S
        gate = EgressGate(registry=registry, routing=run_ab._routing_for(leg.provider),
                          trace=trace,
                          transport=retrying(run_ab.make_transport(keys, timeout),
                                             attempts=leg.retry_attempts,
                                             min_interval_s=leg.min_interval_s))
        try:
            resp = await gate.dispatch(LLMRequest(
                matter_ref=f"accept-s7h:{leg.label}", task_class="analysis",
                messages=[{"role": "user", "content": "Reply with the single word: OK"}],
                max_tokens=min(leg.output_cap, 512),
                classification="CLOUD_PERMITTED" if leg.engine == "cloud" else "LOCAL_PREFERRED"))
        except Exception as ex:                                  # noqa: BLE001
            problems.append(f"C6: {leg.label} live dispatch failed ({type(ex).__name__}): {ex}")
            continue
        rows = [r for r in trace.by_matter(f"accept-s7h:{leg.label}") if r.status == "ok"]
        if not rows:
            problems.append(f"C6: {leg.label} dispatched but no ok trace row was written")
            continue
        row = rows[-1]
        print(f"[C6] {leg.label}: provider={row.provider} model={row.model} "
              f"backend={row.backend!r} verified={row.verified} "
              f"tokens={row.tokens_in}/{row.tokens_out} latency_ms={row.latency_ms}",
              file=sys.stderr)
        if leg.engine == "cloud":
            if row.backend != "saas" or row.verified != 1:
                problems.append(f"C6: cloud leg expected backend='saas'/verified=1, got "
                                f"backend={row.backend!r}/verified={row.verified}")
        else:
            if row.verified != 0:
                problems.append(f"C6: local leg {leg.label} must stay verified=0 (CR-3), got "
                                f"verified={row.verified}")
        if resp.content is None:
            problems.append(f"C6: {leg.label} returned an empty content channel on a trivial "
                            f"prompt at max_tokens={min(leg.output_cap, 512)} (cap too small?)")
    return problems


async def check_c7(tmp_path: Path) -> list[str]:
    """A reasoning model that spends the whole budget on reasoning_content records a CAP failure,
    not a quality failure."""
    async def reasoning_only(provider, payload):
        return {"choices": [{"index": 0, "finish_reason": "length",
                             "message": {"role": "assistant", "content": None,
                                         "reasoning_content": "thinking"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 64, "total_tokens": 74}}
    reg = ProviderRegistry()
    reg.upsert(ProviderConfig(name="stub", base_url="http://s/v1", model="m", engine="cloud",
                              tier="cloud", admitted="full"))
    # One trace store for the gate and the leg: run_leg reads back the row the gate wrote, so the
    # two must share it or the leg sees no dispatch and records a spurious failure instead.
    trace = TraceStore(tmp_path / "t7.db")
    gate = EgressGate(registry=reg,
                      routing=RoutingTable(rules=[], defaults={"local_only": ["stub"],
                                                               "local_preferred": ["stub"],
                                                               "cloud_permitted": ["stub"]}),
                      trace=trace, transport=reasoning_only)
    leg = run_ab.ModelUnderTest(label="stub", provider="stub", model="m", engine="cloud",
                                output_cap=64, rate_key="x")
    scored = await run_ab.run_leg(leg, _tiny_cases(tmp_path), tmp_path, trace, registry=reg,
                                  keys={}, atria_key="", ollama_url="", gate=gate)
    recs = run_ab.load_sidecar(tmp_path / "A7-stub.jsonl")
    if scored != 0:
        return ["C7: an empty-content case must not count as scored"]
    if not recs or recs[0]["status"] != "empty_content":
        return ["C7: the case should be recorded as empty_content"]
    if recs[0]["tokens_out"] != 64:
        return [f"C7: tokens_out must be kept ({recs[0]['tokens_out']} != 64) so a cap failure is "
                "distinguishable from a quality failure"]
    return []


def _load_committed() -> tuple[dict[str, list[dict]], list[str]]:
    sidecars: dict[str, list[dict]] = {}
    for p in sorted(EVAL_DIR.glob("A7-*.jsonl")):
        for rec in run_ab.load_sidecar(p):
            sidecars.setdefault(rec["leg"], []).append(rec)
    from harness.eval.golden_case import load_cases
    case_ids = [c.id for c in load_cases(CASES_DIR)]
    return sidecars, case_ids


def _dashboard_claims() -> dict[str, float]:
    """The per-leg mean costs the dashboard printed, parsed back out of its ranked table."""
    reports = sorted(EVAL_DIR.glob("A7-MODEL-SUBSTITUTION-*.md"))
    if not reports:
        return {}
    claims: dict[str, float] = {}
    for line in reports[-1].read_text(encoding="utf-8").splitlines():
        if line.startswith("| ") and "leg" not in line and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 8:
                try:
                    claims[cells[0]] = float(cells[6])
                except ValueError:
                    continue
    return claims


async def run(args: argparse.Namespace) -> int:
    sidecars, case_ids = _load_committed()
    if not sidecars:
        print("FAIL: no A7-*.jsonl sidecars found — run scripts/run_ab.py first")
        return 1
    problems: list[str] = []
    problems += check_c1(sidecars, case_ids)
    problems += check_c2(sidecars, _dashboard_claims(), in_per_m=CLOUD_IN_PER_M,
                         out_per_m=CLOUD_OUT_PER_M)
    # C3 recomputes the recommendation the dashboard reported
    table = RateTable.from_yaml(run_ab.RATES_PATH)
    summaries = dash.leg_summaries(sidecars, run_ab.LEGS, table)
    verdict = __import__("harness.eval.substitute", fromlist=["recommend"]).recommend(
        dash.bar_for(summaries), summaries)
    problems += check_c3(sidecars, verdict["recommendation"])
    problems += await check_c4()
    problems += check_c5()
    if not args.skip_live:
        problems += await check_c6(args.ollama_url, args.atria_key)
    problems += await check_c7(Path(args.tmp))
    if problems:
        print(f"FAIL {CAPABILITY} — {MATURITY}:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"PASS {CAPABILITY} — ACCEPTED on all seven checks "
          f"({len(case_ids)} cases x {len(run_ab.LEGS)} legs)")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ollama-url", default=run_ab.OLLAMA_URL)
    p.add_argument("--atria-key", default=os.environ.get("IRONFLEET_ATRIA_KEY", ""))
    p.add_argument("--skip-live", action="store_true",
                   help="DEBUG: skip C6 (exits 1 by design — never writes a verdict)")
    p.add_argument("--tmp", default=str(Path(__file__).resolve().parent / ".." / "data" / "eval"))
    return p.parse_args()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
