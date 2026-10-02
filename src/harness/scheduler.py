# src/harness/scheduler.py
"""A-5: the turn scheduler (spec §3).

Two locks, one fixed acquire order:

    matter_lock[matter_ref]  ->  global_semaphore(max_concurrent)  ->  run fn()

That single ordering gives three provable properties:

  1. same matter serializes, FIFO — the per-matter lock admits one turn at a time and
     wakes waiters in submission order;
  2. different matters run parallel — per-matter locks are independent, so a matter B turn
     never waits on matter A's lock;
  3. no matter can monopolize the cap — a matter holds its own lock only while RUNNING, so
     its queued turns wait on the MATTER lock, not the semaphore. Each matter contributes
     at most one turn to the semaphore queue, so a backlog can only ever be one turn ahead
     of another waiting matter. This is structural, not configured (spec §3.2).

Release order is the reverse of acquire (inner first): the semaphore is released BEFORE the
matter lock, which hands the freed slot to a waiting OTHER matter before this matter's next
turn can re-queue for it. Deadlock is impossible: locks are per-matter, the semaphore is
global, and every turn acquires in the same order.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable, Generic, TypeVar

from pydantic import BaseModel, PrivateAttr

from harness.capacity import Capacity

T = TypeVar("T")


class TurnHandle(BaseModel, Generic[T]):
    turn_id: str
    matter_ref: str
    kind: str                      # "chat" on the proxy path; a forward-looking label
    status: str = "queued"         # queued | running | done | failed | cancelled
    queue_ms: float = 0.0
    started_at: str = ""
    result: T | None = None
    error: str = ""

    # The completion future lives on the SCHEDULER, not the model: pydantic 2 fields are
    # validated and copied, so an asyncio.Future stashed on the instance would not survive
    # model_validate/copy round-trips. `_sched` is a private attr (excluded from validation
    # and serialization) holding the back-reference the future is looked up through.
    _sched: "TurnScheduler | None" = PrivateAttr(default=None)

    async def wait(self) -> T | None:
        """Await the turn's outcome. Returns the result, or None if it failed/was
        cancelled — the handle's `status` and `error` carry the reason. Awaiting a handle
        that never ran (cancelled while queued) returns None immediately."""
        if self._sched is None:
            return None
        fut = self._sched._futures.get(self.turn_id)
        if fut is None:
            return None
        return await fut


class _MatterQueue:
    """One matter's FIFO. Holds the lock plus the turn waiting for it, so a cancelled
    queued turn can be pulled from the deque before it ever acquires anything."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.waiting: deque[TurnHandle] = deque()


