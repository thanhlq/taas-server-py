"""Tests for `platform_core.resilience.circuit_breaker`."""

from __future__ import annotations

import pytest

from platform_core.resilience.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerFactory,
    CircuitBreakerService,
    CircuitOpenError,
    CircuitState,
)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_breaker(clock: FakeClock, **overrides) -> CircuitBreakerService:
    cfg = CircuitBreakerConfig(
        failure_threshold=2,
        recovery_timeout_seconds=10.0,
        half_open_max_calls=1,
        success_threshold=1,
        **overrides,
    )
    return CircuitBreakerService("test", cfg, clock=clock)


async def test_closed_passes_through_results() -> None:
    breaker = make_breaker(FakeClock())

    async def ok() -> str:
        return "v"

    assert await breaker.call(ok) == "v"


async def test_failures_open_the_circuit() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)

    async def boom() -> None:
        raise RuntimeError("x")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(boom)

    snap = await breaker.snapshot()
    assert snap.state is CircuitState.OPEN

    async def ok() -> str:
        return "v"

    with pytest.raises(CircuitOpenError):
        await breaker.call(ok)


async def test_open_recovers_through_half_open() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)

    async def boom() -> None:
        raise RuntimeError("x")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(boom)

    clock.advance(11.0)  # past recovery window

    async def ok() -> str:
        return "v"

    assert await breaker.call(ok) == "v"
    snap = await breaker.snapshot()
    assert snap.state is CircuitState.CLOSED


async def test_half_open_failure_reopens() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)

    async def boom() -> None:
        raise RuntimeError("x")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(boom)
    clock.advance(11.0)

    with pytest.raises(RuntimeError):
        await breaker.call(boom)  # probe fails

    snap = await breaker.snapshot()
    assert snap.state is CircuitState.OPEN


async def test_success_resets_failure_count() -> None:
    breaker = make_breaker(FakeClock())

    async def boom() -> None:
        raise RuntimeError("x")

    async def ok() -> str:
        return "v"

    with pytest.raises(RuntimeError):
        await breaker.call(boom)
    await breaker.call(ok)

    snap = await breaker.snapshot()
    assert snap.failure_count == 0
    assert snap.state is CircuitState.CLOSED


async def test_factory_caches_by_name() -> None:
    factory = CircuitBreakerFactory(CircuitBreakerConfig())
    a = factory.create("svc-a")
    b = factory.create("svc-a")
    c = factory.create("svc-b")
    assert a is b
    assert a is not c
