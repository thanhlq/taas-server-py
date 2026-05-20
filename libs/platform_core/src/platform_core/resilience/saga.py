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
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol, runtime_checkable

import msgspec

from platform_core.serialization import BaseEntity


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


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #


class SagaService:
    """Executes saga definitions and persists their progress."""

    def __init__(
        self,
        repository: ISagaRepository,
        config: SagaConfig | None = None,
    ) -> None:
        self._repository = repository
        self._config = config or SagaConfig()

    async def run(
        self,
        definition: SagaDefinition,
        context: SagaContext | None = None,
        *,
        saga_id: str | None = None,
    ) -> SagaInstance:
        now = time.time()
        instance = SagaInstance(
            id=saga_id or str(uuid.uuid4()),
            name=definition.name,
            status=SagaStatus.RUNNING,
            context=dict(context or {}),
            steps=[SagaStepRecord(name=step.name) for step in definition.steps],
            created_at=now,
            updated_at=now,
        )
        await self._repository.save(instance)

        for index, step in enumerate(definition.steps):
            try:
                await step.action(instance.context)
            except BaseException as exc:
                instance.steps[index].status = SagaStepStatus.FAILED
                instance.steps[index].error = repr(exc)
                instance.status = SagaStatus.COMPENSATING
                instance.updated_at = time.time()
                await self._repository.save(instance)
                await self._compensate(definition, instance, failed_index=index)
                if self._config.raise_on_abort and instance.status is SagaStatus.ABORTED:
                    raise SagaAbortedError(instance.id, step.name, exc) from exc
                return instance

            instance.steps[index].status = SagaStepStatus.COMPLETED
            instance.updated_at = time.time()
            await self._repository.save(instance)

        instance.status = SagaStatus.COMPLETED
        instance.updated_at = time.time()
        await self._repository.save(instance)
        return instance

    async def _compensate(
        self,
        definition: SagaDefinition,
        instance: SagaInstance,
        *,
        failed_index: int,
    ) -> None:
        for i in range(failed_index - 1, -1, -1):
            step = definition.steps[i]
            record = instance.steps[i]
            if record.status is not SagaStepStatus.COMPLETED or step.compensation is None:
                continue
            try:
                await step.compensation(instance.context)
            except BaseException as exc:
                record.error = f"compensation failed: {exc!r}"
                instance.status = SagaStatus.FAILED
                instance.updated_at = time.time()
                await self._repository.save(instance)
                raise SagaCompensationError(
                    f"Compensation for step {step.name!r} failed"
                ) from exc
            record.status = SagaStepStatus.COMPENSATED

        instance.status = SagaStatus.ABORTED
        instance.updated_at = time.time()
        await self._repository.save(instance)


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


class SagaFactory:
    """Builds `SagaService` instances."""

    def __init__(
        self,
        repository: ISagaRepository,
        config: SagaConfig | None = None,
    ) -> None:
        self._repository = repository
        self._config = config

    def create_service(self, config: SagaConfig | None = None) -> SagaService:
        return SagaService(
            repository=self._repository,
            config=config or self._config,
        )


__all__ = [
    "ISagaRepository",
    "SagaAbortedError",
    "SagaAction",
    "SagaCompensationError",
    "SagaConfig",
    "SagaContext",
    "SagaDefinition",
    "SagaError",
    "SagaFactory",
    "SagaInstance",
    "SagaService",
    "SagaStatus",
    "SagaStep",
    "SagaStepRecord",
    "SagaStepStatus",
]
