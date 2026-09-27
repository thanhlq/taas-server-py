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


__all__ = [
    "BulkheadConfig",
    "BulkheadError",
    "BulkheadFullError",
    "IBulkheadRepository",
]
