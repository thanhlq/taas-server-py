"""
Postgres idempotency store (``resiliant_processed_events``) — same protocol as
``PostgresIdempotencyStore`` of ``@taas/resiliant``.

``claim`` inserts the key FIRST (``INSERT … ON CONFLICT DO NOTHING RETURNING``) in a
savepoint of the caller's session, then the caller runs its work on that session:

* the work raises → the savepoint rolls back, the key is not recorded, the broker
  redelivers and it runs again;
* a concurrent duplicate blocks on the unique index until the first commits, then
  sees the conflict and skips — exactly once relative to the database, no
  check-then-act race.

The claim only becomes visible when the caller commits, so keep the guarded work
short: duplicates wait on it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from foundation.resiliant.idempotency import (
    IdempotencyBackend,
    IdempotencyConfig,
    IIdempotencyStore,
)
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models.idempotency import ProcessedEventTable
from resiliant.sql import interval_days


def _row(idempotency_key: str, scope: dict[str, Any]) -> dict[str, Any]:
    tenant_id = scope.get('tenant_id')
    return {
        'idempotency_key': idempotency_key,
        'event_id': scope['event_id'],
        'event_type': scope.get('event_type') or '',
        'handler_name': scope['handler_name'],
        'saga_id': scope.get('saga_id'),
        'correlation_id': scope.get('correlation_id'),
        'tenant_id': None if tenant_id is None else str(tenant_id),
        'extra_metadata': scope.get('metadata'),
    }


class PostgresIdempotencyStore(IIdempotencyStore):
    backend = IdempotencyBackend.POSTGRES

    def __init__(self, config: IdempotencyConfig) -> None:
        self.config = config

    async def _insert(
        self, session: AsyncSession, idempotency_key: str, scope: dict[str, Any]
    ) -> bool:
        stmt = (
            insert(ProcessedEventTable)
            .values(**_row(idempotency_key, scope))
            .on_conflict_do_nothing(
                index_elements=[ProcessedEventTable.idempotency_key]
            )
            .returning(ProcessedEventTable.id)
        )
        return (await session.execute(stmt)).first() is not None

    @asynccontextmanager
    async def claim(
        self, session: AsyncSession, idempotency_key: str, scope: dict[str, Any]
    ) -> AsyncIterator[bool]:
        async with session.begin_nested():
            claimed = await self._insert(session, idempotency_key, scope)
            yield claimed

    async def is_processed(self, session: AsyncSession, idempotency_key: str) -> bool:
        row = await session.execute(
            select(ProcessedEventTable.id)
            .where(ProcessedEventTable.idempotency_key == idempotency_key)
            .limit(1)
        )
        return row.first() is not None

    async def mark_processed(
        self,
        session: AsyncSession,
        idempotency_key: str,
        event_id: str,
        event_type: str,
        handler_name: str,
        *,
        saga_id: str | None = None,
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Record the key in the caller's session; ``True`` when this call inserted it."""
        return await self._insert(
            session,
            idempotency_key,
            {
                'event_id': event_id,
                'event_type': event_type,
                'handler_name': handler_name,
                'saga_id': saga_id,
                'correlation_id': correlation_id,
                'tenant_id': tenant_id,
                'metadata': extra_metadata,
            },
        )

    async def get_by_key(
        self, session: AsyncSession, idempotency_key: str
    ) -> ProcessedEventTable | None:
        """The stored row (diagnostics) — never on the hot path."""
        result = await session.execute(
            select(ProcessedEventTable)
            .where(ProcessedEventTable.idempotency_key == idempotency_key)
            .limit(1)
        )
        return result.scalars().first()

    async def cleanup_expired(
        self,
        session: AsyncSession,
        *,
        ttl_days: int | None = None,
        batch_size: int | None = None,
    ) -> int:
        """Oldest expired rows first, at most ``batch_size`` per call; loop until it returns 0."""
        days = ttl_days or self.config.ttl_days
        limit = batch_size or self.config.cleanup_batch_size
        t = ProcessedEventTable
        expired = (
            select(t.id)
            .where(t.created_at < func.now() - interval_days(days))
            .order_by(t.created_at.asc())
            .limit(limit)
            .scalar_subquery()
        )
        result = await session.execute(
            delete(t).where(t.id.in_(expired)).returning(t.id)
        )
        return len(result.all())


__all__ = ['PostgresIdempotencyStore']
