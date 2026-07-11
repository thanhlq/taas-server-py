"""
Dead Letter Queue (DLQ) repository for database operations.

Stores events that exhausted their in-process retry budget so they can be
inspected, retried, or abandoned by operators/pollers. All methods operate on a
caller-supplied :class:`AsyncSession`.
"""

from __future__ import annotations

from typing import List, Optional

from db import DBUtils
from db.models.resiliant import DLQEventTable
from foundation import BaseService
from foundation.resiliant.dlq import DeadLetterConfig, DLQStatus
from foundation.utils import now_in_utc
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class DLQRepository(BaseService):
    """Repository for DLQ event database operations."""

    def __init__(self, config: DeadLetterConfig):
        super().__init__()
        self.config = config

    async def save(
        self,
        session: AsyncSession,
        event: DLQEventTable,
    ) -> DLQEventTable:
        """Persist a new DLQ event and flush to obtain its generated id."""
        session.add(event)
        await session.flush()
        return event

    async def get(
        self,
        session: AsyncSession,
        dlq_id: str,
    ) -> Optional[DLQEventTable]:
        """Return a single DLQ event by primary key (or ``None``)."""
        result = await session.execute(
            select(DLQEventTable).where(DLQEventTable.id == dlq_id)
        )
        return result.scalar_one_or_none()

    async def fetch_pending_batch(
        self,
        session: AsyncSession,
        batch_size: Optional[int] = None,
    ) -> List[DLQEventTable]:
        """Fetch a batch of retriable (PENDING) events and lock them.

        Uses ``FOR UPDATE SKIP LOCKED`` (when enabled) so concurrent workers
        never process the same row, then transitions the batch to PROCESSING.
        """
        batch_size = batch_size or self.config.batch_size

        query = (
            select(DLQEventTable)
            .where(
                and_(
                    DLQEventTable.status == DLQStatus.PENDING,
                    DLQEventTable.retry_count < DLQEventTable.max_retries,
                )
            )
            .order_by(DLQEventTable.created_at.asc())
            .limit(batch_size)
        )
        if self.config.use_skip_locked:
            query = query.with_for_update(skip_locked=True)

        result = await session.execute(query)
        events = list(result.scalars().all())

        if events:
            ids = [e.id for e in events]
            await session.execute(
                update(DLQEventTable)
                .where(DLQEventTable.id.in_(ids))
                .values(status=DLQStatus.PROCESSING, updated_at=now_in_utc())
            )
            await session.commit()

        return events

    async def list_messages(
        self,
        session: AsyncSession,
        *,
        status: Optional[DLQStatus] = None,
        handler_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[DLQEventTable]:
        """List DLQ events, optionally filtered by status and/or handler."""
        conditions = []
        if status is not None:
            conditions.append(DLQEventTable.status == status)
        if handler_name is not None:
            conditions.append(DLQEventTable.handler_name == handler_name)

        query = select(DLQEventTable)
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(DLQEventTable.created_at.desc()).limit(
            limit or self.config.page_size
        )

        result = await session.execute(query)
        return list(result.scalars().all())

    async def mark_resolved(
        self,
        session: AsyncSession,
        dlq_id: str,
    ) -> None:
        """Mark an event as successfully reprocessed."""
        await session.execute(
            update(DLQEventTable)
            .where(DLQEventTable.id == dlq_id)
            .values(
                status=DLQStatus.RESOLVED,
                processed_at=DBUtils.now(),
                updated_at=now_in_utc(),
            )
        )
        await session.commit()

    async def mark_failed(
        self,
        session: AsyncSession,
        dlq_id: str,
        error: str,
    ) -> None:
        """Record a failed retry attempt.

        Increments ``retry_count`` and stores ``last_error``. When the retry
        budget is exhausted the event is moved to ``ABANDONED``; otherwise it
        returns to ``PENDING`` so a later poll can retry it.
        """
        event = await self.get(session, dlq_id)
        if event is None:
            self.logger.warning("DLQ event %s not found for mark_failed", dlq_id)
            return

        new_retry_count = event.retry_count + 1
        exhausted = new_retry_count >= event.max_retries
        new_status = DLQStatus.ABANDONED if exhausted else DLQStatus.PENDING

        await session.execute(
            update(DLQEventTable)
            .where(DLQEventTable.id == dlq_id)
            .values(
                status=new_status,
                retry_count=new_retry_count,
                last_error=error[:1000],
                updated_at=now_in_utc(),
            )
        )
        await session.commit()

    async def mark_abandoned(
        self,
        session: AsyncSession,
        dlq_id: str,
    ) -> None:
        """Force an event to the ABANDONED state (no more automatic retries)."""
        await session.execute(
            update(DLQEventTable)
            .where(DLQEventTable.id == dlq_id)
            .values(status=DLQStatus.ABANDONED, updated_at=now_in_utc())
        )
        await session.commit()

    async def get_stats(self, session: AsyncSession) -> dict:
        """Return per-status counters for observability/dashboards."""
        result = await session.execute(
            select(
                DLQEventTable.status,
                func.count(DLQEventTable.id).label("count"),
            ).group_by(DLQEventTable.status)
        )
        counts = {row.status: row.count for row in result}
        return {status.value: counts.get(status, 0) for status in DLQStatus}
