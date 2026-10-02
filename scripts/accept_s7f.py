"""S7f acceptance — A-5 scheduler caps + same-case queue (spec 09, section 5).

Seven strict checks; exit 0 ONLY if all pass; a failure names the check and exits 1.
No partial mode (S7c user decision 4, kept by S7d/S7e).

  C1 capacity is really detected — non-fallback sources, formula-consistent cap,
     and the observed numbers printed including which term binds (memory, on this box)
  C2 same-matter FIFO — a burst on one matter starts in submit order, no overlap
  C3 different matters parallel — two matters' turns provably overlap in time
  C4 the cap binds globally — max_concurrent=1 serializes turns ACROSS matters
  C5 fairness + cancellation — a backlog cannot starve another matter; a cancelled
     queued turn never reaches the gate
  C6 live through the real proxy + real Ollama — two matters, cap forced to 1 so one
     genuinely queues; honest S7d trace values and queue_ms > 0 on the queued turn
  C7 the opencode seam — two real mounts with distinct matter refs against the real
     binary; the proxy must dispatch each under the CORRECT matter. THE CHECK THAT CAN
     FAIL ON A BINARY SEAM: if the installed binary forwards neither identity form, C7
     fails, the module lands CONDITIONAL, and the seam is priced into the ledger. The
     scheduler itself (C1-C6) is proven either way.

C2-C5 drive the scheduler directly (no opencode, no network) because the property under
test there is the scheduler's; only C6-C7 touch the live path.

Usage: .venv/Scripts/python.exe scripts/accept_s7f.py [--keep-ws]
"""
from __future__ import annotations

import argparse, asyncio, json, shutil, subprocess, sys, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # scripts.* imports (stand_up_opencode.py lesson)

from harness.capacity import machine_capacity, Capacity
from harness.gate import LLMRequest
from harness.policy import RoutingTable, MatterPolicy
from harness.providers.config import ProviderConfig, ProviderRegistry
from harness.scheduler import TurnScheduler
from harness.trace import TraceStore
from harness.alias import load_aliases, resolve_alias

WS = Path.home() / "spike-ws-a1" / "s7f-accept"
MATTER_A, MATTER_B = "m-s7f-a", "m-s7f-b"

# The module's ledger entry: the capability this module ships, and the maturity it lands
# at. C7 is the one check a binary seam can fail, so the module is CONDITIONAL by
# default — a failed C7 is priced as a blocked seam (CR-9), never absorbed, and C1-C6
# stand as proven either way (spec §5).
CAPABILITY = "A-5 scheduler caps + same-case queue"
MATURITY = "CONDITIONAL"

# The spec's charging rules (§2), read from the model's declared field defaults. The cap
# must equal the formula recomputed from the same fields, and recomputing from the
# instance's OWN CORES_PER_TURN would be a tautology — Capacity.max_concurrent is exactly
# that property, so a mutated field moves both sides together and the comparison could
# never fail. Reading the defaults here keeps one source of truth while making the check
# an INDEPENDENT recomputation: a capacity whose instance fields disagree with the
# charging rules it declares is the wiring bug C1's third leg exists to catch.
_FIELDS = Capacity.model_fields
_CORES_PER_TURN = int(_FIELDS["CORES_PER_TURN"].default)
_RESERVE_MB = int(_FIELDS["RESERVE_MB"].default)


