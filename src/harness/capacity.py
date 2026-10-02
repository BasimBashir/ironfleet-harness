# src/harness/capacity.py
"""A-5: machine capacity for the scheduler's concurrency cap (spec §2).

Two numbers decide how many turns may run at once: performance-class logical CPUs and
available RAM. Each carries a `source_*` string recording how it was obtained — the same
discipline as CR-3 provenance, because a capacity number without provenance is a claim an
operator cannot audit. No psutil: stdlib reaches these on every target platform, and a new
dependency for a handful of calls is not warranted.

The cap is conservative on purpose. The reserve is the served model's measured weight
footprint (20,398 MB for thomson1-chat 34.7B Q4_K_M, rounded up to a whole GiB), so an
admitted turn can always COLD-LOAD its model into free RAM rather than gambling that the
server still holds it resident. On the measured box this makes memory the binding term
(min(6, 2) = 2): two matters run concurrently, a third queues, and neither of the two is
betting on residency.
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
from pathlib import Path
from pydantic import BaseModel

# Charging rules (spec §2). CORES_PER_TURN is an admission policy, not a measurement: a
# turn per two performance-class logical CPUs keeps an admitted turn from starving the OS
# and lets a second matter's turn still make progress. RESERVE_MB is the served model's
# /api/tags size rounded up to a whole GiB.


class Capacity(BaseModel):
    perf_cores: int            # performance-class logical CPUs (E-cores excluded where derivable)
    avail_mb: int              # 0 = not derivable — the memory term is then dropped, not guessed
    source_cores: str          # how perf_cores was obtained — recorded, never assumed
    source_memory: str         # how avail_mb was obtained

    CORES_PER_TURN: int = 2
    RESERVE_MB: int = 20_480   # 20,398 MB measured, rounded up to a whole GiB

    @property
    def max_concurrent(self) -> int:
        cores = max(1, self.perf_cores // self.CORES_PER_TURN)
        if self.avail_mb:
            memory = max(1, self.avail_mb // self.RESERVE_MB)
            return max(1, min(cores, memory))
        return cores


def _windows_capacity() -> Capacity:
    # GetLogicalProcessorInformationEx(RelationProcessorCore): one entry per physical
    # package carrying an EfficiencyClass (0 = performance, 1 = efficiency, Win10 1709+).
    # Layout gotcha, observed while writing this: PROCESSOR_RELATIONSHIP has a 20-byte
    # Reserved on Windows 10, so EfficiencyClass is at struct offset 9 and GroupCount at
    # offset 30. A 6-byte read of Reserved returns garbage and silently miscounts P-cores.
    # Verified live 2026-10-02 on the dev box: 6 packages, all EfficiencyClass=0, 2 logical
    # each = 12 performance-class logical CPUs, no E-cores.
    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    buf = (ctypes.c_char * 8192)()
    size = ctypes.c_ulong(8192)
    perf = e = 0
    ok = k32.GetLogicalProcessorInformationEx(0, buf, ctypes.byref(size))
    if ok:
        off = 0
        while off + 32 <= size.value:
            groupcount = int.from_bytes(buf[off + 30:off + 32], "little")
            logical = 0
            for g in range(groupcount):
                base = off + 32 + g * 16          # each GROUP_AFFINITY is 16 bytes
                logical += bin(int.from_bytes(buf[base:base + 8], "little")).count("1")
            # EfficiencyClass 0 = performance. NOTE the comparison: buf is a c_char array,
            # so buf[i] is a BYTES object (b"\x00") — `buf[off+9] == 0` is always False on
            # Python 3 and every core silently lands in the efficiency branch, yielding
            # perf=0 and a fallback cap. Compare the decoded byte instead. Verified live
            # 2026-10-02: with this read the box reports 6 packages, all EfficiencyClass=0,
            # 2 logical each = 12 performance-class logical CPUs, no E-cores.
            if int.from_bytes(buf[off + 9:off + 10], "little") == 0:
                perf += logical
            else:
                e += logical
            off += 32 + groupcount * 16
    if not perf:
        return Capacity(perf_cores=os.cpu_count() or 1, avail_mb=0, source_cores=
                        "fallback: os.cpu_count (GetLogicalProcessorInformationEx failed)",
                        source_memory="fallback: unknown")

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(m)
    if not k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return Capacity(perf_cores=perf, avail_mb=0,
                        source_cores="GetLogicalProcessorInformationEx (performance class)",
                        source_memory="fallback: GlobalMemoryStatusEx failed")
    return Capacity(perf_cores=perf, avail_mb=int(m.ullAvailPhys // 1024 // 1024),
                    source_cores="GetLogicalProcessorInformationEx (performance class)",
                    source_memory="GlobalMemoryStatusEx dwAvailPhys")


def _run(argv: list[str]) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _macos_capacity() -> Capacity:
    # macOS is the one platform that splits performance levels natively:
    # hw.perflevel0.* = P-cores, hw.perflevel1.* = E-cores.
    perf_s = _run(["sysctl", "-n", "hw.perflevel0.logicalcpu"])
    total_s = _run(["sysctl", "-n", "hw.logicalcpu"])
    avail_s = _run(["sysctl", "-n", "hw.memsize"])
    perf = int(perf_s or total_s or 0) or (os.cpu_count() or 1)
    src = ("sysctl hw.perflevel0.logicalcpu" if perf_s else
           ("fallback: hw.logicalcpu (no perflevel split)" if total_s else
            "fallback: os.cpu_count"))
    # vm_stat gives the free+inactive page count; sysctl hw.memsize is total only.
    vm = _run(["vm_stat"])
    avail = 0
    if vm:
        for line in vm.splitlines():
            if "free" in line.lower() or "inactive" in line.lower():
                digits = "".join(ch for ch in line.split(":")[-1] if ch.isdigit())
                if digits:
                    avail += int(digits)          # pages; macOS pages are 16_384 bytes on arm64
    if avail:
        avail = avail * 16_384 // 1024 // 1024
        src_mem = "vm_stat free+inactive pages"
    elif avail_s:
        avail = int(int(avail_s) // 1024 // 1024)
        src_mem = "fallback: hw.memsize total (vm_stat unavailable)"
    else:
        src_mem = "fallback: unknown"
    return Capacity(perf_cores=perf, avail_mb=avail, source_cores=src, source_memory=src_mem)


def _linux_capacity() -> Capacity:
    # /proc/cpuinfo "processor" lines = logical CPUs. Linux has no reliable stdlib P/E
    # split, so the source string says so rather than implying a P-core count was obtained.
    try:
        logical = sum(1 for line in Path("/proc/cpuinfo").read_text().splitlines()
                      if line.startswith("processor"))
    except OSError:
        logical = 0
    perf = logical or (os.cpu_count() or 1)
    src = "/proc/cpuinfo processor count" if logical else "fallback: os.cpu_count"
    avail = 0
    src_mem = "fallback: unknown"
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                kb = "".join(ch for ch in line.split(":")[1] if ch.isdigit())
                if kb:
                    avail = int(kb) // 1024
                    src_mem = "/proc/meminfo MemAvailable"
                break
    except OSError:
        pass
    return Capacity(perf_cores=perf, avail_mb=avail, source_cores=src, source_memory=src_mem)


def machine_capacity() -> Capacity:
    """The real machine's capacity, with the source of every number recorded. Never raises:
    a capacity-detection failure must not kill dispatch — the caller gets a labelled
    fallback and the cap degrades to the cores term (or to 1), never to a crash."""
    try:
        if platform.system() == "Windows":
            return _windows_capacity()
        if platform.system() == "Darwin":
            return _macos_capacity()
        return _linux_capacity()
    except Exception:                              # noqa: BLE001 — the whole point is fallback
        return Capacity(perf_cores=os.cpu_count() or 1, avail_mb=0,
                        source_cores="fallback: os.cpu_count (detection raised)",
                        source_memory="fallback: unknown")
