"""
Dead-letter repository (twin of ``@taas/resiliant`` ``dlq/repository.ts``).

Every method runs on the caller's :class:`AsyncSession` and never commits: a
write joins the caller's transaction.

* Every status change goes through :meth:`DLQRepository.transition`: the
  ``from -> to`` pair is checked against ``DLQ_TRANSITIONS`` before any SQL, and
  the UPDATE is a compare-and-set on the current status, so two operators (or an
  operator and a retry worker) can never both act on one record.
* Retry workers claim with a lease: rows move to ``processing`` and the claim
  commits (the worker's own transaction) before the handler runs — a replay may
  be slow or call out — and :meth:`DLQRepository.reset_stale` returns the rows of
  a crashed worker to ``pending``.
* Claim predicates inline the status literals (``in_values``) so they match the
  partial index ``resiliant_dlq_events_due_idx``; timestamps use the database clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import msgspec
from foundation import BaseService
from foundation.resiliant.dlq import (
    ARCHIVABLE_DLQ_STATUSES,
    RETRYABLE_DLQ_STATUSES,
    DeadLetterConfig,
    DeadLetterError,
    DLQStatus,
    NewDeadLetter,
    can_transition_dlq,
)
from sqlalchemy import BigInteger, and_, cast, func, insert, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import DLQEventArchiveTable, DLQEventTable
from resiliant.sql import clip, db_now, db_now_minus_ms, db_now_plus_ms, in_values

_PATCHABLE = frozenset({'retry_count', 'last_error', 'processed_at', 'next_attempt_at'})
_NO_SYNC = {'synchronize_session': False}


def _json_safe(value: Any) -> Any:
    """``jsonb`` that never fails on datetimes, bytes, UUIDs, decimals or structs."""
    return None if value is None else msgspec.to_builtins(value)


class DLQRepository(BaseService):
    """Dead-letter rows of ``resiliant_dlq_events`` (+ ``_archive``)."""

    def __init__(self, config: DeadLetterConfig | None = None) -> None:
        super().__init__()
        self.config = config or DeadLetterConfig()
        """Only supplies the default ``limit`` of :meth:`claim_due` / :meth:`list`."""

    async def insert(
        self, session: AsyncSession, event: NewDeadLetter, *, max_retries: int
    ) -> DLQEventTable:
        """Insert a ``pending`` dead letter (``failed_at`` defaults to the database clock)."""
        stmt = (
            insert(DLQEventTable)
            .values(
                event_id=event.event_id,
                event_type=event.event_type,
                handler_name=event.handler_name,
                source_destination=event.source_destination,
                source_service=event.source_service,
                payload=_json_safe(event.payload),
                headers=_json_safe(event.headers),
                status=DLQStatus.PENDING,
                retry_count=0,
                max_retries=max_retries,
                original_error=clip(event.error),
                correlation_id=event.correlation_id,
                user_id=event.user_id,
                tenant_id=event.tenant_id,
                failed_at=event.failed_at if event.failed_at is not None else db_now(),
            )
            .returning(DLQEventTable)
        )
        return (await session.scalars(stmt)).one()

    async def get(self, session: AsyncSession, dlq_id: int) -> DLQEventTable | None:
        stmt = (
            select(DLQEventTable)
            .where(DLQEventTable.id == dlq_id)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return (await session.scalars(stmt)).one_or_none()

    async def list(
        self,
        session: AsyncSession,
        *,
        status: DLQStatus | None = None,
        handler_name: str | None = None,
        event_type: str | None = None,
        before_id: int | None = None,
        limit: int | None = None,
    ) -> list[DLQEventTable]:
        """Newest first, keyset-paginated with ``before_id``."""
        t = DLQEventTable
        conditions = []
        if status is not None:
            conditions.append(t.status == status)
        if handler_name is not None:
            conditions.append(t.handler_name == handler_name)
        if event_type is not None:
            conditions.append(t.event_type == event_type)
        if before_id is not None:
            conditions.append(t.id < before_id)
        stmt = select(t)
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = (
            stmt.order_by(t.id.desc())
            .limit(limit or self.config.page_size)
            .execution_options(populate_existing=True)
        )
        return list((await session.scalars(stmt)).all())

    async def transition(
        self,
        session: AsyncSession,
        dlq_id: int,
        from_statuses: Iterable[DLQStatus],
        to_status: DLQStatus,
        **patch: Any,
    ) -> bool:
        """Compare-and-set ``from -> to`` (plus ``retry_count`` / ``last_error`` /
        ``processed_at`` / ``next_attempt_at``). ``False`` when the row is not in one
        of ``from_statuses`` any more (someone else acted first).

        Raises:
            DeadLetterError: an illegal transition (checked before any SQL).
        """
        sources = tuple(from_statuses)
        for status in sources:
            if not can_transition_dlq(status, to_status):
                raise DeadLetterError(f'illegal dead-letter transition {status} -> {to_status}')
        unknown = set(patch) - _PATCHABLE
        if unknown:
            raise DeadLetterError(f'cannot patch dead-letter columns {sorted(unknown)}')
        stmt = (
            update(DLQEventTable)
            .where(DLQEventTable.id == dlq_id, in_values(DLQEventTable.status, sources))
            .values(**patch, status=to_status, updated_at=db_now())
            .execution_options(**_NO_SYNC)
        )
        result = await session.execute(stmt)
        return result.rowcount == 1  # type: ignore[attr-defined]

    async def claim_due(self, session: AsyncSession, limit: int | None = None) -> list[DLQEventTable]:
        """Claim due retryable rows (``pending`` / ``approved`` whose backoff elapsed)
        and move them to ``processing`` (``FOR UPDATE SKIP LOCKED``). The caller
        commits before running the handlers."""
        t = DLQEventTable
        due = (
            select(t.id)
            .where(
                in_values(t.status, RETRYABLE_DLQ_STATUSES),
                or_(t.next_attempt_at.is_(None), t.next_attempt_at <= db_now()),
            )
            .order_by(t.id.asc())
            .limit(limit or self.config.batch_size)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(t)
            .where(t.id.in_(due.scalar_subquery()), in_values(t.status, RETRYABLE_DLQ_STATUSES))
            .values(status=DLQStatus.PROCESSING, updated_at=db_now())
            .returning(t)
            .execution_options(populate_existing=True, **_NO_SYNC)
        )
        rows = list((await session.scalars(stmt)).all())
        return sorted(rows, key=lambda row: row.id)

    async def record_failure(
        self, session: AsyncSession, record: DLQEventTable, error: str, retry_in_ms: float
    ) -> DLQStatus:
        """A retry failed: back to ``pending`` after a backoff, or ``abandoned`` when
        the budget is spent."""
        attempts = record.retry_count + 1
        exhausted = attempts >= record.max_retries
        to_status = DLQStatus.ABANDONED if exhausted else DLQStatus.PENDING
        ok = await self.transition(
            session,
            record.id,
            [DLQStatus.PROCESSING],
            to_status,
            retry_count=attempts,
            last_error=clip(error),
            next_attempt_at=None if exhausted else db_now_plus_ms(retry_in_ms),
        )
        if not ok:
            raise DeadLetterError(f'dead letter {record.id} was not processing any more')
        return to_status

    async def reset_stale(self, session: AsyncSession, timeout_ms: float) -> int:
        """Rows ``processing`` for longer than ``timeout_ms`` belonged to a crashed worker."""
        t = DLQEventTable
        stmt = (
            update(t)
            .where(
                in_values(t.status, [DLQStatus.PROCESSING]),
                t.updated_at < db_now_minus_ms(timeout_ms),
            )
            .values(status=DLQStatus.PENDING, updated_at=db_now())
            .execution_options(**_NO_SYNC)
        )
        result = await session.execute(stmt)
        return result.rowcount  # type: ignore[attr-defined]

    async def archive(self, session: AsyncSession, older_than_days: float, limit: int = 1000) -> int:
        """Move up to ``limit`` terminal rows older than ``older_than_days`` to the
        archive table (same id) — one statement, so a row is never in both tables
        or in neither."""
        live = DLQEventTable.__tablename__
        archive = DLQEventArchiveTable.__tablename__
        columns = ', '.join(column.name for column in DLQEventTable.__table__.columns)
        statuses = ', '.join(f"'{s.value}'" for s in ARCHIVABLE_DLQ_STATUSES)
        stmt = text(
            f"""
            with moved as (
              delete from "{live}"
              where id in (
                select id from "{live}"
                where status in ({statuses})
                  and updated_at < now() - (cast(:days as double precision) * interval '1 day')
                order by id
                limit :limit
              )
              returning *
            )
            insert into "{archive}" ({columns})
            select {columns} from moved
            """
        )
        result = await session.execute(
            stmt, {'days': float(older_than_days), 'limit': max(1, int(limit))}
        )
        return result.rowcount  # type: ignore[attr-defined]

    async def stats(self, session: AsyncSession) -> dict[str, Any]:
        """Per-status counts (every status, 0 when absent) + ``oldest_pending_age_ms``
        (age of the oldest retryable row, ``None`` when there is none)."""
        t = DLQEventTable
        rows = await session.execute(select(t.status, func.count()).group_by(t.status))
        stats: dict[str, Any] = {status.value: 0 for status in DLQStatus}
        for status, count in rows:
            stats[str(getattr(status, 'value', status))] = int(count)
        oldest = await session.scalar(
            select(cast(func.extract('epoch', func.now() - t.created_at) * 1000, BigInteger))
            .where(in_values(t.status, RETRYABLE_DLQ_STATUSES))
            .order_by(t.id.asc())
            .limit(1)
        )
        stats['oldest_pending_age_ms'] = None if oldest is None else int(oldest)
        return stats


__all__ = ['DLQRepository']
