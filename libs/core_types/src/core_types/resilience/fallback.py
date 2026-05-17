"""
Fallback primitive.

Runs a primary async handler and, on a configured exception, invokes a
fallback handler instead.

Layout:

* `FallbackConfig`   - policy
* `FallbackService`  - primary -> fallback dispatcher
* `FallbackFactory`  - DI helper
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import msgspec


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class FallbackError(Exception):
    """Raised when both primary and fallback fail."""

    def __init__(self, primary: BaseException, fallback: BaseException) -> None:
        super().__init__(f"Primary failed: {primary!r}; fallback failed: {fallback!r}")
        self.primary = primary
        self.fallback = fallback


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class FallbackConfig(msgspec.Struct, frozen=True):
    """Policy for the fallback service."""

    # Exception types that trigger the fallback. Default: all `Exception`s.
    fallback_on: tuple[type[BaseException], ...] = (Exception,)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class FallbackService:
    """Executes a primary handler and falls back on configured exceptions."""

    def __init__(self, config: FallbackConfig | None = None) -> None:
        self._config = config or FallbackConfig()

    @property
    def config(self) -> FallbackConfig:
        return self._config

    async def execute[T](
        self,
        primary: Callable[[], Awaitable[T]],
        fallback: Callable[[BaseException], Awaitable[T]],
    ) -> T:
        try:
            return await primary()
        except self._config.fallback_on as primary_exc:
            try:
                return await fallback(primary_exc)
            except BaseException as fallback_exc:
                raise FallbackError(primary_exc, fallback_exc) from fallback_exc


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class FallbackFactory:
    """Builds `FallbackService` instances."""

    def __init__(self, config: FallbackConfig | None = None) -> None:
        self._config = config

    def create_service(self, config: FallbackConfig | None = None) -> FallbackService:
        return FallbackService(config or self._config)


__all__ = [
    "FallbackConfig",
    "FallbackError",
    "FallbackFactory",
    "FallbackService",
]
