"""
Circuit breaker primitive.

A circuit breaker short-circuits calls to a failing dependency to give it time
to recover and to fail fast for the caller.

States:

* `CLOSED`    - calls pass through; failures are counted.
* `OPEN`      - calls fail fast until `recovery_timeout_seconds` elapses.
* `HALF_OPEN` - a limited number of probe calls are allowed; success closes
  the breaker, failure re-opens it.

Layout:

* `CircuitState`           - enum of breaker states
* `CircuitBreakerSnapshot` - persisted state for a named breaker
* `CircuitBreakerConfig`   - policy (thresholds, recovery window)
* `ICircuitBreakerRepository` - optional shared storage protocol
* `CircuitBreakerService`  - guards an async handler
* `CircuitBreakerFactory`  - DI helper
"""

from __future__ import annotations

import asyncio
import enum
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

import msgspec

from platform_core.base_entity import BaseEntity


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class CircuitBreakerError(Exception):
    """Base class for circuit breaker errors."""


class CircuitOpenError(CircuitBreakerError):
    """Raised when a call is rejected because the breaker is open."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Circuit {name!r} is open")
        self.name = name


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class CircuitState(enum.StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerSnapshot(BaseEntity):
    """Persisted state of a named circuit breaker."""

    name: str
    state: CircuitState
    failure_count: int = 0
    success_count: int = 0
    opened_at: float | None = None


class CircuitBreakerConfig(msgspec.Struct, frozen=True):
    """Policy for the circuit breaker."""

    # Consecutive failures that flip CLOSED -> OPEN.
    failure_threshold: int = 5
    # How long to stay OPEN before allowing probes (HALF_OPEN).
    recovery_timeout_seconds: float = 30.0
    # Probe calls allowed while HALF_OPEN.
    half_open_max_calls: int = 1
    # Consecutive successes in HALF_OPEN that flip back to CLOSED.
    success_threshold: int = 1


# --------------------------------------------------------------------------- #
# Repository protocol (optional, for shared state across instances)
# --------------------------------------------------------------------------- #


@runtime_checkable
class ICircuitBreakerRepository(Protocol):
    """Pluggable storage for breaker snapshots (e.g. Redis for fleet-wide state)."""

    async def get(self, name: str) -> CircuitBreakerSnapshot | None: ...

    async def save(self, snapshot: CircuitBreakerSnapshot) -> None: ...


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class CircuitBreakerService:
    """
    Guards an async handler with a circuit breaker.

    Usage::

        result = await breaker.call(lambda: client.fetch(url))
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        *,
        repository: ICircuitBreakerRepository | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._repository = repository
        self._clock = clock
        self._lock = asyncio.Lock()
        self._snapshot = CircuitBreakerSnapshot(
            name=name, state=CircuitState.CLOSED
        )
        self._half_open_in_flight = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def config(self) -> CircuitBreakerConfig:
        return self._config

    async def snapshot(self) -> CircuitBreakerSnapshot:
        await self._refresh()
        return self._snapshot

    async def call[T](self, handler: Callable[[], Awaitable[T]]) -> T:
        await self._before_call()
        try:
            result = await handler()
        except BaseException:
            await self._on_failure()
            raise
        await self._on_success()
        return result

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _refresh(self) -> None:
        if self._repository is None:
            return
        stored = await self._repository.get(self._name)
        if stored is not None:
            self._snapshot = stored

    async def _persist(self) -> None:
        if self._repository is not None:
            await self._repository.save(self._snapshot)

    async def _before_call(self) -> None:
        async with self._lock:
            await self._refresh()
            snap = self._snapshot
            if snap.state is CircuitState.OPEN:
                assert snap.opened_at is not None
                if (
                    self._clock() - snap.opened_at
                    < self._config.recovery_timeout_seconds
                ):
                    raise CircuitOpenError(self._name)
                # transition to HALF_OPEN
                self._snapshot = CircuitBreakerSnapshot(
                    name=self._name,
                    state=CircuitState.HALF_OPEN,
                    opened_at=snap.opened_at,
                )
                self._half_open_in_flight = 0
                await self._persist()

            if self._snapshot.state is CircuitState.HALF_OPEN:
                if self._half_open_in_flight >= self._config.half_open_max_calls:
                    raise CircuitOpenError(self._name)
                self._half_open_in_flight += 1

    async def _on_success(self) -> None:
        async with self._lock:
            snap = self._snapshot
            if snap.state is CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(self._half_open_in_flight - 1, 0)
                successes = snap.success_count + 1
                if successes >= self._config.success_threshold:
                    self._snapshot = CircuitBreakerSnapshot(
                        name=self._name, state=CircuitState.CLOSED
                    )
                else:
                    self._snapshot = msgspec.structs.replace(
                        snap, success_count=successes
                    )
            elif snap.state is CircuitState.CLOSED and snap.failure_count:
                self._snapshot = msgspec.structs.replace(snap, failure_count=0)
            await self._persist()

    async def _on_failure(self) -> None:
        async with self._lock:
            snap = self._snapshot
            if snap.state is CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(self._half_open_in_flight - 1, 0)
                self._open(now=self._clock())
            else:
                failures = snap.failure_count + 1
                if failures >= self._config.failure_threshold:
                    self._open(now=self._clock())
                else:
                    self._snapshot = msgspec.structs.replace(
                        snap, failure_count=failures
                    )
            await self._persist()

    def _open(self, *, now: float) -> None:
        self._snapshot = CircuitBreakerSnapshot(
            name=self._name, state=CircuitState.OPEN, opened_at=now
        )
        self._half_open_in_flight = 0


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class CircuitBreakerFactory:
    """Builds (and caches) `CircuitBreakerService` instances by name."""

    def __init__(
        self,
        config: CircuitBreakerConfig | None = None,
        *,
        repository: ICircuitBreakerRepository | None = None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._cache: dict[str, CircuitBreakerService] = {}

    def create(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreakerService:
        if name not in self._cache:
            self._cache[name] = CircuitBreakerService(
                name,
                config or self._config,
                repository=self._repository,
            )
        return self._cache[name]


__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerFactory",
    "CircuitBreakerService",
    "CircuitBreakerSnapshot",
    "CircuitOpenError",
    "CircuitState",
    "ICircuitBreakerRepository",
]
