"""A-7 model substitution runner — drives N models over the golden corpus through the real gate.

Each leg registers through the REAL provenance probe (its honest verdict printed, never asserted),
runs every golden case, and writes one re-scorable JSONL sidecar per leg — the S2 baseline runner's
record shape verbatim, so scripts/rescore_sidecars.py works on A-7 sidecars unchanged.

Two recorded deviations (spec §1.3), both named in the run's output:
  1. Ollama's honest admission is mechanical-only (CR-3: it cannot report its executing backend).
     Analysis-class eval work is overridden in MEMORY ONLY for this run, following the user-directed
     2026-08-28 baseline precedent. The probe, the routing table and src/ are untouched; every local
     dispatch is still traced verified=0.
  2. The golden corpus is dispatched to api.atria-asi.ai on the user's 2026-10-06 direction. The
     corpus is authored from PUBLIC judgments, not client matter data. The API key is held in memory
     only — never the keychain, never a file, never the repo.

Resilience (user requirement): the transport retries below the gate with backoff, the cloud leg is
paced under its per-minute rate limit, and completed cases are never re-run — interrupt the run and
relaunch it, or pass --recall ID to redo specific failed/empty cases.

Usage:
  .venv/Scripts/python.exe scripts/run_ab.py --atria-key $IRONFLEET_ATRIA_KEY
  .venv/Scripts/python.exe scripts/run_ab.py --only gc-liq --recall gc-dir-001

Exit codes: 0 = every leg accounted for all its cases; 1 = setup failure (no cases, no rates,
    no key for a cloud leg) or an incomplete run (a leg that died outright, or cases still
    pending when the pass finished). The exit status is how a backgrounded live run signals
    whether it is safe to proceed to the dashboard.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))                       # scripts.* imports (accept_s7f lesson)
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from harness.eval.golden_case import GoldenCase, load_cases                # noqa: E402
from harness.eval.scorers import score_case                                # noqa: E402
from harness.eval.substitute import ModelUnderTest, RateTable               # noqa: E402
from harness.gate import EgressGate, GateRefusal, LLMRequest, Transport     # noqa: E402
from harness.policy import RoutingTable                                     # noqa: E402
from harness.providers.config import ProviderConfig, ProviderRegistry       # noqa: E402
from harness.providers.http_fetch import openai_fetch                       # noqa: E402
from harness.providers.probe import register_provider                       # noqa: E402
from harness.providers.retry import retrying                                # noqa: E402
from harness.trace import TraceStore                                        # noqa: E402

CASES_DIR = ROOT / "data" / "golden_cases"
RATES_PATH = ROOT / "data" / "eval" / "ab" / "rates.yaml"
SIDECAR_DIR = ROOT / "data" / "eval"
OLLAMA_URL = os.environ.get("HARNESS_OLLAMA_URL", "http://127.0.0.1:11434/v1")
ATRIA_URL = "https://api.atria-asi.ai/v1"
# The cloud leg's declared weights revision. Under the CR-3 cloud rule this yields verified=1,
# which means DECLARED AND RECORDED — not a cryptographic proof. The dashboard says so.
ATRIA_WEIGHTS_REVISION = "glm-5.2-base-finetune"
# A cold 21-27B weights load takes minutes; the 300s http_fetch default would retry a legitimate
# load as a failure. Pacing waits and retries are included in the traced latency_ms — that wait is
# a real cost of using the model.
LOCAL_TIMEOUT_S = float(os.environ.get("HARNESS_AB_LOCAL_TIMEOUT", "1800"))
CLOUD_TIMEOUT_S = float(os.environ.get("HARNESS_AB_CLOUD_TIMEOUT", "600"))

# The comparison set (spec §1.1). Incumbent first — the bar is relative to it.
LEGS: list[ModelUnderTest] = [
    ModelUnderTest(label="thomson1-chat", role="incumbent", provider="ollama-local-chat",
                   model="thomson1-chat:latest", engine="ollama", context_window=262144,
                   output_cap=16384, min_interval_s=0.0, rate_key="local-amortized"),
    ModelUnderTest(label="qwen3.8:27b", role="candidate", provider="ollama-local-qwen",
                   model="qwen3.8:27b", engine="ollama", context_window=262144,
                   output_cap=16384, min_interval_s=0.0, rate_key="local-amortized"),
    ModelUnderTest(label="Atria-Dawn-Preview", role="candidate", provider="atria-cloud",
                   model="Atria-Dawn-Preview", engine="cloud", context_window=256_000,
                   output_cap=32768, min_interval_s=3.0, rate_key="atria-glm52",
                   retry_attempts=5),
]


def _sidecar_name(label: str) -> str:
    # NTFS reads a colon as an alternate-data-stream separator, so a label like
    # "qwen3.8:27b" would write a file named A7-qwen3.8 with no .jsonl extension —
    # invisible to the dashboard's A7-*.jsonl glob, while read-back through the same
    # colon-bearing path still worked (so resume never noticed). The record's "leg"
    # field keeps the true label; only the filename is sanitized.
    return f"A7-{label.replace(':', '-')}.jsonl"


def load_sidecar(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # A run killed mid-flush leaves a torn final line; a relaunch must skip it (with the leg and
    # the dropped line named) rather than die on it — resuming is the whole point of the sidecar.
    records = []
    for lineno, l in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not l.strip():
            continue
        try:
            records.append(json.loads(l))
        except json.JSONDecodeError:
            print(f"[sidecar] {path.name}:{lineno}: unparseable line dropped "
                  f"(expected after an interrupted run): {l[:80]!r}")
    return records


def pending(records: list[dict], case_ids: list[str], recall: tuple[str, ...]) -> list[str]:
    """Cases still to run: any with no record, any whose LAST record is not 'ok', and any recalled
    by id substring. The sidecar is append-only, so the last record per id is the effective one."""
    last: dict[str, dict] = {}
    for r in records:
        last[r["id"]] = r
    return [c for c in case_ids
            if last.get(c) is None
            or last[c].get("status") != "ok"
            or any(s in c for s in recall)]


def case_record(case: GoldenCase, leg: ModelUnderTest, *, status: str, error: str = "",
                sc=None, content: str | None = None, tokens_in: int = 0, tokens_out: int = 0,
                latency_ms: int = 0, model: str = "") -> dict:
    """One re-scorable record per case — the baseline runner's shape, plus leg identification and
    persona_rate so LegSummary can compute the persona axis without rescoring."""
    checks = sc.checks if sc is not None else {}
    return {
        "id": case.id, "leg": leg.label, "role": leg.role, "model": model or leg.model,
        "passed": sc.passed if sc is not None else None,
        "citation_accuracy": sc.citation_accuracy if sc is not None else None,
        "grounding_score": sc.grounding_score if sc is not None else None,
        "persona_rate": (sum(checks.values()) / len(checks)) if checks else None,
        "checks": checks,
        "status": status, "error": error,
        "tokens_in": tokens_in, "tokens_out": tokens_out, "latency_ms": latency_ms,
        "content": content,
    }


def make_transport(keys: dict[str, str], timeout_s: float) -> Transport:
    """A key-bearing transport whose key source is the IN-MEMORY dict — the 'in memory only'
    promise for the cloud key is structural, not aspirational. Mirrors the gate's default transport
    apart from the key source and the timeout."""
    async def _call(provider: ProviderConfig, payload: dict) -> dict:
        key = keys.get(provider.name) or ""
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        result = await openai_fetch(f"{provider.base_url.rstrip('/')}/chat/completions", headers,
                                    payload, timeout=timeout_s)
        if result is None:
            raise RuntimeError(f"provider {provider.name} call failed")
        return result
    return _call


def _routing_for(provider_name: str) -> RoutingTable:
    """One provider for every classification — the leg is the only candidate on its own table."""
    return RoutingTable(rules=[], defaults={"local_only": [provider_name],
                                            "local_preferred": [provider_name],
                                            "cloud_permitted": [provider_name]})


async def _register(leg: ModelUnderTest, *, registry: ProviderRegistry, keys: dict[str, str],
                    ollama_url: str, atria_key: str) -> None:
    """Register through the REAL probe and print the honest verdict. Local legs then take the one
    recorded in-memory override (deviation 1); the cloud leg admits fully on its declared revision."""
    if leg.engine == "cloud":
        res = await register_provider(leg.provider, ATRIA_URL, atria_key, model=leg.model,
                                      engine="cloud",
                                      declared={"weights_revision": ATRIA_WEIGHTS_REVISION},
                                      registry=registry, keychain_set=keys)
        print(f"[probe] {leg.label}: reachable={res.reachable} auth_ok={res.auth_ok} "
              f"backend={res.provenance.backend!r} verified={int(res.provenance.verified)} "
              f"-> admission={res.admission}")
        if res.admission == "refused":
            raise RuntimeError(f"probe refused {leg.provider} — no A/B leg is possible against it")
        return
    res = await register_provider(leg.provider, ollama_url, "ollama-nokey-needed", model=leg.model,
                                  engine="ollama", declared={}, registry=registry,
                                  keychain_set=keys)
    honest = registry.get(leg.provider).admitted
    print(f"[probe] {leg.label}: reachable={res.reachable} auth_ok={res.auth_ok} "
          f"backend={res.provenance.backend!r} verified={int(res.provenance.verified)} "
          f"-> honest admission={honest}")
    print(f"[deviation] in-memory admission override for {leg.provider} on this eval leg "
          f"(user-directed 2026-08-28 precedent; CR-3 and src/ untouched; traced verified=0)")
    registry.get(leg.provider).admitted = "full"


async def run_leg(leg: ModelUnderTest, cases: list[GoldenCase], out_dir: Path,
                  trace: TraceStore, *, registry: ProviderRegistry | None = None,
                  keys: dict[str, str] | None = None, ollama_url: str = OLLAMA_URL,
                  atria_key: str = "", recall: tuple[str, ...] = (),
                  gate: EgressGate | None = None) -> int:
    """Run one leg's cases through the gate, appending one sidecar record per case. Returns the
    number of cases SCORED (not merely attempted). A per-case failure never aborts the leg."""
    if registry is None:
        registry, keys = ProviderRegistry(), {}
        await _register(leg, registry=registry, keys=keys, ollama_url=ollama_url,
                        atria_key=atria_key)
    if keys is None:
        keys = {}
    if gate is None:
        timeout = LOCAL_TIMEOUT_S if leg.engine != "cloud" else CLOUD_TIMEOUT_S
        gate = EgressGate(registry=registry, routing=_routing_for(leg.provider), trace=trace,
                          transport=retrying(make_transport(keys, timeout),
                                             attempts=leg.retry_attempts,
                                             min_interval_s=leg.min_interval_s))
    sidecar_path = out_dir / _sidecar_name(leg.label)
    todo = pending(load_sidecar(sidecar_path), [c.id for c in cases], recall)
    print(f"[leg  ] {leg.label}: {len(todo)}/{len(cases)} case(s) to run "
          f"({len(cases) - len(todo)} already complete)")
    scored = 0
    sidecar = sidecar_path.open("a", encoding="utf-8")
    try:
        for case in cases:
            if case.id not in todo:
                continue
            matter = f"eval-a7:{leg.label}:{case.id}"
            try:
                resp = await gate.dispatch(LLMRequest(
                    matter_ref=matter, task_class=case.task_class,
                    messages=[{"role": "user", "content": case.prompt}],
                    max_tokens=leg.output_cap,
                    classification="CLOUD_PERMITTED" if leg.engine == "cloud" else "LOCAL_PREFERRED"))
            except (GateRefusal, Exception) as ex:                 # noqa: BLE001 — record, keep going
                why = f"dispatch failed ({type(ex).__name__}): {ex}"
                print(f"[case ] {leg.label}/{case.id}: {why}")
                rows = trace.by_matter(matter)          # the gate traces even its own refusals
                rec = case_record(case, leg, status="failed", error=why,
                                  model=leg.model,
                                  latency_ms=rows[-1].latency_ms if rows else 0)
                sidecar.write(json.dumps(rec, ensure_ascii=False) + "\n")
                sidecar.flush()
                continue
            # The gate has already traced this dispatch with its measured latency — the sidecar
            # carries it so the dashboard can amortize a local leg's rate without the trace db
            # (substitute.amortized_rate_entry sums tokens AND latency_ms from the sidecar).
            tr = trace.by_matter(matter)[-1]
            if resp.content is None:
                # A reasoning model spent the whole budget on reasoning_content — a CAP failure, not
                # a quality failure. Keep tokens_out so the two are distinguishable; recall-eligible.
                usage = resp.usage or {}
                rec = case_record(case, leg, status="empty_content",
                                  error=(f"content channel empty under output_cap="
                                         f"{leg.output_cap}"),
                                  tokens_in=usage.get("prompt_tokens", 0),
                                  tokens_out=usage.get("completion_tokens", 0),
                                  model=resp.model, latency_ms=tr.latency_ms)
                print(f"[case ] {leg.label}/{case.id}: EMPTY CONTENT "
                      f"(tokens_out={rec['tokens_out']})")
            else:
                sc = score_case(resp.content, case)
                usage = resp.usage or {}
                rec = case_record(case, leg, status="ok", sc=sc, content=resp.content,
                                  tokens_in=usage.get("prompt_tokens", 0),
                                  tokens_out=usage.get("completion_tokens", 0),
                                  model=resp.model, latency_ms=tr.latency_ms)
                scored += 1
                print(f"[case ] {leg.label}/{case.id}: citations={sc.citation_accuracy:.2f} "
                      f"grounding={sc.grounding_score:.2f} "
                      f"checks={sum(sc.checks.values())}/{len(sc.checks)} "
                      f"tokens={rec['tokens_in']}/{rec['tokens_out']}")
            sidecar.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sidecar.flush()
    finally:
        sidecar.close()
    return scored


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ollama-url", default=OLLAMA_URL)
    p.add_argument("--atria-key", default=os.environ.get("IRONFLEET_ATRIA_KEY", ""),
                   help="cloud API key (or $IRONFLEET_ATRIA_KEY); held in memory only")
    p.add_argument("--only", action="append", default=[], metavar="ID-SUBSTR",
                   help="run cases whose id contains this substring (repeatable)")
    p.add_argument("--recall", action="append", default=[], metavar="ID-SUBSTR",
                   help="re-run these cases even if already scored (repeatable)")
    p.add_argument("--legs", action="append", default=[],
                   help="run only legs whose label contains this substring (repeatable)")
    p.add_argument("--cases", type=Path, default=CASES_DIR)
    p.add_argument("--out-dir", type=Path, default=SIDECAR_DIR)
    p.add_argument("--rates", type=Path, default=RATES_PATH)
    return p.parse_args()


async def run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    if args.only:
        cases = [c for c in cases if any(s in c.id for s in args.only)]
    if not cases:
        print(f"FAIL: no cases selected from {args.cases}")
        return 1
    legs = LEGS
    if args.legs:
        legs = [l for l in LEGS if any(s in l.label for s in args.legs)]
    if any(l.engine == "cloud" for l in legs) and not args.atria_key:
        print("FAIL: a cloud leg is selected but --atria-key / $IRONFLEET_ATRIA_KEY is empty")
        return 1
    # Rate-table integrity BEFORE any model is billed a token (spec §7).
    try:
        table = RateTable.from_yaml(args.rates)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as ex:
        print(f"FAIL: cannot load rate table {args.rates} ({type(ex).__name__}: {ex})")
        return 1
    for leg in legs:
        table.require(leg.rate_key)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    trace = TraceStore(args.out_dir / f"trace-s7h-{stamp}.db")
    print(f"[setup] {len(cases)} case(s) x {len(legs)} leg(s); trace db: {trace.db_path}")
    print("[setup] models on the local server are honestly mechanical-only per CR-3; local legs "
          "carry the recorded in-memory admission override for this eval run")
    if any(l.engine == "cloud" for l in legs):
        print("[deviation] the golden corpus is dispatched to api.atria-asi.ai on the user's "
              "2026-10-06 direction; the corpus is authored from PUBLIC judgments, not client "
              "matter data, and the API key is held in memory only")
        print("[probe    ] note: verified=1 on the cloud leg means DECLARED AND RECORDED, not "
              "cryptographically proven — the dashboard says so")
    dead_legs = 0
    unfinished = 0
    for leg in legs:
        print(f"[leg  ] starting {leg.label} ({leg.role}, output_cap={leg.output_cap}, "
              f"min_interval_s={leg.min_interval_s})")
        try:
            scored = await run_leg(leg, cases, args.out_dir, trace, ollama_url=args.ollama_url,
                                   atria_key=args.atria_key, recall=tuple(args.recall))
        except Exception as ex:                                   # noqa: BLE001 — a dead leg is UNUSABLE
            print(f"[leg  ] {leg.label} FAILED as a leg: {ex}")
            dead_legs += 1
            continue
        total = len(pending(load_sidecar(args.out_dir / _sidecar_name(leg.label)),
                            [c.id for c in cases], ()))
        print(f"[leg  ] {leg.label} done: {scored} scored, {total} still pending")
        unfinished += total
    print(f"[done ] sidecars in {args.out_dir}/A7-<label>.jsonl; next: scripts/build_dashboard.py")
    if dead_legs or unfinished:
        print(f"FAIL: {dead_legs} leg(s) failed outright, {unfinished} case(s) still pending "
              f"— the run is not complete; the exit status says so")
        return 1
    return 0


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)      # progress lines must survive redirection
    sys.exit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
