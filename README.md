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
from harness.core.gate import EgressGate
from harness.routing.table import RoutingTable
from harness.storage.trace import TraceStore
from harness.models.requests import LLMRequest

registry = load_registry()  # from provider DB
table = RoutingTable.from_yaml("data/routing.yaml")
traces = TraceStore("data/traces")
gate = EgressGate(registry, table, traces)

req = LLMRequest(task_class="legal_qa", classification="client_question", messages=[...])
try:
    response = await gate.dispatch(req)
except GateRefusal as e:
    print(f"Request refused: {e.reason}")
```

## Eval

```python
from harness.eval.runner import run_eval

report_path = run_eval(gate, "data/golden_cases", "reports/eval.md")
```

Golden-case YAML format doubles as Jonathan's P0-4b authoring template. See `data/golden_cases/` for examples.

## Spike

See [SPIKE_PROTOCOL.md](src/harness/spike/SPIKE_PROTOCOL.md) and [SEAM_COUNT.md](src/harness/spike/SEAM_COUNT.md) for spike scaffolding and execution protocol (P0-5).

## Security & Operations

- **Provider verification** (`P0-6`): See [dsh_precheck.py](src/harness/security/dsh_precheck.py) for security preflight checks.
- **Runbook** (`P0-7`, macOS-only): See [RUNBOOK_P0_7.md](src/harness/ops/RUNBOOK_P0_7.md) for operational procedures.
