"""
Database-backed saga repository (durable workflow state).

Implements :class:`foundation.resiliant.saga.ISagaRepository`, giving
:class:`foundation.resiliant.saga.SagaService` crash-durable state: the whole
:class:`SagaInstance` is checkpointed to ``saga_state`` after every step, so a
worker crash mid-flow loses nothing and the saga can be resumed, queried, or
signalled from outside.

Contract note
-------------
``ISagaRepository.save(instance)`` / ``get(saga_id)`` take **no session** — the
saga executor is decoupled from any business transaction. This repository
therefore owns its own :class:`AsyncSession` (resolved lazily from the main
database when a factory is not injected) and commits each checkpoint
independently. Extra query helpers (:meth:`get_by_key`, :meth:`get_stats`) power
Temporal-style *signals*, *queries*, and *visibility*.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from db.models.resiliant import SagaStateTable
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.saga import (
    SagaInstance,
    SagaStatus,
    SagaStepRecord,
    SagaStepStatus,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession


class SagaRepository:
    """Persists :class:`SagaInstance` state to the ``saga_state`` table."""

    def __init__(
        self,
        session_factory: Optional[Callable[[], AsyncSession]] = None,
    ) -> None:
        self._session_factory = session_factory
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    # ------------------------------------------------------------------ #
    # Session resolution (lazy, mirrors OutboxPoller.publisher)
    # ------------------------------------------------------------------ #

    @property
    def session_factory(self) -> Callable[[], AsyncSession]:
        if self._session_factory is None:
            from foundation.db.advanced_db_manager import MainDatabase

            self._session_factory = MainDatabase.get_instance().new_session
        return self._session_factory

    # ------------------------------------------------------------------ #
    # ISagaRepository
    # ------------------------------------------------------------------ #

    async def save(self, instance: SagaInstance) -> None:
        """Upsert the saga instance (race-safe on ``saga_id``)."""
        values = _instance_to_values(instance)
        stmt = pg_insert(SagaStateTable).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SagaStateTable.saga_id],
            set_={
                'status': values['status'],
                'current_step': values['current_step'],
                'context': values['context'],
                'steps': values['steps'],
                'last_error': values['last_error'],
                'saga_updated_at': values['saga_updated_at'],
            },
        )
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def get(self, saga_id: str) -> Optional[SagaInstance]:
        """Load a saga instance by its own id (or ``None``)."""
        async with self.session_factory() as session:
            row = await session.scalar(
                select(SagaStateTable).where(SagaStateTable.saga_id == saga_id)
            )
            return _row_to_instance(row) if row is not None else None

    # ------------------------------------------------------------------ #
    # Signals / Queries / Visibility (beyond the base Protocol)
    # ------------------------------------------------------------------ #

    async def get_by_key(self, name: str, saga_key: str) -> Optional[SagaInstance]:
        """Load the live saga for a business anchor — the *signal/query* lookup."""
        async with self.session_factory() as session:
            row = await session.scalar(
                select(SagaStateTable)
                .where(SagaStateTable.name == name)
                .where(SagaStateTable.saga_key == saga_key)
            )
            return _row_to_instance(row) if row is not None else None

    async def get_stats(self) -> dict[str, int]:
        """Return per-status counts across all sagas (visibility)."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    SagaStateTable.status, func.count(SagaStateTable.saga_id)
                ).group_by(SagaStateTable.status)
            )
            counts = dict(result)
        return {status.value: counts.get(status, 0) for status in SagaStatus}


# --------------------------------------------------------------------------- #
# (de)serialisation between SagaInstance and the ORM row
# --------------------------------------------------------------------------- #


def _current_step(instance: SagaInstance) -> str | None:
    """The first non-completed step — the human-readable resume pointer."""
    for record in instance.steps:
        if record.status is not SagaStepStatus.COMPLETED:
            return record.name
    return None


def _last_error(instance: SagaInstance) -> str | None:
    for record in reversed(instance.steps):
        if record.error:
            return record.error[:1000]
    return None


def _instance_to_values(instance: SagaInstance) -> dict[str, Any]:
    return {
        'saga_id': instance.id,
        'name': instance.name,
        'saga_key': instance.context.get('saga_key'),
        'status': instance.status,
        'current_step': _current_step(instance),
        'context': dict(instance.context),
        'steps': [
            {'name': s.name, 'status': s.status.value, 'error': s.error}
            for s in instance.steps
        ],
        'last_error': _last_error(instance),
        'saga_created_at': instance.created_at,
        'saga_updated_at': instance.updated_at,
    }


def _row_to_instance(row: SagaStateTable) -> SagaInstance:
    steps = [
        SagaStepRecord(
            name=s['name'],
            status=SagaStepStatus(s['status']),
            error=s.get('error'),
        )
        for s in (row.steps or [])
    ]
    return SagaInstance(
        id=row.saga_id,
        name=row.name,
        status=SagaStatus(row.status),
        context=dict(row.context or {}),
        steps=steps,
        created_at=row.saga_created_at,
        updated_at=row.saga_updated_at,
    )
