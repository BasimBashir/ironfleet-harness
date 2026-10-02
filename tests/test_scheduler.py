# tests/test_scheduler.py — A-5 per-matter FIFO + global cap (spec §3)
import asyncio
import pytest
from harness.capacity import Capacity
from harness.scheduler import TurnScheduler


def _cap():
    # A synthetic machine whose cap is whatever max_concurrent says — capacity logic is
    # tested in tests/test_capacity.py; these tests exercise the locks.
    return Capacity(perf_cores=99, avail_mb=999_999, source_cores="t", source_memory="t")


def _recorder(events: list, i: int):
    """A turn factory for the ordering tests: records `("start", i)` on entry and
    `("end", i)` on exit, so the caller can compare the ordered phase lists.

    The phases come from the SAME closure for a given turn, so a turn that started but
    never ended shows up as a missing entry in the `ends` list the tests compare — the
    failure names the index rather than passing on a partial ordering."""
    async def _body():
        events.append(("start", i))
        await asyncio.sleep(0.01)
        events.append(("end", i))
        return i
    return _body


@pytest.mark.asyncio
async def test_same_matter_turns_serialize_in_fifo_order():
    sched = TurnScheduler(_cap(), max_concurrent=4)
    events: list = []
    handles = []
    for i in range(5):
        handles.append(sched.submit("M-1", "chat", _recorder(events, i)))
    await asyncio.gather(*(h.wait() for h in handles))
    # 5 turns on one matter: starts happen strictly in submit order with no interleaving —
    # each end precedes the next start.
    starts = [i for phase, i in events if phase == "start"]
    ends = [i for phase, i in events if phase == "end"]
    assert starts == [0, 1, 2, 3, 4]          # FIFO — a later turn never overtakes
    assert ends == [0, 1, 2, 3, 4]            # and each finishes before the next starts


@pytest.mark.asyncio
async def test_different_matters_run_in_parallel():
    # Two matters, one turn each, that can only complete if BOTH are inside their critical
    # section at the same time. Overlap is REQUIRED by the barrier, not inferred from
    # timing — a serialized run would deadlock on barrier.wait() and time out the test.
    sched = TurnScheduler(_cap(), max_concurrent=2)
    barrier = asyncio.Barrier(2)
    results: list[str] = []

    async def _fn(matter):
        async def _body():
            await barrier.wait()              # both turns must be RUNNING to pass this
            await asyncio.sleep(0.02)         # and both stay running after
            return matter
        return await _body()

    h1 = sched.submit("M-A", "chat", lambda: _fn("A"))
    h2 = sched.submit("M-B", "chat", lambda: _fn("B"))
    r = await asyncio.gather(h1.wait(), h2.wait())
    assert sorted(r) == ["A", "B"]
    assert results == []                      # placeholder removed; barrier is the proof


@pytest.mark.asyncio
async def test_two_matters_do_not_overlap_when_the_cap_is_one():
    # The previous test's overlap is only possible if the cap admits 2. With
    # max_concurrent=1 the same two turns must NOT overlap — proving the global semaphore
    # binds, not just the per-matter locks.
    sched = TurnScheduler(_cap(), max_concurrent=1)
    running: list[str] = []
    overlapped: list = []

    async def _fn(matter):
        running.append(matter)
        if len(running) > 1:
            overlapped.append(tuple(sorted(running)))
        await asyncio.sleep(0.02)
        running.remove(matter)
        return matter

    h1 = sched.submit("M-A", "chat", lambda: _fn("A"))
    h2 = sched.submit("M-B", "chat", lambda: _fn("B"))
    await asyncio.gather(h1.wait(), h2.wait())
    assert overlapped == []                    # serialized: at most one running at a time


def test_cap_is_taken_from_capacity_when_not_overridden():
    c = Capacity(perf_cores=12, avail_mb=54_872, source_cores="t", source_memory="t")
    assert TurnScheduler(c).max_concurrent == 2      # the measured box: memory binds
    c2 = Capacity(perf_cores=4, avail_mb=999_999, source_cores="t", source_memory="t")
    assert TurnScheduler(c2).max_concurrent == 2     # min(2, 48) — cores bind here


def test_env_override_wins_over_the_derived_cap(monkeypatch):
    monkeypatch.setenv("HARNESS_MAX_CONCURRENT", "3")
    c = Capacity(perf_cores=12, avail_mb=54_872, source_cores="t", source_memory="t")
    assert TurnScheduler(c).max_concurrent == 3      # the derivation said 2; the env wins


