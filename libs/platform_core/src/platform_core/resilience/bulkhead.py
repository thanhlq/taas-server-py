"""
Bulkhead primitive.

A bulkhead limits the number of concurrent in-flight calls to a dependency so
that a saturated downstream cannot exhaust caller resources.

This implementation is process-local (asyncio semaphore). An optional
repository protocol is provided for future distributed quota backends
(e.g. Redis token bucket).

Layout:

* `BulkheadConfig`        - policy
* `IBulkheadRepository`   - optional shared quota protocol
* `BulkheadService`       - guards an async handler
* `BulkheadFactory`       - DI helper
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

import msgspec


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class BulkheadError(Exception):
    """Base class for bulkhead errors."""


class BulkheadFullError(BulkheadError):
    """Raised when no slot is available within the wait budget."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Bulkhead {name!r} is full")
        self.name = name


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class BulkheadConfig(msgspec.Struct, frozen=True):
    """Policy for the bulkhead."""

    # Max in-flight concurrent calls.
    max_concurrent: int = 10
    # Max queued waiters before rejecting (None = unbounded queue).
    max_waiters: int | None = None
    # Max seconds a waiter blocks before BulkheadFullError (None = wait forever).
    acquire_timeout_seconds: float | None = None


# --------------------------------------------------------------------------- #
# Repository protocol (placeholder for distributed quota backends)
# --------------------------------------------------------------------------- #


@runtime_checkable
class IBulkheadRepository(Protocol):
    """Pluggable distributed quota backend."""

    async def acquire(self, name: str, *, timeout: float | None) -> bool: ...

    async def release(self, name: str) -> None: ...


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


__all__ = [
    "BulkheadConfig",
    "BulkheadError",
    "BulkheadFactory",
    "BulkheadFullError",
    "BulkheadService",
    "IBulkheadRepository",
]
