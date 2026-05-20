"""Tests for `platform_core.resilience.bulkhead`."""

from __future__ import annotations

import asyncio

import pytest

from platform_core.resilience.bulkhead import (
    BulkheadConfig,
    BulkheadFactory,
    BulkheadFullError,
    BulkheadService,
)


async def test_limits_concurrent_in_flight() -> None:
    bulk = BulkheadService("b", BulkheadConfig(max_concurrent=2))

    in_flight = 0
    peak = 0
    release = asyncio.Event()

    async def work() -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await release.wait()
        in_flight -= 1

    tasks = [asyncio.create_task(bulk.execute(work)) for _ in range(5)]
    await asyncio.sleep(0.05)
    assert peak == 2

    release.set()
    await asyncio.gather(*tasks)


async def test_releases_slot_on_handler_error() -> None:
    bulk = BulkheadService("b", BulkheadConfig(max_concurrent=1))

    async def boom() -> None:
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await bulk.execute(boom)

    async def ok() -> str:
        return "v"

    assert await bulk.execute(ok) == "v"


async def test_acquire_timeout_raises_full() -> None:
    bulk = BulkheadService(
        "b",
        BulkheadConfig(max_concurrent=1, acquire_timeout_seconds=0.05),
    )

    release = asyncio.Event()

    async def hold() -> None:
        await release.wait()

    holder = asyncio.create_task(bulk.execute(hold))
    await asyncio.sleep(0.01)

    async def ok() -> None:
        return None

    with pytest.raises(BulkheadFullError):
        await bulk.execute(ok)

    release.set()
    await holder


async def test_max_waiters_rejects_overflow() -> None:
    bulk = BulkheadService(
        "b",
        BulkheadConfig(max_concurrent=1, max_waiters=1),
    )

    release = asyncio.Event()

    async def hold() -> None:
        await release.wait()

    holder = asyncio.create_task(bulk.execute(hold))
    await asyncio.sleep(0.01)

    async def waiter() -> None:
        await asyncio.sleep(0)

    queued = asyncio.create_task(bulk.execute(waiter))
    await asyncio.sleep(0.01)

    async def overflow() -> None:
        return None

    with pytest.raises(BulkheadFullError):
        await bulk.execute(overflow)

    release.set()
    await asyncio.gather(holder, queued)


async def test_factory_caches_by_name() -> None:
    f = BulkheadFactory(BulkheadConfig())
    assert f.create("svc") is f.create("svc")
    assert f.create("svc") is not f.create("other")