@pytest.mark.asyncio
async def test_a_backlog_cannot_starve_another_matter():
    # The structural fairness property (spec §3.2 item 3): a matter holds its own lock only
    # while RUNNING, so its queued turns wait on the matter lock, not on the semaphore.
    # Each matter contributes at most ONE turn to the semaphore queue, so matter B cannot
    # be pushed back by A's backlog beyond a single turn. With cap=1, A's five queued
    # turns all wait on A's LOCK; B's single turn waits on the SEMAPHORE behind A's one
    # running turn — so B must run before any of A's backlog.
    sched = TurnScheduler(_cap(), max_concurrent=1)
    ran: list[str] = []

    async def _a():
        await asyncio.sleep(0.02)
        ran.append("A")
        return "A"

    async def _slow():
        await asyncio.sleep(0.005)
        ran.append("queued-A")
        return "A-queued"

    async def _b():
        ran.append("B")
        return "B"

    sched.submit("M-A", "chat", _a)
    backlog = [sched.submit("M-A", "chat", _slow) for _ in range(5)]
    hb = sched.submit("M-B", "chat", _b)
    # The backlog is awaited TOO, not just B: gather(ha, hb) resolves the instant B's
    # future settles, and the test's loop then closes and cancels A's still-pending queued
    # turns — so "queued-A" never lands and the position assertion below cannot even be
    # evaluated. Await everything, then compare positions.
    await asyncio.gather(hb.wait(), *(h.wait() for h in backlog))
    assert "B" in ran and "queued-A" in ran, f"expected both to have run: {ran}"
    assert ran.index("B") < ran.index("queued-A"), \
        f"matter B was starved by A's backlog: {ran}"


@pytest.mark.asyncio
async def test_queue_timeout_fails_the_turn_without_running_it():
    sched = TurnScheduler(_cap(), max_concurrent=1, queue_timeout=0.05)
    called = []

    async def _blocker():
        await asyncio.sleep(0.3)
        return "blocking"

    async def _victim():
        called.append(True)
        return "victim"

    h1 = sched.submit("M-1", "chat", _blocker)
    h2 = sched.submit("M-1", "chat", _victim)     # queued behind the blocker
    assert await h2.wait() is None                # no result — it never ran
    assert h2.status == "failed"
    assert "queue timeout" in h2.error
    assert called == []                            # the gate never saw it
    await asyncio.gather(h1.wait())


@pytest.mark.asyncio
async def test_cancel_a_queued_turn_never_runs_it():
    sched = TurnScheduler(_cap(), max_concurrent=1)
    ran = []

    async def _blocker():
        await asyncio.sleep(0.2)
        return "blocking"

    async def _victim():
        ran.append(True)
        return "victim"

    h1 = sched.submit("M-1", "chat", _blocker)
    h2 = sched.submit("M-1", "chat", _victim)
    assert sched.cancel(h2.turn_id) is True
    assert h2.status == "cancelled"
    await asyncio.gather(h1.wait())
    assert ran == []                            # the gate never saw it
    # The cancelled turn's own future must resolve too. A task cancelled before its
    # first step never runs its body, so the handler inside _run never fires; without
    # cancel() itself resolving the future, awaiting this handle blocks forever.
    assert await h2.wait() is None
    assert h2.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_an_unknown_turn_is_false_not_an_error():
    sched = TurnScheduler(_cap())
    assert sched.cancel("nope") is False        # a dead handle is a normal query, not an error


@pytest.mark.asyncio
async def test_a_running_turn_failure_is_recorded_not_raised():
    sched = TurnScheduler(_cap())

    async def _boom():
        raise RuntimeError("kaboom")

    h = sched.submit("M-1", "chat", _boom)
    await h.wait()
    assert h.status == "failed"
    assert "kaboom" in h.error


@pytest.mark.asyncio
async def test_registry_and_in_flight():
    sched = TurnScheduler(_cap(), max_concurrent=2)
    started: list[str] = []

    async def _fn(tag):
        started.append(tag)
        await asyncio.sleep(0.02)
        return tag

    h1 = sched.submit("M-1", "chat", lambda: _fn("r0"))
    h2 = sched.submit("M-2", "chat", lambda: _fn("r1"))
    assert sched.handle(h1.turn_id) is h1
    assert len(sched.handles()) == 2
    assert sched.in_flight >= 2
    r = await asyncio.gather(h1.wait(), h2.wait())
    assert r == ["r0", "r1"]
    assert h1.status == "done" and h1.result == "r0"
    assert h2.status == "done" and h2.result == "r1"
    assert h1.queue_ms >= 0.0                   # recorded even when it never queued
    assert sched.in_flight == 0
