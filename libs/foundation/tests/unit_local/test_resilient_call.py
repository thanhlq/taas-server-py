"""Tests for `foundation.resiliant.resilient_call.ResilientExecutor`."""

from __future__ import annotations

import asyncio

import pytest
from foundation.resiliant.bulkhead import BulkheadConfig, BulkheadFullError
from foundation.resiliant.circuit_breaker import CircuitBreakerConfig, CircuitOpenError
from foundation.resiliant.resilient_call import ResilientExecutor
from foundation.resiliant.timeout import OperationTimeoutError


async def test_success_passes_through() -> None:
    executor = ResilientExecutor('svc', timeout_seconds=1.0)

    async def ok() -> int:
        return 42

    assert await executor.call(ok) == 42


async def test_timeout_raises() -> None:
    executor = ResilientExecutor('svc', timeout_seconds=0.02)

    async def slow() -> None:
        await asyncio.sleep(1.0)

    with pytest.raises(OperationTimeoutError):
        await executor.call(slow)


async def test_circuit_breaker_opens_then_fast_fails() -> None:
    executor = ResilientExecutor(
        'svc',
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=2, recovery_timeout_seconds=60.0
        ),
    )

    async def boom() -> None:
        raise ValueError('down')

    # Two real failures trip the breaker...
    for _ in range(2):
        with pytest.raises(ValueError):
            await executor.call(boom)

    # ...then it fails fast without calling the handler.
    with pytest.raises(CircuitOpenError):
        await executor.call(boom)


async def test_fallback_is_used_on_failure() -> None:
    executor = ResilientExecutor('svc')

    async def boom() -> str:
        raise RuntimeError('nope')

    async def fb(exc: BaseException) -> str:
        return f'fallback:{type(exc).__name__}'

    assert await executor.call(boom, fallback=fb) == 'fallback:RuntimeError'


async def test_timeout_failure_trips_the_breaker() -> None:
    # timeout is innermost, so an expiry surfaces as a breaker failure.
    executor = ResilientExecutor(
        'svc',
        timeout_seconds=0.02,
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=1, recovery_timeout_seconds=60.0
        ),
    )

    async def slow() -> None:
        await asyncio.sleep(1.0)

    with pytest.raises(OperationTimeoutError):
        await executor.call(slow)

    # Breaker is now OPEN -> fast fail.
    with pytest.raises(CircuitOpenError):
        await executor.call(slow)


async def test_bulkhead_limits_concurrency() -> None:
    executor = ResilientExecutor(
        'svc',
        bulkhead=BulkheadConfig(max_concurrent=1, acquire_timeout_seconds=0.05),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold() -> None:
        started.set()
        await release.wait()

    task = asyncio.create_task(executor.call(hold))
    await started.wait()  # first call occupies the only slot

    async def quick() -> None:
        return None

    with pytest.raises(BulkheadFullError):
        await executor.call(quick)

    release.set()
    await task
