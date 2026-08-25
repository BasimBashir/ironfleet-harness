"""Live smoke test against a local Ollama instance (Windows dev machine, D13).

Demonstrates the CR-3 behavior end-to-end with a REAL local LLM:
  1. Register Ollama through the provenance-verifying probe.
     Expected: reachable/auth OK, models listed, provenance UNVERIFIED (Ollama does not
     report the actual executing backend per request) -> admission "mechanical-only".
  2. Dispatch a PRIVILEGED task class (drafting) -> GateRefusal, traced as refused.
  3. Dispatch a MECHANICAL task class (extraction) -> real completion from the local
     model through the gate, traced with verified=0 (honest), engine=ollama.

Usage:  .venv/Scripts/python.exe scripts/live_ollama_smoke.py [base_url]
Default base_url: http://127.0.0.1:11434/v1
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.gate import EgressGate, GateRefusal, LLMRequest  # noqa: E402
from harness.policy import RoutingTable  # noqa: E402
from harness.providers.config import ProviderRegistry  # noqa: E402
from harness.providers.http_fetch import openai_fetch  # noqa: E402
from harness.providers.probe import register_provider  # noqa: E402
from harness.trace import TraceStore  # noqa: E402

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:11434/v1"
PROVIDER_NAME = "ollama-local"


async def detect_model() -> str:
    payload = await openai_fetch(f"{BASE_URL.rstrip('/')}/models", {})
    if not payload:
        print(f"FAIL: cannot reach {BASE_URL}/models — is Ollama running?")
        sys.exit(1)
    models = [m.get("id", "") for m in payload.get("data", [])]
    print(f"[probe] models on {BASE_URL}: {models}")
    qwen = [m for m in models if "qwen" in m.lower()]
    model = qwen[0] if qwen else (models[0] if models else "")
    if not model:
        print("FAIL: no models served by Ollama")
        sys.exit(1)
    return model


async def main() -> None:
    model = await detect_model()
    print(f"[setup] using model: {model}")

    registry = ProviderRegistry()
    keys: dict[str, str] = {}
    res = await register_provider(
        PROVIDER_NAME, BASE_URL, "ollama-nokey-needed", model=model, engine="ollama",
        declared={"weights_revision": ""},   # nothing declared: Ollama cannot verify anyway
        registry=registry, keychain_set=keys,
    )
    print(f"[probe] reachable={res.reachable} auth_ok={res.auth_ok} models={res.models}")
    print(f"[probe] provenance.verified={res.provenance.verified} "
          f"backend={res.provenance.backend!r} -> admission={res.admission}")
    assert res.admission == "mechanical-only", (
        f"expected mechanical-only for Ollama (CR-3), got {res.admission}")

    # Routing: ollama-local is the only provider for every class.
    routing = RoutingTable(rules=[], defaults={
        "local_only": [PROVIDER_NAME],
        "local_preferred": [PROVIDER_NAME],
        "cloud_permitted": [PROVIDER_NAME],
    })
    # ignore_cleanup_errors: WAL sqlite handles can still be open on Windows at exit
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        gate = EgressGate(registry=registry, routing=routing,
                          trace=TraceStore(Path(td) / "live.db"))

        # --- 2. privileged task class must be refused (fail-closed) ---
        try:
            await gate.dispatch(LLMRequest(
                matter_ref="LIVE-DEMO", task_class="drafting",
                messages=[{"role": "user", "content": "Draft a one-line demand letter."}],
                max_tokens=32))
            print("FAIL: drafting dispatch unexpectedly succeeded")
            sys.exit(1)
        except GateRefusal as e:
            row = gate.trace.by_matter("LIVE-DEMO")[0]
            print(f"[gate ] drafting REFUSED as designed: {e}")
            print(f"[trace] status={row.status} classification={row.classification} error={row.error!r}")
            assert row.status == "refused"

        # --- 3. mechanical task class dispatches for real through the gate ---
        resp = await gate.dispatch(LLMRequest(
            matter_ref="LIVE-DEMO", task_class="extraction",
            messages=[{"role": "user",
                       "content": "Extract the party names as a JSON list. Text: "
                                  "Between ACME Ltd (creditor) and John Smith (debtor). "
                                  "Reply with JSON only."}]))   # default max_tokens (128k) applies
        print(f"[gate ] extraction OK via {resp.provider} / {resp.model}")
        print(f"[model ] {resp.content.strip()[:200]!r}")
        rows = [r for r in gate.trace.by_matter("LIVE-DEMO") if r.status == "ok"]
        assert rows, "no ok trace row for the extraction dispatch"
        row = rows[0]
        print(f"[trace] engine={row.engine} model={row.model} verified={row.verified} "
              f"tokens_in={row.tokens_in} tokens_out={row.tokens_out} latency_ms={row.latency_ms}")
        assert row.engine == "ollama" and row.model == model and row.verified == 0
        assert row.tokens_in > 0 and row.tokens_out > 0

    print("\nLIVE SMOKE PASSED: Ollama registered mechanical-only (CR-3); "
          "drafting refused fail-closed; extraction served locally and traced honestly.")


if __name__ == "__main__":
    asyncio.run(main())
