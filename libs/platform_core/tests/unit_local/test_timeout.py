"""Tests for `platform_core.resilience.timeout`."""

from __future__ import annotations

import asyncio

import pytest

from platform_core.resilience.timeout import (
    OperationTimeoutError,
    TimeoutConfig,
    TimeoutFactory,
    TimeoutService,
)


async def test_returns_when_handler_finishes_in_time() -> None:
    service = TimeoutService(TimeoutConfig(seconds=1.0))

    async def quick() -> str:
        await asyncio.sleep(0.01)
        return "v"

    assert await service.execute(quick) == "v"


async def test_raises_on_deadline() -> None:
    service = TimeoutService(TimeoutConfig(seconds=0.05))

    async def slow() -> None:
        await asyncio.sleep(1.0)

    with pytest.raises(OperationTimeoutError):
        await service.execute(slow)


async def test_per_call_override() -> None:
    service = TimeoutService(TimeoutConfig(seconds=10.0))

    async def slow() -> None:
        await asyncio.sleep(0.2)

    with pytest.raises(OperationTimeoutError):
        await service.execute(slow, seconds=0.05)


async def test_factory_builds_service() -> None:
    assert isinstance(TimeoutFactory().create_service(), TimeoutService)
