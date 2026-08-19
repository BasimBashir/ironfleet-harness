# Harness

Phase 0 foundation package for IronFleet harness-core.

## Status

Phase 0 of the Rev-2 merged programme. See [specs](../specs/) and [IronFleet_Merged_Programme.pdf](../IronFleet_Merged_Programme.pdf) for full context and architecture.

## Quickstart

```bash
pip install -e ".[dev]"
```

Run tests with `pytest` from the repo root. Tests use async support configured in `pyproject.toml`.

Key fixtures:
- `harness_home`: Provides isolated `HARNESS_HOME` environment variable
- `fake_transport`: Mock OpenAI-compatible completion for testing

## Register a provider

```python
import asyncio
from harness.providers.probe import register_provider

res = asyncio.run(register_provider(
    "mini1-mlx", "http://mini1:8080/v1", "<api-key>",
    model="qwen3.8-27b",                # default local model (D12) — endpoints serve multiple LLMs
    engine="mlx-lm",
    declared={"weights_revision": "<pinned-revision>"},
))
print(res.admission)                     # full | mechanical-only | refused
```

The probe refuses or restricts any endpoint that cannot verifiably report weights revision + executing backend (CR-3).

## Routing

Edit `data/routing.yaml` to configure task_class × classification → provider mappings. The routing table drives provider selection based on request characteristics.

## Dispatch

```python
import asyncio
from harness.gate import EgressGate, LLMRequest, GateRefusal
from harness.policy import RoutingTable
from harness.providers.config import ProviderRegistry
from harness.trace import TraceStore

registry = ProviderRegistry()          # populated via register_provider(...)
table = RoutingTable.from_yaml("data/routing.yaml")
gate = EgressGate(registry, table, TraceStore("trace.db"))

req = LLMRequest(matter_ref="M-001", task_class="drafting",
                 classification="LOCAL_PREFERRED", messages=[{"role": "user", "content": "..."}])
try:
    resp = asyncio.run(gate.dispatch(req))
except GateRefusal as e:                # fail-closed: nothing dispatches outside the gate
    print(f"refused: {e}")
```

Real OpenAI-compatible endpoints do not send `_server_meta`, so production trace rows read `verified=0` until a provenance sidecar exists — that is by design, not a fault.

## Eval

```python
import asyncio
from harness.eval.runner import run_eval

scores = asyncio.run(run_eval(gate, "data/golden_cases", "report.md"))
# returns list[CaseScore]; also writes report.md
```

Golden-case YAML format doubles as Jonathan's P0-4b authoring template. See `data/golden_cases/` for examples.

## Spike

See [SPIKE_PROTOCOL.md](src/harness/spike/SPIKE_PROTOCOL.md) and [SEAM_COUNT.md](src/harness/spike/SEAM_COUNT.md) for spike scaffolding and execution protocol (P0-5).

## Security & Operations

- **DSH supply-chain pre-check** (`P0-6`): See [dsh_precheck.py](src/harness/security/dsh_precheck.py) for security preflight checks.
- **Runbook** (`P0-7`, macOS-only): See [RUNBOOK_P0_7.md](src/harness/ops/RUNBOOK_P0_7.md) for operational procedures.
