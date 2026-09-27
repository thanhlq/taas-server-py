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

import enum
from typing import Protocol, runtime_checkable

import msgspec

from foundation.serialization import BaseEntity

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


__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerSnapshot",
    "CircuitOpenError",
    "CircuitState",
    "ICircuitBreakerRepository",
]
