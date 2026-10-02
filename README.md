# Harness

Phase 0 foundation package for IronFleet harness-core.

## Status

Phase 0 of the Rev-2 merged programme. See [specs](../specs/) and [IronFleet_Merged_Programme.pdf](../IronFleet_Merged_Programme.pdf) for full context and architecture.

## Quickstart

```bash
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
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

## Local inference on Windows

`llama-server` (llama.cpp) is the supported Windows local engine — it serves an
OpenAI-compatible API on `http://127.0.0.1:8080/v1` and reports its actual
build via `/props`, so the probe can verify it:

```python
import asyncio
from harness.providers.probe import register_provider

res = asyncio.run(register_provider(
    "win-llamacpp", "http://127.0.0.1:8080/v1", "dummy",   # llama-server ignores auth
    model="<served-model-name>",                            # the name llama-server serves
    engine="llamacpp",
    declared={"weights_revision": "<gguf-sha256-or-tag>"},
))
print(res.admission)                                       # full
```

Start the server pinned to one GGUF (`llama-server -m <path-to-model.gguf>`);
record the file's sha256 (or tag) as `declared={"weights_revision": ...}`.
The probe verifies by fetching `/props` and requiring non-empty `build_info` —
declared revision plus a real executing backend is `admission="full"`.
**Ollama on any OS stays mechanical-only** (CR-3): it silently substitutes the
executing backend, so its provenance can never be verified.

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

Real OpenAI-compatible endpoints do not send `_server_meta`, so per-dispatch provenance is: weights revision as declared (pinned), backend as **discovered by the probe at registration** (`discovered_backend`), `verified=0` unless the wire itself reports a matching revision (S6-2). On Ollama — which cannot report its executing backend — rows read `backend=''`, `verified=0`. That is by design, not a fault. An explicit empty wire value falls through to the probe's finding (the `or` chain treats falsy as absent). An admitted cloud provider records `backend='saas'` — the probe's synthesized tier label, not a local engine.

## Local embeddings (A-4 / S7e)

The `embedding` task class is a **mechanical slot** that runs LOCAL-ONLY. Embedding
privileged text via a cloud API is an egress event, so the gate enforces this
structurally — `harness.policy.LOCAL_ONLY_TASKS` drops any cloud-tier provider for the
class *before* routing-table preferences are honoured. A cloud embedder named in the
embedding rule's `cloud_permitted` list is unreachable; that is tested adversarially in
`scripts/accept_s7e.py` (C2), not merely asserted.

`EgressGate.embed()` is a sibling of `dispatch()`: same routing, admission, provenance and
trace row; only the endpoint (`/embeddings`) and the payload differ. The local embedding
provider is `ollama-embed` (Ollama, `bge-m3:567m`, 1024-dim), registered through the same
probe as every other provider. Its admission is honestly `mechanical-only` with
`verified=0` — Ollama cannot report its executing backend (CR-3), and embeddings are
deterministic mechanical work, which is precisely what the mechanical tier is for.

`harness.vectors.VectorStore` is the thin local index: float32 vectors as SQLite BLOBs
(stdlib `array`), pure-Python cosine search, scoped by `matter_ref` — a search for one
matter never surfaces another's vectors. **Scaling caveat, stated plainly:** this is the
index A-4 was priced for (thousands to tens of thousands of chunks per matter). Pure-Python
cosine is O(rows x dims) per query; swap in sqlite-vec or numpy later behind the same
interface — the interface is the stable surface, the cosine is not.

## Multi-window scheduling (A-5 / S7f)

Different matters run fully in parallel; turns on the **same** matter serialize through a
per-matter FIFO; and total concurrency is capped by this machine's measured performance
cores **and** available memory.

`harness.capacity.machine_capacity()` detects both numbers with stdlib per-platform probes
(`ctypes` on Windows, `sysctl` on macOS, `/proc` on Linux) and records *how* each was
obtained in a `source_*` string — the same provenance discipline the gate applies to
providers. The cap is:

```
max_concurrent = max(1, min(perf_cores // 2, avail_mb // 20480))
```

The `20480` MB reserve is the served model's measured weight footprint (20,398 MB for
`thomson1-chat` 34.7B Q4_K_M, rounded up to a whole GiB), so an admitted turn can always
**cold-load** its model into free RAM rather than betting the server still holds it
resident. On the dev box (12 performance-class logical CPUs, ~52 GiB available) this makes
**memory the binding term: the cap is 2.** Two matters run concurrently; a third queues. An
explicit `HARNESS_MAX_CONCURRENT` env var overrides the derivation.

The scheduler is `harness.scheduler.TurnScheduler`. Each turn acquires its matter's lock and
then one global semaphore, in that fixed order — which gives same-matter FIFO serialization,
cross-matter parallelism, and a fairness property that is structural rather than configured:
a matter holds its own lock only while *running*, so its queued turns wait on the matter lock
and each matter contributes at most one turn to the global queue. No matter's backlog can
starve another beyond a single turn.

The egress proxy is **multi-matter**: a request identifies its matter by an
`X-IronFleet-Matter` header, a `/v1/m/<ref>/chat/completions` path, or the legacy single
`matter.json` (in that precedence), and an unregistered matter is refused with
`500 matter_unavailable` — no passthrough, no default matter. Every dispatch is submitted to
the scheduler as a turn. A turn that waits beyond the queue timeout returns `503` with
`Retry-After`, so a saturated queue makes the client back off rather than fan retries into
identical trace rows.

**Honest caveat:** the queue is in-process. If the proxy dies, the queue dies with it — a
queued turn is re-issued by its window. A persistent job table is deferred to the shell step
that will consume it.

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
- **Ops runbook** (`P0-7`, per OS): See [RUNBOOK_P0_7.md](src/harness/ops/RUNBOOK_P0_7.md) — encrypted-at-rest store + versioned backup on macOS (`p07_setup_macos.sh` / `p07_verify_macos.sh`), Windows (`p07_setup_windows.ps1` / `p07_verify_windows.ps1`), and Linux (`p07_setup_linux.sh` / `p07_verify_linux.sh`).

The `HARNESS_HOME` environment variable sets the store root for the Windows and Linux ops scripts (macOS uses the IronFleetPriv volume).
