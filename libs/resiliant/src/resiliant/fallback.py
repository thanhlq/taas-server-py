"""
Fallback — implementation.

Definitions (errors, config, protocols) live in ``foundation.resiliant.fallback``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from foundation.resiliant.fallback import (
    FallbackConfig,
    FallbackError,
)

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
