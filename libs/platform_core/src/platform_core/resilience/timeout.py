"""
Timeout primitive.

Caps the wall-clock duration of an async handler. Stateless.

Layout:

* `TimeoutConfig`   - policy
* `TimeoutService`  - executes a handler under a deadline
* `TimeoutFactory`  - DI helper
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import msgspec


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class TimeoutError_(Exception):
    """Raised when a handler exceeds its deadline."""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"Operation exceeded timeout of {seconds}s")
        self.seconds = seconds


# Public alias keeps the conventional name without shadowing builtins at module scope.
OperationTimeoutError = TimeoutError_


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class TimeoutConfig(msgspec.Struct, frozen=True):
    """Policy for the timeout service."""

    seconds: float = 5.0


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


__all__ = [
    "OperationTimeoutError",
    "TimeoutConfig",
    "TimeoutFactory",
    "TimeoutService",
]
