"""
Generic outbox repository — any ``OutboxRecordMixin`` table; same SQL as
``OutboxRepository`` of ``@taas/resiliant``.

Claiming is lock-based: ``FOR UPDATE SKIP LOCKED`` inside the relay's transaction,
outcomes written in the same transaction. There is no ``processing`` state to leak:
a relay that crashes mid-batch rolls back, its locks vanish and another replica
claims the same rows again (at-least-once).

Every status change is a compare-and-set on the claimable statuses, so a row an
operator dead-lettered or requeued meanwhile is never overwritten. Writes join the
caller's session; nothing here commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from foundation.resiliant.outbox import CLAIMABLE_OUTBOX_STATUSES, OutboxStatus
from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from resiliant.models.outbox import OutboxRecordMixin
from resiliant.sql import (
    clip,
    db_now,
    db_now_minus_ms,
    db_now_plus_ms,
    in_values,
    sql_literal,
)

OUTBOX_INSERT_CHUNK = 500
"""Rows per multi-row INSERT: far below the 65 535 bind-parameter cap."""


@dataclass(frozen=True, slots=True)
class OutboxFailure:
    record: OutboxRecordMixin
    error: str
    counted: bool
    """Attributed to the record (counts against its budget) or to the target (does not)."""
    retry_in_ms: float


class OutboxRepository[RecordT: OutboxRecordMixin]:
    """Claiming, status transitions, retention and stats for one outbox table."""

    def __init__(self, model: type[RecordT], config: Any = None) -> None:
        self.model = model
        self.config = config

    @property
    def table_name(self) -> str:
        return self.model.__tablename__  # type: ignore[attr-defined]

    async def _notify(self, session: AsyncSession, channel: str | None) -> None:
        if channel:
            # Delivered by Postgres when the caller's transaction commits.
            await session.execute(
                text('select pg_notify(:channel, :table)'),
                {'channel': channel, 'table': self.table_name},
            )

    async def append(
        self,
        session: AsyncSession,
        values: list[dict[str, Any]],
        notify_channel: str | None = None,
    ) -> int:
        """Insert rows; a row hitting a unique key (event id, request id) is skipped. Returns how many were new."""
        model = self.model
        inserted = 0
        for i in range(0, len(values), OUTBOX_INSERT_CHUNK):
            batch = values[i : i + OUTBOX_INSERT_CHUNK]
            stmt = (
                insert(model).values(batch).on_conflict_do_nothing().returning(model.id)
            )  # type: ignore[attr-defined]
            inserted += len((await session.execute(stmt)).all())
        if inserted:
            await self._notify(session, notify_channel)
        return inserted

    async def insert_returning(
        self,
        session: AsyncSession,
        value: dict[str, Any],
        notify_channel: str | None = None,
    ) -> RecordT | None:
        """Insert one row and return it; ``None`` when a unique key already exists."""
        model = self.model
        stmt = insert(model).values(value).on_conflict_do_nothing().returning(model)  # type: ignore[attr-defined]
        row = (await session.execute(stmt)).scalars().first()
        if row is not None:
            await self._notify(session, notify_channel)
        return row

    async def get(self, session: AsyncSession, record_id: int) -> RecordT | None:
        return await session.get(self.model, record_id)

    async def find_by(
        self, session: AsyncSession, column: str, value: Any
    ) -> RecordT | None:
        """First row whose ``column`` equals ``value`` (e.g. ``request_id``)."""
        target = getattr(self.model, column, None)
        if target is None:
            raise ValueError(f'{self.table_name} has no column {column!r}')
        return (
            (await session.execute(select(self.model).where(target == value).limit(1)))
            .scalars()
            .first()
        )

    async def find_one(self, session: AsyncSession, **criteria: Any) -> RecordT | None:
        conditions = [
            getattr(self.model, key) == value for key, value in criteria.items()
        ]
        return (
            (await session.execute(select(self.model).where(*conditions).limit(1)))
            .scalars()
            .first()
        )

    async def claim(
        self, session: AsyncSession, limit: int, *, preserve_ordering: bool
    ) -> list[RecordT]:
        """Lock up to ``limit`` due rows for this transaction, oldest (lowest id) first.

        Due = ``pending``, or ``failed`` whose backoff elapsed. With ``preserve_ordering`` a
        row waits while an earlier row of its ordering key is failing — on the same target
        and channel only (order only exists within one destination).
        """
        if not session.in_transaction():
            raise RuntimeError(
                f'OutboxRepository({self.table_name}).claim must run inside a transaction'
            )
        if limit < 1:
            return []
        t: Any = self.model
        conditions: list[Any] = [
            in_values(t.status, CLAIMABLE_OUTBOX_STATUSES),
            or_(t.next_attempt_at.is_(None), t.next_attempt_at <= db_now()),
        ]
        if preserve_ordering:
            earlier: Any = aliased(self.model, name='earlier')
            blocked = (
                select(text('1'))
                .select_from(earlier)
                .where(
                    earlier.ordering_key == t.ordering_key,
                    earlier.target.is_not_distinct_from(t.target),
                    earlier.channel.is_not_distinct_from(t.channel),
                    earlier.status == sql_literal(OutboxStatus.FAILED.value),
                    earlier.id < t.id,
                )
            )
            conditions.append(or_(t.ordering_key.is_(None), ~blocked.exists()))
        stmt = (
            select(t)
            .where(and_(*conditions))
            .order_by(t.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True, of=t)
        )
        return list((await session.execute(stmt)).scalars().all())

    async def mark_published(self, session: AsyncSession, ids: list[int]) -> int:
        if not ids:
            return 0
        t: Any = self.model
        result = await session.execute(
            update(t)
            .where(t.id.in_(ids), in_values(t.status, CLAIMABLE_OUTBOX_STATUSES))
            .values(
                status=OutboxStatus.PUBLISHED,
                processed_at=db_now(),
                updated_at=db_now(),
                last_error=None,
                next_attempt_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount  # type: ignore[attr-defined]

    async def mark_failed(
        self, session: AsyncSession, failure: OutboxFailure
    ) -> OutboxStatus:
        """Record a failed delivery; returns the new status."""
        record: Any = failure.record
        attempts = record.retry_count + 1 if failure.counted else record.retry_count
        dead = failure.counted and attempts >= record.max_retries
        status = OutboxStatus.DEAD_LETTER if dead else OutboxStatus.FAILED
        t: Any = self.model
        await session.execute(
            update(t)
            .where(t.id == record.id, in_values(t.status, CLAIMABLE_OUTBOX_STATUSES))
            .values(
                status=status,
                retry_count=attempts,
                last_error=clip(failure.error),
                next_attempt_at=None if dead else db_now_plus_ms(failure.retry_in_ms),
                updated_at=db_now(),
            )
            .execution_options(synchronize_session=False)
        )
        return status

    async def requeue_dead_letters(
        self, session: AsyncSession, ids: list[int] | None = None, limit: int = 1000
    ) -> int:
        """Put dead-lettered rows back in the queue with a fresh budget (operator action)."""
        if ids is not None and not ids:
            return 0
        t: Any = self.model
        dead = t.status == sql_literal(OutboxStatus.DEAD_LETTER.value)
        scope = (
            t.id.in_(ids)
            if ids is not None
            else t.id.in_(
                select(t.id)
                .where(dead)
                .order_by(t.id.asc())
                .limit(limit)
                .scalar_subquery()
            )
        )
        result = await session.execute(
            update(t)
            .where(scope, dead)
            .values(
                status=OutboxStatus.PENDING,
                retry_count=0,
                next_attempt_at=None,
                updated_at=db_now(),
            )
            .execution_options(synchronize_session=False)
        )
        return result.rowcount  # type: ignore[attr-defined]

    async def purge_published(
        self, session: AsyncSession, older_than_ms: float, limit: int = 10_000
    ) -> int:
        """Retention: delete up to ``limit`` rows published more than ``older_than_ms`` ago (call until 0)."""
        t: Any = self.model
        doomed = (
            select(t.id)
            .where(
                t.status == sql_literal(OutboxStatus.PUBLISHED.value),
                t.processed_at < db_now_minus_ms(older_than_ms),
            )
            .limit(limit)
            .scalar_subquery()
        )
        result = await session.execute(
            delete(t).where(t.id.in_(doomed)).returning(t.id)
        )
        return len(result.all())

    async def list(
        self,
        session: AsyncSession,
        *,
        status: OutboxStatus | None = None,
        limit: int = 100,
        before_id: int | None = None,
    ) -> list[RecordT]:
        t: Any = self.model
        stmt = select(t)
        if status is not None:
            stmt = stmt.where(t.status == status)
        if before_id is not None:
            stmt = stmt.where(t.id < before_id)
        return list(
            (await session.execute(stmt.order_by(t.id.desc()).limit(limit)))
            .scalars()
            .all()
        )

    async def oldest_pending_age_ms(self, session: AsyncSession) -> int | None:
        """Age of the oldest claimable row (the ``_due_idx`` head), ``None`` when the queue is empty."""
        t: Any = self.model
        age = (
            await session.execute(
                select(
                    text('(extract(epoch from (now() - created_at)) * 1000)::bigint')
                )
                .select_from(t)
                .where(in_values(t.status, CLAIMABLE_OUTBOX_STATUSES))
                .order_by(t.id.asc())
                .limit(1)
            )
        ).scalar()
        return None if age is None else max(0, int(age))

    async def stats(
        self, session: AsyncSession, *, exact_published: bool = False
    ) -> dict[str, Any]:
        """Exact counts of the live statuses (partial indexes), ``published`` estimated unless
        ``exact_published``, and the age of the oldest claimable row."""
        t: Any = self.model
        counts = {status.value: 0 for status in OutboxStatus}
        live = await session.execute(
            select(t.status, func.count())
            .where(in_values(t.status, CLAIMABLE_OUTBOX_STATUSES))
            .group_by(t.status)
        )
        for status, count in live:
            counts[str(getattr(status, 'value', status))] = int(count)
        counts[OutboxStatus.DEAD_LETTER.value] = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(t)
                    .where(t.status == sql_literal('dead_letter'))
                )
            ).scalar()
            or 0
        )
        if exact_published:
            counts[OutboxStatus.PUBLISHED.value] = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(t)
                        .where(t.status == sql_literal('published'))
                    )
                ).scalar()
                or 0
            )
        else:
            estimate = (
                await session.execute(
                    text(
                        'select greatest(reltuples, 0)::bigint from pg_class where oid = to_regclass(:name)'
                    ),
                    {'name': self.table_name},
                )
            ).scalar() or 0
            others = counts['pending'] + counts['failed'] + counts['dead_letter']
            counts[OutboxStatus.PUBLISHED.value] = max(0, int(estimate) - others)
        return {
            'counts': counts,
            'oldest_pending_age_ms': await self.oldest_pending_age_ms(session),
        }


__all__ = ['OUTBOX_INSERT_CHUNK', 'OutboxFailure', 'OutboxRepository']
