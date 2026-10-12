# tests/test_capacity.py — A-5 machine capacity detection (spec §2)
import pytest
from harness.capacity import Capacity

def test_cores_term_binds_when_memory_is_generous():
    c = Capacity(perf_cores=12, avail_mb=200_000, source_cores="x", source_memory="y")
    # min(12//2, 200000//20480) = min(6, 9) = 6 — the cores term decides
    assert c.max_concurrent == 6

def test_memory_term_binds_on_this_class_of_machine():
    # A class-of-machine input (S7f's live boxes read 53.3–53.5 GB available, so memory
    # binds the same way): 12 perf cores, ~54.9 GB available, 20 GiB reserve.
    # min(6, 2) = 2 — memory binds, which is the whole reason the reserve exists.
    c = Capacity(perf_cores=12, avail_mb=54_872, source_cores="x", source_memory="y")
    assert c.max_concurrent == 2

def test_unknown_memory_degrades_to_the_cores_term_not_to_one():
    # avail_mb=0 means "not derivable", not "no memory": drop the memory term and say why.
    c = Capacity(perf_cores=8, avail_mb=0, source_cores="x", source_memory="fallback: unknown")
    assert c.max_concurrent == 4

def test_cap_floors_at_one_on_a_tiny_machine():
    c = Capacity(perf_cores=1, avail_mb=1024, source_cores="x", source_memory="y")
    assert c.max_concurrent == 1
    c2 = Capacity(perf_cores=0, avail_mb=0, source_cores="fallback", source_memory="fallback")
    assert c2.max_concurrent == 1   # never 0 — a scheduler sized 0 admits nothing forever

def test_machine_capacity_returns_real_numbers_with_a_source():
    # The real probe must record HOW each number was obtained, not just that it got one.
    import platform
    from harness import capacity as cap
    c = cap.machine_capacity()
    assert c.perf_cores >= 1
    assert c.source_cores                       # never empty
    assert c.source_memory                      # never empty
    assert c.max_concurrent >= 1
    if "fallback" not in c.source_memory:
        assert c.avail_mb > 0                   # a claimed real read must be a number
    if platform.system() == "Windows":
        # The ctypes path is the one that can silently misread the struct — this asserts
        # it read a real performance-class count instead of falling back. perf_cores < 2
        # here would mean the EfficiencyClass byte comparison broke again (see the note
        # in _windows_capacity: `buf[off+9] == 0` is always False for a c_char array).
        assert "GetLogicalProcessorInformationEx" in c.source_cores
        assert c.perf_cores >= 2
