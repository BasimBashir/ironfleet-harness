# tests/test_retry.py — retry below the gate (spec §§2.2, 6). The user's cloud endpoint
# intermittently returns {"error": "upstream failure"} on a 200 and is rate-limited per minute.
import asyncio
import pytest
from harness.gate import Transport
from harness.providers.config import ProviderConfig
from harness.providers.retry import RetryExhausted, retrying

CFG = ProviderConfig(name="p", base_url="http://p/v1", model="m", engine="cloud")


def _cfg(**kw):
    return ProviderConfig(name="p", base_url="http://p/v1", model="m", engine="cloud", **kw)


@pytest.mark.asyncio
async def test_none_result_is_retried_then_succeeds():
    calls = []

    async def inner(provider, payload):
        calls.append(payload)
        return None if len(calls) < 3 else {"choices": [{"message": {"content": "ok"}}]}

    out = await retrying(inner, attempts=5, base_delay_s=0.0)(CFG, {"model": "m"})
    assert out["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_error_body_on_a_200_is_retried():
    # the observed Atria shape: HTTP 200 carrying an error payload — http_fetch returns it as a dict
    calls = []

    async def inner(provider, payload):
        calls.append(1)
        return ({"error": {"message": "upstream failure", "type": "bad_gateway_error"}}
                if len(calls) < 2 else {"choices": [{"message": {"content": "ok"}}]})

    out = await retrying(inner, attempts=3, base_delay_s=0.0)(CFG, {})
    assert out["choices"][0]["message"]["content"] == "ok" and len(calls) == 2


@pytest.mark.asyncio
async def test_a_raised_exception_is_retried():
    calls = []

    async def inner(provider, payload):
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("connect timeout")
        return {"choices": [{"message": {"content": "ok"}}]}

    out = await retrying(inner, attempts=3, base_delay_s=0.0)(CFG, {})
    assert len(calls) == 2 and out["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_being_retried():
    # CancelledError is a BaseException, not an Exception: a caller's timeout or the user's Ctrl-C
    # must survive the wrapper, not be classified as retryable and spend the whole budget.
    calls = []

    async def inner(provider, payload):
        calls.append(1)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await retrying(inner, attempts=3, base_delay_s=0.0)(CFG, {})
    assert len(calls) == 1          # raised on the first call, never retried


@pytest.mark.asyncio
async def test_permanent_failure_exhausts_attempts_and_raises():
    calls = []

    async def inner(provider, payload):
        calls.append(1)
        return {"error": {"message": "upstream failure"}}

    with pytest.raises(RetryExhausted, match="upstream failure"):
        await retrying(inner, attempts=4, base_delay_s=0.0)(CFG, {})
    assert len(calls) == 4          # exactly the ceiling, no more


@pytest.mark.asyncio
async def test_success_on_the_first_try_does_not_retry():
    calls = []

    async def inner(provider, payload):
        calls.append(1)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    await retrying(inner, attempts=3, base_delay_s=0.0)(CFG, {})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_pacing_enforces_the_minimum_interval_between_calls():
    import time
    calls = []

    async def inner(provider, payload):
        calls.append(time.monotonic())
        return {"choices": [{"message": {"content": "ok"}}]}

    t = retrying(inner, attempts=2, base_delay_s=0.0, min_interval_s=0.05)
    await t(CFG, {})
    await t(CFG, {})
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.045        # the second call waited for the pacing interval