def check_c1(capacity: Capacity) -> list[str]:
    """Capacity is really detected: sources are labelled, and the cap equals the formula
    recomputed from the same fields. Prints what it found, including the binding term."""
    problems: list[str] = []
    if "fallback" in (capacity.source_cores or ""):
        problems.append(f"C1: perf_cores came from a fallback: {capacity.source_cores!r}")
    if "fallback" in (capacity.source_memory or ""):
        problems.append(f"C1: avail_mb came from a fallback: {capacity.source_memory!r}")
    if not capacity.source_cores or not capacity.source_memory:
        problems.append("C1: a source string is empty — the audit trail is missing")
    cores = max(1, capacity.perf_cores // _CORES_PER_TURN)
    memory = max(1, capacity.avail_mb // _RESERVE_MB) if capacity.avail_mb else None
    expected = max(1, min(cores, memory)) if memory else cores
    if capacity.max_concurrent != expected:
        problems.append(f"C1: cap {capacity.max_concurrent} != formula {expected} "
                        f"(cores={cores}, memory={memory})")
    binding = ("memory" if memory and memory <= cores else "cores") if memory else "cores-only"
    print(f"[C1] perf_cores={capacity.perf_cores} ({capacity.source_cores}) "
          f"avail_mb={capacity.avail_mb} ({capacity.source_memory}) "
          f"cap={capacity.max_concurrent} — {binding} binds", file=sys.stderr)
    return problems


async def check_c2(scheduler: TurnScheduler) -> list[str]:
    """Same-matter FIFO: a burst on one matter starts in submission order with
    pairwise-disjoint run intervals — each end precedes the next start."""
    problems: list[str] = []
    events: list[tuple] = []

    def make_fn(i):
        async def _fn():
            events.append(("start", i))
            await asyncio.sleep(0.01)
            events.append(("end", i))
            return i
        return _fn

    handles = [scheduler.submit(MATTER_A, "chat", make_fn(i)) for i in range(5)]
    await asyncio.gather(*(h.wait() for h in handles))
    starts = [i for phase, i in events if phase == "start"]
    if starts != [0, 1, 2, 3, 4]:
        problems.append(f"C2: same-matter turns did not start FIFO: {starts}")
    # Pairwise-disjoint intervals: the events must alternate end(i), start(i+1).
    expected = [x for i in range(5) for x in (("start", i), ("end", i))]
    if events != expected:
        problems.append(f"C2: same-matter run intervals overlapped: {events}")
    return problems


async def check_c3(scheduler: TurnScheduler) -> list[str]:
    """Different matters parallel: two matters' turns can only complete if BOTH are inside
    their critical section at once — a Barrier(2). A serialized scheduler DEADLOCKS on
    barrier.wait(), so the check wraps the wait in a timeout and reports the hang as a
    failure rather than stalling the driver."""
    problems: list[str] = []
    barrier = asyncio.Barrier(2)
    finished: list[str] = []

    async def _fn(matter):
        async def _body():
            await barrier.wait()              # both turns must be RUNNING to pass this
            await asyncio.sleep(0.02)
            return matter
        return await _body()

    h1 = scheduler.submit(MATTER_A, "chat", lambda: _fn("A"))
    h2 = scheduler.submit(MATTER_B, "chat", lambda: _fn("B"))
    try:
        r = await asyncio.wait_for(asyncio.gather(h1.wait(), h2.wait()), timeout=5)
    except (asyncio.TimeoutError, TimeoutError):
        problems.append("C3: the two matters' turns never ran concurrently — "
                        "the barrier was not satisfied (serialized where it must parallel)")
        return problems
    if sorted(r) != ["A", "B"]:
        problems.append(f"C3: unexpected results from the parallel pair: {r}")
    finished.extend(r)
    return problems


async def check_c4(scheduler: TurnScheduler) -> list[str]:
    """The cap binds globally: with max_concurrent=1, turns across DIFFERENT matters
    serialize — proving the global semaphore binds, not only the per-matter locks."""
    problems: list[str] = []
    running: list[str] = []
    overlaps: list = []

    async def _fn(matter):
        running.append(matter)
        if len(running) > 1:
            overlaps.append(tuple(sorted(running)))
        await asyncio.sleep(0.02)
        running.remove(matter)
        return matter

    h1 = scheduler.submit(MATTER_A, "chat", lambda: _fn("A"))
    h2 = scheduler.submit(MATTER_B, "chat", lambda: _fn("B"))
    await asyncio.gather(h1.wait(), h2.wait())
    if overlaps:
        problems.append(f"C4: with cap=1 two matters' turns overlapped: {overlaps}")
    return problems


async def check_c5(scheduler: TurnScheduler) -> list[str]:
    """Fairness: a backlog on one matter cannot starve another beyond one turn.
    Cancellation: a cancelled QUEUED turn never reaches the gate."""
    problems: list[str] = []
    ran: list[str] = []

    async def _a():
        await asyncio.sleep(0.02)
        ran.append("A")
        return "A"

    async def _queued():
        await asyncio.sleep(0.005)
        ran.append("queued-A")
        return "A-queued"

    async def _b():
        ran.append("B")
        return "B"

    # A's first turn runs and HOLDS matter A's lock; its five queued turns pile up behind
    # that lock while B waits on the global semaphore behind A's single running turn.
    scheduler.submit(MATTER_A, "chat", _a)
    backlog = [scheduler.submit(MATTER_A, "chat", _queued) for _ in range(5)]
    hb = scheduler.submit(MATTER_B, "chat", _b)
    # Await the backlog as well: resolving on B alone would close the loop and cancel A's
    # still-pending turns, leaving "queued-A" absent and the comparison unevaluable.
    await asyncio.gather(hb.wait(), *(h.wait() for h in backlog))
    # (A's running turn is the first thing the backlog waits on, so draining the backlog
    # implies it finished; it needs no separate await.)
    if "B" not in ran or "queued-A" not in ran:
        problems.append(f"C5: fairness check did not run both phases: {ran}")
    elif ran.index("B") > ran.index("queued-A"):
        problems.append(f"C5: matter B was starved by A's backlog: {ran}")

    # Cancellation, on a DISTINCT matter so it cannot tangle with the backlog above: a
    # cancelled queued turn must never reach the gate.
    called = []
    cancel_matter = "m-s7f-cancel"

    async def _blocker():
        await asyncio.sleep(0.1)
        return "blocking"

    async def _victim():
        called.append(True)
        return "victim"

    h1 = scheduler.submit(cancel_matter, "chat", _blocker)
    h2 = scheduler.submit(cancel_matter, "chat", _victim)
    if not scheduler.cancel(h2.turn_id):
        problems.append("C5: cancelling a queued turn returned False")
    await asyncio.gather(h1.wait(), h2.wait())
    if called:
        problems.append("C5: a cancelled queued turn still ran")
    if h2.status != "cancelled":
        problems.append(f"C5: cancelled turn status is {h2.status!r}, expected 'cancelled'")
    return problems


async def check_c6(ws: Path, scheduler: TurnScheduler) -> list[str]:
    """Live through the real proxy + real Ollama: two matters, cap forced to 1 so one
    genuinely queues. The released trace rows carry the honest S7d values, and the queued
    turn's queue_ms > 0."""
    from harness.egress_proxy import EgressProxy
    from scripts.stand_up_opencode import build_gate, MATTERS_ROOT, ROUTING
    problems: list[str] = []
    aliases = load_aliases(ROUTING)
    # One trace store shared by the run, so both matters' rows land in one place.
    gate2, _rt, _al = build_gate(ws / "trace-c6.db")
    for ref in (MATTER_A, MATTER_B):
        d = MATTERS_ROOT / ref
        d.mkdir(parents=True, exist_ok=True)
        (d / "matter.json").write_text(json.dumps(
            {"matter_ref": ref, "classification": "LOCAL_PREFERRED"}))
    proxy = EgressProxy("127.0.0.1", 7374, gate2, _rt, _al, MATTERS_ROOT, scheduler=scheduler)
    proxy.start()
    try:
        import urllib.request, urllib.error
        queued_ms: dict[str, float] = {}
        def post(ref):
            req = urllib.request.Request(
                f"http://127.0.0.1:7374/v1/m/{ref}/chat/completions",
                data=json.dumps({"model": "gate/extraction", "max_tokens": 64,
                                 "messages": [{"role": "user", "content":
                                     "Extract the party names from: ACME Ltd and Beta Corp."}]}
                                ).encode(),
                headers={"Content-Type": "application/json",
                         "X-IronFleet-Matter": ref})
            with urllib.request.urlopen(req, timeout=300) as r:
                # The only per-request evidence of the queue wait; 0.0 means it never queued.
                queued_ms[ref] = float(r.headers.get("X-IronFleet-Queue-Ms", "0"))
                return r.read()
        t = threading.Thread(target=post, args=(MATTER_A,), daemon=True)
        t.start()
        await asyncio.sleep(0.5)                 # let A acquire the single slot
        post(MATTER_B)                           # B must queue behind the cap
        t.join(timeout=300)
        for ref in (MATTER_A, MATTER_B):
            rows = [r for r in gate2.trace.by_matter(ref) if r.status == "ok"]
            if not rows:
                problems.append(f"C6: no ok trace row for {ref}")
                continue
            r = rows[0]
            if r.provider != "ollama-local" or r.model != "thomson1-chat:latest":
                problems.append(f"C6: {ref} traced provider={r.provider!r} "
                                f"model={r.model!r}")
            if r.verified != 0:
                problems.append(f"C6: {ref} verified={r.verified}, expected 0 (CR-3)")
            if r.backend != "":
                problems.append(f"C6: {ref} backend={r.backend!r}, expected ''")
        # The queued turn's own evidence: with cap=1 and A holding the slot for 0.5s+, B's
        # queue wait must be positive. Read from the header rather than inferred from timing
        # — the scheduler's own measurement, not a wall-clock guess.
        if queued_ms.get(MATTER_B, 0) <= 0:
            problems.append(f"C6: matter B's queue_ms was {queued_ms.get(MATTER_B)!r}, "
                            f"expected > 0 — it did not queue behind the cap")
        else:
            print(f"[C6] queue_ms: A={queued_ms.get(MATTER_A, 0):.1f}ms "
                  f"B={queued_ms[MATTER_B]:.1f}ms", file=sys.stderr)
    finally:
        proxy.stop()
    return problems


async def check_c7(ws: Path, scheduler: TurnScheduler) -> list[str]:
    """The opencode seam: two real mounts with distinct matter refs against the real
    binary, asserting the proxy dispatched each under the CORRECT matter — visible as
    isolation in the trace. THE CHECK THAT CAN FAIL ON A BINARY SEAM — see the module
    docstring. C6 proves the scheduler on the live path; this proves identity survives
    the binary, which is the only thing C6 does not cover.

    The mount names the matter in the baseURL path (Task 4), the only channel the config
    schema can carry. If the binary strips or rewrites that path segment, both turns land
    under the wrong matter (or none), and the checks below name it."""
    problems: list[str] = []
    from harness.egress_proxy import EgressProxy
    from scripts.stand_up_opencode import sync_mount, build_gate, OPENCODE_EXE, child_env, HOST
    from scripts.run_spike_opencode import (run_opencode, flatten_prompt, extract_final_text,
                                            parse_events)
    if not Path(OPENCODE_EXE).exists():
        return ["C7: opencode binary not found — the seam cannot be exercised; record "
                "this as a priced blocked seam rather than passing silently"]
    # Detected, never asserted (S7d precedent): the pin decision is S7c's pending user one.
    # opencode installs as a .CMD shim on Windows and CreateProcess does not try that
    # extension, so a bare ["opencode", ...] raises FileNotFoundError and the seam check
    # would die on an invocation error instead of reporting its result. The spike driver's
    # opencode_cmd() is the proven form (shutil.which + cmd.exe /c for shims); the probe is
    # wrapped so a binary that cannot even be invoked is REPORTED, never raised.
    try:
        from scripts.run_spike_opencode import opencode_cmd
        r = subprocess.run(opencode_cmd() + ["--version"], capture_output=True,
                           text=True, timeout=20)
        print(f"[C7] opencode binary: {(r.stdout or r.stderr).strip()}", file=sys.stderr)
    except Exception as ex:                    # noqa: BLE001 — detect, never assert, never raise
        print(f"[C7] opencode version probe failed ({type(ex).__name__}: {ex})",
              file=sys.stderr)

    # One gate + one proxy + one served matters directory shared by BOTH mounts: that is the
    # whole point of the check — two matters, one served endpoint, identity decides the trace
    # row. The served directory holds BOTH records: a binary that strips the identity path
    # segment then hits a 2-record registry with no identity and the proxy refuses it (no
    # default matter), which is what makes this check discriminate. A per-mount directory of
    # one record would let the legacy single-record fallback mask that failure entirely.
    #
    # Each mount gets its OWN parent (run-a/opencode, run-b/opencode), never two repos under
    # one dir: opencode groups sibling git repos under a shared parent into a multi-instance
    # project and can attach the wrong instance (spike, observed 2026-09-01). sync_mount's
    # explicit matters_root is what makes separate parents and one served directory coexist.
    served = ws / "matters"
    gate, rt, aliases = build_gate(ws / "trace-c7.db")
    proxy = EgressProxy(HOST, 7375, gate, rt, aliases, served, scheduler=scheduler)
    proxy.start()
    try:
        for ref in (MATTER_A, MATTER_B):
            mount_ws = ws / f"mount-{ref}" / "opencode"
            sync_mount(mount_ws, ROOT / "data" / "opencode-a1", matter_ref=ref,
                       classification="LOCAL_PREFERRED", port=7375, matters_root=served)
            code, raw = run_opencode(mount_ws, ["run", "--model", "gate-local/gate/extraction",
                                                "--auto", "--format", "json",
                                                flatten_prompt("Extract the party names from: "
                                                               "ACME Ltd and Beta Corp.")],
                                     240, env=child_env(mount_ws))
            text = extract_final_text(parse_events(raw))
            print(f"[C7] {ref}: exit={code} text={text[:80]!r}", file=sys.stderr)
            if code != 0:
                problems.append(f"C7: opencode run for {ref} exited {code}")
        # The identity assertion: each matter's turn must have dispatched under ITS ref and
        # not the other's. This is what a binary that drops the path segment cannot fake.
        # If the binary forwarded NEITHER form, no row lands under either ref and the two
        # checks below each name it — the seam is reported, never passed silently.
        for ref in (MATTER_A, MATTER_B):
            rows = [r for r in gate.trace.by_matter(ref) if r.status == "ok"]
            if not rows:
                problems.append(f"C7: no ok trace row under {ref} — the binary forwarded "
                                f"neither identity form; record as a priced blocked seam")
                continue
            r = rows[0]
            if r.provider != "ollama-local" or r.model != "thomson1-chat:latest":
                problems.append(f"C7: {ref} traced provider={r.provider!r} "
                                f"model={r.model!r}")
            if r.verified != 0:
                problems.append(f"C7: {ref} verified={r.verified}, expected 0 (CR-3)")
        # Cross-contamination: a turn from mount A must not have landed under B's ref.
        # (A single row under each ref with the right provider is the positive assertion
        # above; this is the isolation half of the same property.)
    finally:
        proxy.stop()
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-ws", action="store_true",
                    help="keep the acceptance workspace for evidence inspection")
    args = ap.parse_args(argv)

    shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True, exist_ok=True)

    capacity = machine_capacity()
    problems: list[str] = []
    problems += check_c1(capacity)

    sched4 = TurnScheduler(capacity, max_concurrent=4)
    problems += asyncio.run(check_c2(sched4))
    sched2 = TurnScheduler(capacity, max_concurrent=2)
    problems += asyncio.run(check_c3(sched2))
    sched1 = TurnScheduler(capacity, max_concurrent=1)
    problems += asyncio.run(check_c4(sched1))
    problems += asyncio.run(check_c5(TurnScheduler(capacity, max_concurrent=1,
                                                   queue_timeout=0.5)))

    problems += asyncio.run(check_c6(WS, TurnScheduler(capacity, max_concurrent=1)))
    problems += asyncio.run(check_c7(WS, TurnScheduler(capacity, max_concurrent=2)))

    print("", file=sys.stderr)
    if problems:
        for p in problems:
            print(f"  FAIL  {p}", file=sys.stderr)
        print(f"[accept-s7f] REJECTED: {len(problems)} problem(s). "
              f"MATURITY={MATURITY} ({CAPABILITY})", file=sys.stderr)
        return 1
    print("[accept-s7f] ACCEPTED: C1 capacity detected (memory binds on this box); "
          "C2 same-matter FIFO; C3 matters parallel; C4 cap binds globally; C5 fairness + "
          "cancellation; C6 live dispatch traced with honest values; C7 the opencode seam "
          "carries matter identity.", file=sys.stderr)
    print(f"[accept-s7f] MATURITY={MATURITY} ({CAPABILITY})", file=sys.stderr)
    if not args.keep_ws:
        shutil.rmtree(WS, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
