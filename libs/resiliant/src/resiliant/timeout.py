"""
Timeout — implementation.

Definitions (errors, config, protocols) live in ``foundation.resiliant.timeout``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from foundation.resiliant.timeout import (
    OperationTimeoutError,
    TimeoutConfig,
)

# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class TimeoutService:
    """Runs an async handler with a hard deadline."""

    def __init__(self, config: TimeoutConfig | None = None) -> None:
        self._config = config or TimeoutConfig()

    @property
    def config(self) -> TimeoutConfig:
        return self._config

    async def execute[T](
        self,
        handler: Callable[[], Awaitable[T]],
        *,
        seconds: float | None = None,
    ) -> T:
        deadline = seconds if seconds is not None else self._config.seconds
        try:
            return await asyncio.wait_for(handler(), deadline)
        except TimeoutError as exc:
            raise OperationTimeoutError(deadline) from exc


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class TimeoutFactory:
    """Builds `TimeoutService` instances."""

    def __init__(self, config: TimeoutConfig | None = None) -> None:
        self._config = config

    def create_service(self, config: TimeoutConfig | None = None) -> TimeoutService:
        return TimeoutService(config or self._config)
