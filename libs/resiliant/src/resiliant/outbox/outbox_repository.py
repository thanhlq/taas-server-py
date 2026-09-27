"""
Generic outbox repository — works on any ``OutboxRecordMixin`` table.

The table is chosen at construction (``OutboxRepository(MessagingOutboxTable, config)``),
so every use case shares the same claiming / retry / stats logic. All methods take
a caller-supplied :class:`AsyncSession`; ``save`` only flushes, so the record
commits with the surrounding business transaction (the outbox guarantee).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from foundation import BaseService
from foundation.resiliant.outbox import OutboxConfig, OutboxStatus
from foundation.utils import now_in_utc
from sqlalchemy import CursorResult, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models.outbox import OutboxRecordMixin

# Records older than this are ignored by the poller (manual follow-up instead).
_MAX_RECORD_AGE = timedelta(days=7)
# Retryable states: fresh records and failed ones waiting for their backoff.
_CLAIMABLE = (OutboxStatus.PENDING, OutboxStatus.FAILED)


class OutboxRepository[RecordT: OutboxRecordMixin](BaseService):
    """Claiming, status transitions and stats for one outbox table."""

    def __init__(self, model: type[RecordT], config: OutboxConfig):
        super().__init__()
        self.model = model
        self.config = config

    @property
    def table_name(self) -> str:
        return self.model.__tablename__  # type: ignore[attr-defined]

    async def save(self, session: AsyncSession, record: RecordT) -> RecordT:
        """Add ``record`` to the business transaction (flushed, not committed)."""
        session.add(record)
        await session.flush()
        return record

    async def find_one(self, session: AsyncSession, **criteria: Any) -> RecordT | None:
        """First record whose columns equal ``criteria`` (e.g. ``request_id=…``)."""
        model = self.model
        conditions = [getattr(model, key) == value for key, value in criteria.items()]
        result = await session.execute(select(model).where(*conditions).limit(1))
        return result.scalar_one_or_none()

    async def fetch_pending_batch(
        self, session: AsyncSession, batch_size: int | None = None
    ) -> list[RecordT]:
        """Claim up to ``batch_size`` due records and mark them ``PROCESSING`` (commits).

        Due = ``PENDING``, or ``FAILED`` whose backoff elapsed, under the retry cap.
        ``FOR UPDATE SKIP LOCKED`` lets several pollers share a table safely.
        """
        model = self.model
        now = now_in_utc()
        query = (
            select(model)
            .where(
                and_(
                    model.status.in_(_CLAIMABLE),
                    model.retry_count < model.max_retries,
                    model.created_at >= now - _MAX_RECORD_AGE,  # type: ignore[attr-defined]
                    or_(model.next_attempt_at.is_(None), model.next_attempt_at <= now),
                )
            )
            .order_by(model.created_at.asc())  # type: ignore[attr-defined]
            .limit(batch_size or self.config.batch_size)
        )
        if self.config.use_skip_locked:
            query = query.with_for_update(skip_locked=True)

        records = list((await session.execute(query)).scalars().all())
        if records:
            await session.execute(
                update(model)
                .where(model.id.in_([r.id for r in records]))  # type: ignore[attr-defined]
                .values(status=OutboxStatus.PROCESSING, updated_at=now)
            )
            await session.commit()
        return records

    async def mark_published(self, session: AsyncSession, record_id: Any) -> None:
        """Record successful delivery (commits)."""
        now = now_in_utc()
        await session.execute(
            update(self.model)
            .where(self.model.id == record_id)  # type: ignore[attr-defined]
            .values(status=OutboxStatus.PUBLISHED, processed_at=now, updated_at=now, last_error=None)
        )
        await session.commit()

    async def mark_failed(self, session: AsyncSession, record_id: Any, error: str) -> OutboxStatus | None:
        """Count a failed delivery (commits).

        Below ``max_retries`` the record becomes ``FAILED`` and is retried after
        ``retry_backoff_multiplier ** attempt`` seconds; at the cap it becomes
        ``DEAD_LETTER`` (terminal). Returns the new status (``None`` if not found).
        """
        model = self.model
        record = (
            await session.execute(select(model).where(model.id == record_id))  # type: ignore[attr-defined]
        ).scalar_one_or_none()
        if record is None:
            self.logger.warning('%s: record %s not found for marking as failed', self.table_name, record_id)
            return None

        attempts = record.retry_count + 1
        now = now_in_utc()
        if attempts >= record.max_retries:
            status, next_attempt_at = OutboxStatus.DEAD_LETTER, None
            self.logger.error(
                '%s: record %s dead-lettered after %s attempts: %s', self.table_name, record_id, attempts, error
            )
        else:
            status = OutboxStatus.FAILED
            next_attempt_at = now + timedelta(seconds=self.config.retry_backoff_multiplier**attempts)
            self.logger.warning(
                '%s: record %s failed (attempt %s/%s), retry at %s: %s',
                self.table_name, record_id, attempts, record.max_retries, next_attempt_at.isoformat(), error,
            )

        await session.execute(
            update(model)
            .where(model.id == record_id)  # type: ignore[attr-defined]
            .values(
                status=status,
                retry_count=attempts,
                last_error=error[:1000],
                next_attempt_at=next_attempt_at,
                updated_at=now,
            )
        )
        await session.commit()
        return status

    async def reset_stale_processing(self, session: AsyncSession, timeout_seconds: int | None = None) -> int:
        """Return records stuck in ``PROCESSING`` (crashed poller) to ``PENDING`` (commits)."""
        model = self.model
        threshold = now_in_utc() - timedelta(seconds=timeout_seconds or self.config.processing_timeout_seconds)
        result: CursorResult[Any] = await session.execute(  # type: ignore[assignment]
            update(model)
            .where(and_(model.status == OutboxStatus.PROCESSING, model.updated_at < threshold))  # type: ignore[attr-defined]
            .values(status=OutboxStatus.PENDING, updated_at=now_in_utc())
        )
        count = result.rowcount
        await session.commit()
        if count > 0:
            self.logger.warning('%s: reset %s stale processing records', self.table_name, count)
        return count

    async def get_stats(self, session: AsyncSession) -> dict[str, Any]:
        """Counts per status plus the age of the oldest pending record."""
        model = self.model
        result = await session.execute(
            select(model.status, func.count(model.id).label('count')).group_by(model.status)  # type: ignore[attr-defined]
        )
        counts = {row.status: row.count for row in result}
        oldest_pending = (
            await session.execute(
                select(model.created_at)  # type: ignore[attr-defined]
                .where(model.status == OutboxStatus.PENDING)
                .order_by(model.created_at.asc())  # type: ignore[attr-defined]
                .limit(1)
            )
        ).scalar_one_or_none()
        return {
            'table': self.table_name,
            **{status.value: counts.get(status, 0) for status in OutboxStatus},
            'oldest_pending_age_seconds': (
                (now_in_utc() - oldest_pending).total_seconds() if oldest_pending else None
            ),
        }
