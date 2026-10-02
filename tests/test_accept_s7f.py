# tests/test_accept_s7f.py — the PURE parts of the S7f acceptance driver.
# main() drives real Ollama + the real opencode binary and is NEVER run in the suite.
import asyncio
import pytest
from harness.capacity import Capacity
from harness.scheduler import TurnScheduler


def _sched(max_concurrent=2, **kw):
    return TurnScheduler(Capacity(perf_cores=99, avail_mb=999_999, source_cores="t",
                                  source_memory="t"), max_concurrent=max_concurrent, **kw)


def test_check_c1_passes_on_a_derived_capacity():
    # A derived capacity with non-fallback sources and a formula-consistent cap passes.
    from scripts.accept_s7f import check_c1
    c = Capacity(perf_cores=12, avail_mb=54_872, source_cores="real probe",
                 source_memory="real probe")
    assert check_c1(c) == []


def test_check_c1_rejects_a_fallback_source():
    # The audit trail: a fallback result is legal but must be LABELLED. An unlabelled
    # fallback would silently ship a cap nobody derived.
    from scripts.accept_s7f import check_c1
    c = Capacity(perf_cores=8, avail_mb=0, source_cores="os.cpu_count", source_memory="")
    problems = check_c1(c)
    assert problems and any("source" in p for p in problems)


def test_check_c1_rejects_an_inconsistent_cap():
    # The cap must equal the formula recomputed from the same fields — a hand-set
    # max_concurrent that disagrees with the capacity it was built from is a wiring bug.
    from scripts.accept_s7f import check_c1
    c = Capacity(perf_cores=12, avail_mb=54_872, source_cores="t", source_memory="t")
    c.CORES_PER_TURN = 99                        # forces cores=1 while memory says 2
    problems = check_c1(c)
    assert problems


@pytest.mark.asyncio
async def test_check_c2_same_matter_fifo():
    from scripts.accept_s7f import check_c2
    assert await check_c2(_sched(max_concurrent=4)) == []


@pytest.mark.asyncio
async def test_check_c3_different_matters_parallel():
    from scripts.accept_s7f import check_c3
    assert await check_c3(_sched(max_concurrent=2)) == []


@pytest.mark.asyncio
async def test_check_c4_cap_binds_globally():
    from scripts.accept_s7f import check_c4
    assert await check_c4(_sched(max_concurrent=1)) == []


@pytest.mark.asyncio
async def test_check_c5_fairness_and_cancellation():
    from scripts.accept_s7f import check_c5
    assert await check_c5(_sched(max_concurrent=1, queue_timeout=0.2)) == []
