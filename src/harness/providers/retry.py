# src/harness/providers/retry.py — a retrying transport wrapper (spec §§2.2, 6).
#
# Why the retry sits BELOW the gate: the gate's dispatch() catches a transport exception, writes a
# traced error row and moves to the NEXT candidate — and an A/B leg has exactly one candidate. So a
# retry above the gate would turn a transient blip into a failed case, and a retry inside the gate
# would mean editing proven code. Wrapping the transport means the gate sees only the final success
# or the final failure, and one trace row describes what actually reached the provider.
#
# Retryable shapes: `None` from the fetch (http_fetch swallows status >= 400 and returns None), a
# JSON body carrying an "error" key on a 200 (the observed Atria upstream_failure), and any raised
# exception (timeouts, connection resets). LIMITATION, said out loud: because http_fetch discards
# the status code, a permanent 4xx is indistinguishable from a transient 5xx here, so it is retried
# up to the attempt ceiling and then reported as exhausted rather than classified. Teaching
# http_fetch to surface status codes is a priced future improvement (spec §10), out of scope.
from __future__ import annotations
import asyncio
import random
import time
from typing import Awaitable, Callable

from harness.gate import Transport
from harness.providers.config import ProviderConfig


class RetryExhausted(RuntimeError):
    pass


class _Pacer:
    """Enforces a minimum interval between the STARTS of consecutive calls, so a leg stays under
    a per-minute rate limit. The pacing wait lands inside the gate's latency_ms — that wait is a
    real cost of using the model, so it belongs in the measurement."""
    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._last = 0.0

    async def wait(self) -> None:
        if self.min_interval_s <= 0:
            return
        now = time.monotonic()
        delta = self.min_interval_s - (now - self._last)
        if delta > 0:
            await asyncio.sleep(delta)
        self._last = time.monotonic()


def _is_retryable(result: object, exc: BaseException | None) -> bool:
    if exc is not None:
        return True
    if result is None:
        return True
    # a 200 carrying an error payload (the observed upstream_failure shape)
    return isinstance(result, dict) and "error" in result


def retrying(inner: Transport, *, attempts: int = 3, base_delay_s: float = 2.0,
             min_interval_s: float = 0.0) -> Transport:
    """Wrap a transport with bounded retry, exponential backoff + jitter, and per-call pacing."""
    pacer = _Pacer(min_interval_s)

    async def _call(provider: ProviderConfig, payload: dict) -> dict:
        last_exc: BaseException | None = None
        last_result: object = None
        for attempt in range(1, attempts + 1):
            await pacer.wait()
            try:
                result = await inner(provider, payload)
                exc = None
            except Exception as ex:         # narrow on purpose: CancelledError/KeyboardInterrupt
                result, exc = None, ex     # must propagate, not be classified as retryable
            if not _is_retryable(result, exc):
                assert isinstance(result, dict)
                return result
            last_result, last_exc = result, exc
            if attempt < attempts:
                # exponential backoff with jitter, capped at 60s
                delay = min(base_delay_s * (2 ** (attempt - 1)) + random.random(), 60.0)
                await asyncio.sleep(delay)
        detail = f"last error: {last_exc!r}" if last_exc is not None else f"last result: {last_result!r}"
        raise RetryExhausted(
            f"provider {provider.name} failed after {attempts} attempt(s) — {detail}")
    return _call