class TurnScheduler:
    def __init__(self, capacity: Capacity, *, max_concurrent: int | None = None,
                 queue_timeout: float = 600.0,
                 run_timeout: float | None = None) -> None:
        self.capacity = capacity
        # An explicit override always wins over the derivation, and the capacity's source
        # records that it applied — a forced cap must be visible in the acceptance output,
        # not indistinguishable from a derived one.
        env = os.environ.get("HARNESS_MAX_CONCURRENT")
        self.max_concurrent = int(max_concurrent or env or 0) or capacity.max_concurrent
        self.queue_timeout = queue_timeout
        self.run_timeout = run_timeout
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._matters: dict[str, _MatterQueue] = {}
        self._handles: dict[str, TurnHandle] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._futures: dict[str, "asyncio.Future[T | None]"] = {}

    def _matter(self, matter_ref: str) -> _MatterQueue:
        return self._matters.setdefault(matter_ref, _MatterQueue())

    @property
    def in_flight(self) -> int:
        return sum(1 for h in self._handles.values()
                   if h.status in ("queued", "running"))

    def submit(self, matter_ref: str, kind: str, fn: Callable[[], Awaitable[T]]) -> TurnHandle[T]:
        handle: TurnHandle[T] = TurnHandle(turn_id=str(uuid.uuid4()), matter_ref=matter_ref,
                                           kind=kind)
        handle._sched = self                     # the back-reference wait() looks the future up with
        self._handles[handle.turn_id] = handle
        # The future is created HERE, before the task starts, so wait() on a just-submitted
        # handle always finds one — the turn's outcome is settled on this loop either way.
        # get_running_loop, not get_event_loop: on Python 3.14 the latter RAISES
        # RuntimeError ("no current event loop") when called with no running loop, and
        # submit() is only ever called from inside one (a test coroutine, or the proxy's
        # background loop) — so the strict form fails loudly on a wiring error instead of
        # binding the future to the wrong loop.
        self._futures[handle.turn_id] = asyncio.get_running_loop().create_future()
        mq = self._matter(matter_ref)
        mq.waiting.append(handle)
        task = asyncio.ensure_future(self._run(handle, mq, fn))
        self._tasks[handle.turn_id] = task
        return handle

    async def _run(self, handle: TurnHandle, mq: _MatterQueue,
                   fn: Callable[[], Awaitable[T]]) -> None:
        fut = self._futures[handle.turn_id]
        # owned, not mq.lock.locked(): a turn CANCELLED while queued for the lock never
        # acquired it, but mq.lock.locked() is still True — the RUNNING turn of the same
        # matter holds it. Releasing on the bare predicate would free another turn's lock
        # mid-run and break the serialization this whole module exists to provide.
        owned = False
        try:
            t0 = time.monotonic()
            try:
                # The queue covers BOTH gates: the matter lock AND the global cap. A turn
                # blocked only by the cap (a different matter, no local contention) is
                # still queued, and queue_ms must say so — C6's queued turn is exactly that
                # case. Measuring after the lock alone reports ~0 for it, which makes the
                # queue wait invisible over the wire (observed against the running proxy:
                # 835ms of wall-clock wait, 0.036ms of reported queue_ms).
                # The deadline bounds ONLY the two acquisitions; fn() runs outside it under
                # run_timeout, so a slow turn can never be misreported as a queue timeout.
                async with asyncio.timeout(self.queue_timeout):
                    await mq.lock.acquire()
                    owned = True
                    await self._semaphore.acquire()
            except (asyncio.TimeoutError, TimeoutError):
                handle.status = "failed"
                handle.error = f"queue timeout after {self.queue_timeout}s"
                fut.set_result(None)
                return
            except asyncio.CancelledError:
                # cancelled while waiting for either gate: it never ran, and never will.
                # The future must be resolved here or a caller awaiting wait() blocks
                # forever — cancel() itself only sets the status and cancels the task.
                # The guard matters for the running case below, not this one: a turn
                # cancelled at a gate never started its body, so cancel() has not
                # resolved anything yet. Checked anyway — one rule for both handlers.
                if handle.status != "cancelled":
                    handle.status = "cancelled"
                if not fut.done():
                    fut.set_result(None)
                raise
            try:
                handle.queue_ms = (time.monotonic() - t0) * 1000.0
                # Popped here, while holding both gates: cancel() of a queued turn finds
                # it in the deque and removes it before it reaches this point.
                if handle in mq.waiting:
                    mq.waiting.remove(handle)
                if handle.status == "cancelled":        # cancelled between the two gates
                    fut.set_result(None)
                    return
                handle.status = "running"
                handle.started_at = datetime.now(timezone.utc).isoformat()
                if self.run_timeout is not None:
                    result = await asyncio.wait_for(fn(), self.run_timeout)
                else:
                    result = await fn()
                handle.result = result
                handle.status = "done"
                fut.set_result(result)
            except asyncio.CancelledError:
                handle.status = "cancelled"
                # cancel() already resolved this future synchronously when it cancelled a
                # RUNNING turn — a second set_result here would raise InvalidStateError out
                # of the task and it would die erroring instead of cancelled. Whether the
                # turn had started is a race cancel() cannot settle, so the check lives
                # here, on the side that knows whether the future is still pending.
                if not fut.done():
                    fut.set_result(None)
                raise
            except Exception as ex:                 # noqa: BLE001 — record, don't raise
                handle.status = "failed"
                handle.error = str(ex)
                fut.set_result(None)
            # The semaphore is released HERE, before the matter lock below: a waiting OTHER
            # matter gets the slot before this matter's next turn can re-queue for it.
            finally:
                self._semaphore.release()
        finally:
            if owned:
                mq.lock.release()
            self._tasks.pop(handle.turn_id, None)

    def cancel(self, turn_id: str) -> bool:
        handle = self._handles.get(turn_id)
        if handle is None or handle.status in ("done", "failed", "cancelled"):
            return False
        handle.status = "cancelled"
        mq = self._matters.get(handle.matter_ref)
        if mq is not None and handle in mq.waiting:
            mq.waiting.remove(handle)          # queued: it will never acquire the lock
        task = self._tasks.get(turn_id)
        if task is not None and not task.done():
            task.cancel()                       # running: the fn's await observes it
            # A task cancelled BEFORE its first step never runs its body at all — asyncio
            # throws the CancelledError into a coroutine that has not started, so _run's
            # own handler never fires and the future would stay pending forever. Anyone
            # awaiting TurnHandle.wait() would then block for the life of the process.
            # Resolve it here: cancel() is synchronous, and by the time it returns the
            # caller is entitled to regard the turn as finished.
            fut = self._futures.get(turn_id)
            if fut is not None and not fut.done():
                fut.set_result(None)
        return True

    def handle(self, turn_id: str) -> "TurnHandle | None":
        return self._handles.get(turn_id)

    def handles(self) -> list["TurnHandle"]:
        return list(self._handles.values())
