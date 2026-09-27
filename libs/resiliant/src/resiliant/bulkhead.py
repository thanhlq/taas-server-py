"""
Bulkhead (concurrency isolation) — implementation.

Definitions (errors, config, protocols) live in ``foundation.resiliant.bulkhead``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from foundation.resiliant.bulkhead import (
    BulkheadConfig,
    BulkheadFullError,
    IBulkheadRepository,
)

# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class BulkheadService:
    """
    Wraps an async handler with concurrency limits.

    Usage::

        result = await bulkhead.execute(lambda: client.call(...))
    """

    def __init__(
        self,
        name: str,
        config: BulkheadConfig | None = None,
        *,
        repository: IBulkheadRepository | None = None,
    ) -> None:
        self._name = name
        self._config = config or BulkheadConfig()
        self._repository = repository
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent)
        self._waiters = 0
        self._waiters_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def in_flight(self) -> int:
        return self._config.max_concurrent - self._semaphore._value  # type: ignore[attr-defined]

    async def execute[T](self, handler: Callable[[], Awaitable[T]]) -> T:
        await self._acquire()
        try:
            return await handler()
        finally:
            await self._release()

    async def _acquire(self) -> None:
        cfg = self._config

        if self._repository is not None:
            ok = await self._repository.acquire(
                self._name, timeout=cfg.acquire_timeout_seconds
            )
            if not ok:
                raise BulkheadFullError(self._name)
            return

        async with self._waiters_lock:
            if (
                cfg.max_waiters is not None
                and self._waiters >= cfg.max_waiters
                and self._semaphore.locked()
            ):
                raise BulkheadFullError(self._name)
            self._waiters += 1

        try:
            if cfg.acquire_timeout_seconds is None:
                await self._semaphore.acquire()
            else:
                try:
                    await asyncio.wait_for(
                        self._semaphore.acquire(), cfg.acquire_timeout_seconds
                    )
                except TimeoutError as exc:
                    raise BulkheadFullError(self._name) from exc
        finally:
            async with self._waiters_lock:
                self._waiters -= 1

    async def _release(self) -> None:
        if self._repository is not None:
            await self._repository.release(self._name)
            return
        self._semaphore.release()


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class BulkheadFactory:
    """Builds (and caches) `BulkheadService` instances by name."""

    def __init__(
        self,
        config: BulkheadConfig | None = None,
        *,
        repository: IBulkheadRepository | None = None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._cache: dict[str, BulkheadService] = {}

    def create(
        self, name: str, config: BulkheadConfig | None = None
    ) -> BulkheadService:
        if name not in self._cache:
            self._cache[name] = BulkheadService(
                name,
                config or self._config,
                repository=self._repository,
            )
        return self._cache[name]
