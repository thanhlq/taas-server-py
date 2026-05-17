"""Tests for `core_types.resilience.fallback`."""

from __future__ import annotations

import pytest

from core_types.resilience.fallback import (
    FallbackConfig,
    FallbackError,
    FallbackFactory,
    FallbackService,
)


async def test_returns_primary_on_success() -> None:
    service = FallbackService()

    async def primary() -> str:
        return "primary"

    async def fb(_: BaseException) -> str:
        return "fb"

    assert await service.execute(primary, fb) == "primary"


async def test_invokes_fallback_on_failure() -> None:
    service = FallbackService()
    captured: list[BaseException] = []

    async def primary() -> str:
        raise RuntimeError("boom")

    async def fb(exc: BaseException) -> str:
        captured.append(exc)
        return "fb"

    assert await service.execute(primary, fb) == "fb"
    assert isinstance(captured[0], RuntimeError)


async def test_only_falls_back_on_configured_exception() -> None:
    service = FallbackService(FallbackConfig(fallback_on=(ValueError,)))

    async def primary() -> str:
        raise RuntimeError("not handled")

    async def fb(_: BaseException) -> str:
        return "fb"

    with pytest.raises(RuntimeError):
        await service.execute(primary, fb)


async def test_fallback_error_when_both_fail() -> None:
    service = FallbackService()

    async def primary() -> str:
        raise RuntimeError("p")

    async def fb(_: BaseException) -> str:
        raise ValueError("f")

    with pytest.raises(FallbackError) as exc_info:
        await service.execute(primary, fb)
    assert isinstance(exc_info.value.primary, RuntimeError)
    assert isinstance(exc_info.value.fallback, ValueError)


async def test_factory_builds_service() -> None:
    assert isinstance(FallbackFactory().create_service(), FallbackService)
