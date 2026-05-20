"""Tests for `platform_core.resilience.retry`."""

from __future__ import annotations

import random

import pytest

from platform_core.resilience.retry import (
    BackoffStrategy,
    RetryConfig,
    RetryExhaustedError,
    RetryFactory,
    RetryService,
)


class RecordingSleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


async def test_returns_on_first_success() -> None:
    sleeper = RecordingSleeper()
    service = RetryService(RetryConfig(max_attempts=3), sleep=sleeper)

    async def ok() -> str:
        return "v"

    assert await service.execute(ok) == "v"
    assert sleeper.calls == []


async def test_retries_until_success() -> None:
    sleeper = RecordingSleeper()
    service = RetryService(
        RetryConfig(
            max_attempts=5,
            initial_delay_seconds=0.1,
            strategy=BackoffStrategy.EXPONENTIAL,
            multiplier=2.0,
        ),
        sleep=sleeper,
    )

    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("nope")
        return "ok"

    assert await service.execute(flaky) == "ok"
    assert attempts == 3
    # 2 sleeps between 3 attempts: 0.1, 0.2
    assert sleeper.calls == pytest.approx([0.1, 0.2])


async def test_exhausts_and_raises() -> None:
    service = RetryService(
        RetryConfig(max_attempts=2, initial_delay_seconds=0.0),
        sleep=RecordingSleeper(),
    )

    async def boom() -> None:
        raise RuntimeError("x")

    with pytest.raises(RetryExhaustedError) as exc_info:
        await service.execute(boom)
    assert exc_info.value.attempts == 2
    assert isinstance(exc_info.value.last_error, RuntimeError)


async def test_only_retries_on_configured_exceptions() -> None:
    service = RetryService(
        RetryConfig(max_attempts=5, retry_on=(ValueError,)),
        sleep=RecordingSleeper(),
    )

    async def boom() -> None:
        raise RuntimeError("not retried")

    with pytest.raises(RuntimeError):
        await service.execute(boom)


async def test_linear_and_constant_strategies() -> None:
    sleeper = RecordingSleeper()
    service = RetryService(
        RetryConfig(
            max_attempts=4,
            initial_delay_seconds=0.5,
            strategy=BackoffStrategy.LINEAR,
        ),
        sleep=sleeper,
    )

    async def boom() -> None:
        raise RuntimeError("x")

    with pytest.raises(RetryExhaustedError):
        await service.execute(boom)
    assert sleeper.calls == pytest.approx([0.5, 1.0, 1.5])

    sleeper2 = RecordingSleeper()
    service2 = RetryService(
        RetryConfig(
            max_attempts=3,
            initial_delay_seconds=0.25,
            strategy=BackoffStrategy.CONSTANT,
        ),
        sleep=sleeper2,
    )
    with pytest.raises(RetryExhaustedError):
        await service2.execute(boom)
    assert sleeper2.calls == pytest.approx([0.25, 0.25])


async def test_max_delay_caps_backoff() -> None:
    sleeper = RecordingSleeper()
    service = RetryService(
        RetryConfig(
            max_attempts=4,
            initial_delay_seconds=10.0,
            max_delay_seconds=15.0,
            strategy=BackoffStrategy.EXPONENTIAL,
            multiplier=10.0,
        ),
        sleep=sleeper,
    )

    async def boom() -> None:
        raise RuntimeError("x")

    with pytest.raises(RetryExhaustedError):
        await service.execute(boom)
    assert all(d <= 15.0 for d in sleeper.calls)


async def test_jitter_stays_within_bounds() -> None:
    sleeper = RecordingSleeper()
    service = RetryService(
        RetryConfig(
            max_attempts=5,
            initial_delay_seconds=1.0,
            jitter=0.5,
            strategy=BackoffStrategy.CONSTANT,
        ),
        sleep=sleeper,
        rng=random.Random(0),
    )

    async def boom() -> None:
        raise RuntimeError("x")

    with pytest.raises(RetryExhaustedError):
        await service.execute(boom)
    for d in sleeper.calls:
        assert 0.5 <= d <= 1.5


async def test_factory_builds_service() -> None:
    assert isinstance(RetryFactory().create_service(), RetryService)
