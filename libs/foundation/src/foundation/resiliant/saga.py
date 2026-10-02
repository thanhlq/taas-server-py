"""
Saga (orchestration) - contracts only (implementation: ``resiliant.saga``).

Twin of ``@taas/foundation/resiliant/saga`` (taas-server-js): same statuses,
same step-record shape, same errors - a saga checkpointed by one language can
be read, signalled and resumed by the other (shared ``resiliant_saga_state``).

A saga runs local steps in order; when one fails, the steps that already
completed are compensated in reverse order. The whole instance (status,
per-step records, accumulated context) is checkpointed after every step and
every compensation, which makes it durable: after a crash it can be resumed
from the first step that did not complete, queried, or signalled by its
business key (``saga_key``, unique per saga name).

Versioning rule (in-flight safety): steps are matched by NAME. Adding a step
is safe; renaming or removing one while instances may be in flight is not -
an unknown recorded name makes ``resume`` refuse the instance.

Layout:

* ``SagaStatus`` / ``SagaStepStatus``   - lifecycle of an instance / a step
* ``SagaStep`` / ``SagaDefinition``     - a validated definition (``define_saga``)
* ``SagaStepRecord`` / ``SagaInstance`` - persisted state (``steps`` jsonb items: ``{name, status, error}``)
* ``SagaConfig``                        - policy (``raise_on_abort``)
* ``ISagaRepository`` / ``ISignalableSagaRepository`` / ``ISagaService`` - protocols
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import msgspec

from foundation.serialization import BaseEntity

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


def _describe(error: BaseException | object) -> str:
    return str(error)


class SagaError(Exception):
    """Base class for saga errors (invalid definition, unknown instance, key collision...)."""


class SagaAbortedError(SagaError):
    """A step failed and every completed step was compensated."""

    def __init__(self, saga_id: str, failed_step: str, cause: BaseException) -> None:
        super().__init__(f'saga {saga_id} aborted at step "{failed_step}": {_describe(cause)}')
        self.saga_id = saga_id
        self.failed_step = failed_step
        self.cause = cause


class SagaCompensationError(SagaError):
    """A compensation itself failed: the saga is FAILED and needs manual intervention."""

    def __init__(self, saga_id: str, step: str, cause: BaseException) -> None:
        super().__init__(f'saga {saga_id}: compensation of "{step}" failed: {_describe(cause)}')
        self.saga_id = saga_id
        self.step = step
        self.cause = cause


# --------------------------------------------------------------------------- #
# Statuses
# --------------------------------------------------------------------------- #


class SagaStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATING = "compensating"
    ABORTED = "aborted"
    """Failed and fully compensated."""
    FAILED = "failed"
    """A compensation failed."""


TERMINAL_SAGA_STATUSES: tuple[SagaStatus, ...] = (
    SagaStatus.COMPLETED,
    SagaStatus.ABORTED,
    SagaStatus.FAILED,
)


class SagaStepStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    COMPENSATED = "compensated"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Definition
# --------------------------------------------------------------------------- #

# The mutable, JSON-serialisable state steps share (bytes are stored as hex,
# other non-JSON values via ``msgspec.to_builtins``; keep ints < 2**53 or store
# them as strings so the Node twin reads them exactly).
SagaContext = dict[str, Any]
SagaAction = Callable[[SagaContext], Awaitable[None]]


class SagaStep:
    """A single step: ``action`` and its optional, idempotent undo ``compensation``."""

    __slots__ = ("action", "compensation", "name")

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
    """Validated definition: a name, at least one step, unique non-empty step names."""

    __slots__ = ("name", "steps")

    def __init__(self, name: str, steps: Sequence[SagaStep]) -> None:
        if not name:
            raise SagaError("a saga needs a name")
        if not steps:
            raise SagaError(f'saga "{name}" must contain at least one step')
        seen: set[str] = set()
        for step in steps:
            if not step.name or step.name in seen:
                raise SagaError(
                    f'saga "{name}": step names must be unique and non-empty ("{step.name}")'
                )
            seen.add(step.name)
        self.name = name
        self.steps: tuple[SagaStep, ...] = tuple(steps)


def define_saga(name: str, steps: Sequence[SagaStep]) -> SagaDefinition:
    """``defineSaga`` of the Node twin: a validated :class:`SagaDefinition`."""
    return SagaDefinition(name, steps)


# --------------------------------------------------------------------------- #
# Persisted state
# --------------------------------------------------------------------------- #


class SagaStepRecord(BaseEntity):
    """One item of the ``steps`` jsonb array: ``{"name", "status", "error"}``."""

    name: str
    status: SagaStepStatus = SagaStepStatus.PENDING
    error: str | None = None


class SagaInstance(BaseEntity, kw_only=True):
    """Persisted state of a running or finished saga (``id`` is the public ``saga_id``)."""

    id: str
    name: str
    saga_key: str | None = None
    """Business anchor for signals / queries, e.g. ``solana:mainnet:<tx>``; unique per saga name."""
    status: SagaStatus
    context: SagaContext
    steps: list[SagaStepRecord]
    created_at: datetime
    updated_at: datetime


class SagaConfig(msgspec.Struct, frozen=True):
    """Policy for saga execution."""

    raise_on_abort: bool = True
    """Raise :class:`SagaAbortedError` after compensating (otherwise return the ABORTED instance)."""


SagaStats = dict[str, int]
"""Instances per status - every :class:`SagaStatus` value is present."""


# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


@runtime_checkable
class ISagaRepository(Protocol):
    """Storage contract for saga instances (no session: checkpoints are independent of business transactions)."""

    async def save(self, instance: SagaInstance) -> None: ...

    async def get(self, saga_id: str) -> SagaInstance | None: ...

    async def get_by_key(self, name: str, saga_key: str) -> SagaInstance | None: ...

    async def stats(self) -> SagaStats: ...


@runtime_checkable
class ISignalableSagaRepository(ISagaRepository, Protocol):
    """A repository :class:`ISagaService` can signal through (both built-ins)."""

    async def merge_context(
        self, saga_id: str, patch: dict[str, Any], updated_at: datetime
    ) -> bool: ...


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
        saga_key: str | None = None,
    ) -> SagaInstance:
        """Execute ``definition`` step by step, compensating completed steps on failure."""
        ...

    async def resume(self, definition: SagaDefinition, saga_id: str) -> SagaInstance:
        """Continue an interrupted instance (RUNNING / COMPENSATING) from where it stopped."""
        ...

    async def signal(
        self, name: str, saga_key: str, patch: SagaContext
    ) -> SagaInstance | None:
        """Merge ``patch`` into a live saga's context (external event / signal)."""
        ...


def is_terminal_saga(instance: SagaInstance) -> bool:
    """COMPLETED, ABORTED or FAILED - nothing left to run."""
    return instance.status in TERMINAL_SAGA_STATUSES


__all__ = [
    "ISagaRepository",
    "ISagaService",
    "ISignalableSagaRepository",
    "SagaAbortedError",
    "SagaAction",
    "SagaCompensationError",
    "SagaConfig",
    "SagaContext",
    "SagaDefinition",
    "SagaError",
    "SagaInstance",
    "SagaStats",
    "SagaStatus",
    "SagaStep",
    "SagaStepRecord",
    "SagaStepStatus",
    "TERMINAL_SAGA_STATUSES",
    "define_saga",
    "is_terminal_saga",
]
