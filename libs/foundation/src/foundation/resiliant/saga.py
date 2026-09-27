"""
Saga primitive (orchestration-based).

A saga executes a sequence of local transactions; if any step fails, the
previously completed steps are compensated in reverse order, leaving the
system in a consistent state.

Layout:

* `SagaStatus`         - lifecycle state of a saga instance
* `SagaStepStatus`     - lifecycle state of an individual step
* `SagaStep`           - definition of a single step + compensation
* `SagaDefinition`     - ordered collection of steps
* `SagaInstance`       - persisted state of a running saga
* `SagaConfig`         - policy
* `ISagaRepository`    - pluggable storage protocol
* `SagaService`        - executor that runs forward / compensates on failure
* `SagaFactory`        - DI helper
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, runtime_checkable

import msgspec

from foundation.serialization import BaseEntity

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class SagaError(Exception):
    """Base class for saga errors."""


class SagaAbortedError(SagaError):
    """Raised when a saga aborted and compensations completed."""

    def __init__(self, saga_id: str, failed_step: str, cause: BaseException) -> None:
        super().__init__(
            f"Saga {saga_id!r} aborted at step {failed_step!r}: {cause!r}"
        )
        self.saga_id = saga_id
        self.failed_step = failed_step
        self.cause = cause


class SagaCompensationError(SagaError):
    """Raised when a compensation step itself fails (manual intervention required)."""


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


class SagaStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    ABORTED = "aborted"
    FAILED = "failed"  # compensation itself failed


class SagaStepStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    COMPENSATED = "compensated"
    FAILED = "failed"


# Step actions take and return a mutable JSON-serializable context dict.
SagaContext = dict[str, Any]
SagaAction = Callable[[SagaContext], Awaitable[None]]


class SagaStep:
    """A single step in a saga definition."""

    def __init__(
        self,
        name: str,
        action: SagaAction,
        compensation: SagaAction | None = None,
    ) -> None:
        self.name = name
        self.action = action
        self.compensation = compensation


class SagaDefinition:
    """An ordered, named collection of `SagaStep`s."""

    def __init__(self, name: str, steps: Sequence[SagaStep]) -> None:
        if not steps:
            raise ValueError("SagaDefinition must contain at least one step")
        self.name = name
        self.steps = list(steps)


class SagaStepRecord(BaseEntity):
    name: str
    status: SagaStepStatus = SagaStepStatus.PENDING
    error: str | None = None


class SagaInstance(BaseEntity):
    """Persisted state of a running or finished saga."""

    id: str
    name: str
    status: SagaStatus
    context: SagaContext
    steps: list[SagaStepRecord]
    created_at: float
    updated_at: float


class SagaConfig(msgspec.Struct, frozen=True):
    """Policy for saga execution."""

    # Re-raise SagaAbortedError after compensating (otherwise return the instance).
    raise_on_abort: bool = True


# --------------------------------------------------------------------------- #
# Repository protocol
# --------------------------------------------------------------------------- #


@runtime_checkable
class ISagaRepository(Protocol):
    """Storage contract for saga instances."""

    async def save(self, instance: SagaInstance) -> None: ...

    async def get(self, saga_id: str) -> SagaInstance | None: ...


@runtime_checkable
class ISagaService(Protocol):
    """Runs saga definitions and persists their progress (implementation:
    ``resiliant.saga.SagaService``; durable one via ``ResiliantServiceFactoryT.get_saga_service()``)."""

    async def run(
        self,
        definition: SagaDefinition,
        context: SagaContext | None = None,
        *,
        saga_id: str | None = None,
    ) -> SagaInstance:
        """Execute ``definition`` step by step, compensating completed steps on failure."""
        ...


__all__ = [
    "ISagaRepository",
    "ISagaService",
    "SagaAbortedError",
    "SagaAction",
    "SagaCompensationError",
    "SagaConfig",
    "SagaContext",
    "SagaDefinition",
    "SagaError",
    "SagaInstance",
    "SagaStatus",
    "SagaStep",
    "SagaStepRecord",
    "SagaStepStatus",
]
