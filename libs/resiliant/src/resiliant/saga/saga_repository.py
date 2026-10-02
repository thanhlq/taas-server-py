"""
Saga state stores (twin of ``@taas/resiliant`` ``saga/repositories.ts``).

:class:`PgSagaRepository` (alias :class:`SagaRepository`) checkpoints the whole
:class:`SagaInstance` to ``resiliant_saga_state`` after every step. It runs on
its own session (one short transaction per call), never on a business
transaction: a checkpoint must survive the failure of the step that follows it.
The upsert is keyed on ``saga_id``; ``(name, saga_key)`` is unique (when the key
is not null), so two flows for the same business anchor cannot start.

Row shape - identical to the Node twin, so either language reads/resumes the
other's instances:

* ``saga_id`` = ``instance.id``; ``id`` is the internal bigint identity;
* ``steps`` = ``[{"name": ..., "status": "pending|completed|compensated|failed", "error": str|null}]``;
* ``current_step`` = first step not completed; ``last_error`` = newest step error (clipped to 1000);
* ``created_at`` / ``updated_at`` = the executor clock (set by the code, no DB default).

:class:`MemorySagaRepository` is for unit tests.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import msgspec
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.saga import (
    SagaError,
    SagaInstance,
    SagaStats,
    SagaStatus,
    SagaStepRecord,
    SagaStepStatus,
)
from sqlalchemy import bindparam, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import SagaStateTable
from resiliant.sql import clip

LAST_ERROR_MAX = 1000
DEFAULT_ACTIVE_LIMIT = 100


# --------------------------------------------------------------------------- #
# Helpers (shared with the service)
# --------------------------------------------------------------------------- #


def is_unique_violation(error: BaseException) -> bool:
    """True for a Postgres unique violation (SQLSTATE 23505), whatever the driver."""
    current: BaseException | None = error
    for _ in range(4):
        if current is None:
            break
        for attr in ("sqlstate", "pgcode"):
            if getattr(current, attr, None) == "23505":
                return True
        current = getattr(current, "orig", None) or current.__cause__
    return False


def to_json(value: Any) -> Any:
    """JSON-safe copy of ``value`` for a jsonb column (``safeJsonb`` of the Node twin).

    ``bytes`` become hex (as the Node replacer does for ``Uint8Array``); datetimes,
    UUIDs, Decimals, enums, structs... go through ``msgspec.to_builtins``.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, Mapping):
        return {str(k): to_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_json(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return to_json(msgspec.to_builtins(value))


def current_step(instance: SagaInstance) -> str | None:
    """First step not completed - the resume pointer shown to humans."""
    for record in instance.steps:
        if record.status != SagaStepStatus.COMPLETED:
            return record.name
    return None


def last_error(instance: SagaInstance) -> str | None:
    """The newest step error, clipped."""
    for record in reversed(instance.steps):
        if record.error:
            return clip(record.error, LAST_ERROR_MAX)
    return None


def _enum_or_raw[E](enum_cls: Callable[[str], E], value: Any) -> E | Any:
    """Known values as enum members; unknown ones (written by a newer twin) as-is."""
    try:
        return enum_cls(value)
    except ValueError:
        return value


def step_to_json(record: SagaStepRecord) -> dict[str, Any]:
    """The ``steps`` jsonb item - ``SagaStepRecordT`` of the Node twin."""
    return {"name": record.name, "status": str(record.status), "error": record.error}


def step_from_json(item: Mapping[str, Any]) -> SagaStepRecord:
    return SagaStepRecord(
        name=item["name"],
        status=_enum_or_raw(SagaStepStatus, item["status"]),
        error=item.get("error"),
    )


def instance_to_values(instance: SagaInstance) -> dict[str, Any]:
    """Column values of ``resiliant_saga_state`` for ``instance`` (by attribute name)."""
    return {
        "saga_id": instance.id,
        "name": instance.name,
        "saga_key": instance.saga_key,
        "status": instance.status,
        "current_step": current_step(instance),
        "context": to_json(instance.context),
        "steps": [step_to_json(s) for s in instance.steps],
        "last_error": last_error(instance),
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
    }


def row_to_instance(row: SagaStateTable) -> SagaInstance:
    return SagaInstance(
        id=row.saga_id,
        name=row.name,
        saga_key=row.saga_key,
        status=_enum_or_raw(SagaStatus, row.status),
        context=dict(row.context or {}),
        steps=[step_from_json(s) for s in (row.steps or [])],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def empty_stats() -> SagaStats:
    return {status.value: 0 for status in SagaStatus}


def _duplicate_key(instance: SagaInstance) -> SagaError:
    return SagaError(f'saga "{instance.name}" with key {instance.saga_key} already exists')


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #


class PgSagaRepository:
    """Persists :class:`SagaInstance` state to ``resiliant_saga_state``."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    @property
    def session_factory(self) -> Callable[[], AsyncSession]:
        """Injected factory, else the main database (resolved lazily on first use)."""
        if self._session_factory is None:
            from foundation.db.advanced_db_manager import MainDatabase

            self._session_factory = MainDatabase.get_instance().new_session
        return self._session_factory

    async def save(self, instance: SagaInstance) -> None:
        """Upsert on ``saga_id``; never rewrites another definition's row nor its identity."""
        values = instance_to_values(instance)
        table = SagaStateTable
        stmt = (
            pg_insert(table)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[table.saga_id],
                set_={
                    "status": values["status"],
                    "current_step": values["current_step"],
                    "context": values["context"],
                    "steps": values["steps"],
                    "last_error": values["last_error"],
                    "updated_at": values["updated_at"],
                },
                # A checkpoint never rewrites another flow's row, nor changes its identity.
                where=table.name == instance.name,
            )
            .returning(table.id)
        )
        async with self.session_factory() as session:
            try:
                row = (await session.execute(stmt)).first()
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                if is_unique_violation(error):
                    raise _duplicate_key(instance) from error
                raise
        if row is None:
            raise SagaError(
                f'saga {instance.id} belongs to another definition than "{instance.name}"'
            )

    async def get(self, saga_id: str) -> SagaInstance | None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(SagaStateTable).where(SagaStateTable.saga_id == saga_id).limit(1)
            )
            return row_to_instance(row) if row is not None else None

    async def get_by_key(self, name: str, saga_key: str) -> SagaInstance | None:
        """The saga of a business anchor - the *signal / query* lookup."""
        async with self.session_factory() as session:
            row = await session.scalar(
                select(SagaStateTable)
                .where(SagaStateTable.name == name, SagaStateTable.saga_key == saga_key)
                .limit(1)
            )
            return row_to_instance(row) if row is not None else None

    async def list_active(
        self, *, name: str | None = None, limit: int = DEFAULT_ACTIVE_LIMIT
    ) -> list[SagaInstance]:
        """Unfinished instances (running / compensating), oldest first - what a process resumes on startup."""
        stmt = select(SagaStateTable).where(
            SagaStateTable.status.in_([SagaStatus.RUNNING, SagaStatus.COMPENSATING])
        )
        if name:
            stmt = stmt.where(SagaStateTable.name == name)
        stmt = stmt.order_by(SagaStateTable.updated_at.asc()).limit(limit)
        async with self.session_factory() as session:
            rows = (await session.scalars(stmt)).all()
            return [row_to_instance(r) for r in rows]

    async def merge_context(
        self, saga_id: str, patch: dict[str, Any], updated_at: datetime
    ) -> bool:
        """Merge ``patch`` into the stored context (``jsonb ||``) - one statement, no lost update of other keys."""
        stmt = (
            SagaStateTable.__table__.update()
            .where(SagaStateTable.saga_id == saga_id)
            .values(
                context=SagaStateTable.context.op("||", return_type=JSONB)(
                    bindparam("patch", to_json(patch), type_=JSONB)
                ),
                updated_at=updated_at,
            )
            .returning(SagaStateTable.id)
        )
        async with self.session_factory() as session:
            row = (await session.execute(stmt)).first()
            await session.commit()
        return row is not None

    async def stats(self) -> SagaStats:
        """Instances per status (every status present)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(SagaStateTable.status, func.count()).group_by(SagaStateTable.status)
            )
            rows = result.all()
        stats = empty_stats()
        for status, count in rows:
            stats[str(status)] = int(count)
        return stats


SagaRepository = PgSagaRepository
"""Historical name of :class:`PgSagaRepository`."""


# --------------------------------------------------------------------------- #
# Memory (unit tests)
# --------------------------------------------------------------------------- #


class MemorySagaRepository:
    """In-process store with the same ``(name, saga_key)`` uniqueness; stores copies."""

    def __init__(self) -> None:
        self._instances: dict[str, SagaInstance] = {}

    async def save(self, instance: SagaInstance) -> None:
        for other in self._instances.values():
            if (
                other.id != instance.id
                and instance.saga_key is not None
                and other.name == instance.name
                and other.saga_key == instance.saga_key
            ):
                raise _duplicate_key(instance)
        self._instances[instance.id] = copy.deepcopy(instance)

    async def get(self, saga_id: str) -> SagaInstance | None:
        found = self._instances.get(saga_id)
        return copy.deepcopy(found) if found is not None else None

    async def get_by_key(self, name: str, saga_key: str) -> SagaInstance | None:
        for instance in self._instances.values():
            if instance.name == name and instance.saga_key == saga_key:
                return copy.deepcopy(instance)
        return None

    async def merge_context(
        self, saga_id: str, patch: dict[str, Any], updated_at: datetime
    ) -> bool:
        found = self._instances.get(saga_id)
        if found is None:
            return False
        found.context = {**found.context, **copy.deepcopy(patch)}
        found.updated_at = updated_at
        return True

    async def stats(self) -> SagaStats:
        stats = empty_stats()
        for instance in self._instances.values():
            key = str(instance.status)
            stats[key] = stats.get(key, 0) + 1
        return stats


__all__ = [
    "MemorySagaRepository",
    "PgSagaRepository",
    "SagaRepository",
    "current_step",
    "instance_to_values",
    "last_error",
    "row_to_instance",
]
