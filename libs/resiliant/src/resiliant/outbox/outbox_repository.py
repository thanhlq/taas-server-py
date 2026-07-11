"""
Outbox repository for database operations.
"""
from datetime import timedelta
from typing import List, Optional

from db.models.resiliant import OutboxEventTable
from foundation import BaseService
from foundation.resiliant.outbox import OutboxConfig, OutboxStatus
from foundation.utils import now_in_utc
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository(BaseService):
    """
    Repository for outbox event database operations.

    Provides optimized queries with proper indexing and locking strategies.
    All methods operate on a caller-supplied :class:`AsyncSession` so writes can
    participate in the surrounding business transaction (the core guarantee of
    the transactional-outbox pattern).
    """

    def __init__(self, config: OutboxConfig):
        super().__init__()
        self.config = config

    async def save(
        self,
        session: AsyncSession,
        event: OutboxEventTable,
    ) -> OutboxEventTable:
        """
        Save an outbox event.

        Args:
            session: Database session (should be part of business transaction)
            event: Outbox event to save

        Returns:
            Saved outbox event
        """
        session.add(event)
        await session.flush()
        return event

    async def fetch_pending_batch(
        self,
        session: AsyncSession,
        batch_size: Optional[int] = None,
    ) -> List[OutboxEventTable]:
        """
        Fetch pending events for processing with proper locking.

        Uses FOR UPDATE SKIP LOCKED to prevent concurrent workers from
        processing the same events.

        Args:
            session: Database session
            batch_size: Number of events to fetch (defaults to config)

        Returns:
            List of outbox events ready for processing
        """
        batch_size = batch_size or self.config.batch_size
        cutoff = now_in_utc() - timedelta(days=7)

        # Build query
        query = (
            select(OutboxEventTable)
            .where(
                and_(
                    OutboxEventTable.status == OutboxStatus.PENDING,
                    OutboxEventTable.retry_count < OutboxEventTable.max_retries,
                    OutboxEventTable.created_at >= cutoff,
                )
            )
            .order_by(OutboxEventTable.created_at.asc())
            .limit(batch_size)
        )

        # Add FOR UPDATE SKIP LOCKED if enabled
        if self.config.use_skip_locked:
            query = query.with_for_update(skip_locked=True)

        result = await session.execute(query)
        events = result.scalars().all()

        # Mark as PROCESSING
        if events:
            event_ids = [e.id for e in events]
            await session.execute(
                update(OutboxEventTable)
                .where(OutboxEventTable.id.in_(event_ids))
                .values(
                    status=OutboxStatus.PROCESSING,
                    updated_at=now_in_utc(),
                )
            )
            await session.commit()

        return list(events)

    async def mark_published(
        self,
        session: AsyncSession,
        event_id: str,
    ) -> None:
        """
        Mark event as successfully published.

        Args:
            session: Database session
            event_id: Event ID to mark as published
        """
        await session.execute(
            update(OutboxEventTable)
            .where(OutboxEventTable.id == event_id)
            .values(
                status=OutboxStatus.PUBLISHED,
                processed_at=now_in_utc().replace(tzinfo=None),
                updated_at=now_in_utc(),
            )
        )
        await session.commit()

    async def mark_failed(
        self,
        session: AsyncSession,
        event_id: str,
        error: str,
    ) -> None:
        """
        Mark event as failed and increment retry count.

        If max retries exceeded, move to dead letter queue.

        Args:
            session: Database session
            event_id: Event ID to mark as failed
            error: Error message
        """
        # Get current event
        result = await session.execute(
            select(OutboxEventTable).where(OutboxEventTable.id == event_id)
        )
        event = result.scalar_one_or_none()

        if not event:
            self.logger.warning(f'Event {event_id} not found for marking as failed')
            return

        new_retry_count: int = event.retry_count + 1
        max_retries: int = event.max_retries
        # Determine new status
        if new_retry_count >= max_retries:
            new_status = OutboxStatus.DEAD_LETTER
            self.logger.error(
                f'Event {event_id} moved to DLQ after {new_retry_count} retries. '
                f'Error: {error}'
            )
        else:
            new_status = OutboxStatus.FAILED
            self.logger.warning(
                f'Event {event_id} failed (retry {new_retry_count}/{max_retries}). '
                f'Error: {error}'
            )

        # Update event
        await session.execute(
            update(OutboxEventTable)
            .where(OutboxEventTable.id == event_id)
            .values(
                status=new_status,
                retry_count=new_retry_count,
                last_error=error[:1000],  # Truncate error message
                updated_at=now_in_utc(),
            )
        )
        await session.commit()

    async def reset_stale_processing(
        self,
        session: AsyncSession,
        timeout_seconds: Optional[int] = None,
    ) -> int:
        """
        Reset events stuck in PROCESSING status.

        This handles cases where workers crashed or timed out.

        Args:
            session: Database session
            timeout_seconds: Processing timeout (defaults to config)

        Returns:
            Number of events reset
        """
        timeout_seconds = timeout_seconds or self.config.processing_timeout_seconds
        threshold = now_in_utc() - timedelta(seconds=timeout_seconds)

        result = await session.execute(
            update(OutboxEventTable)
            .where(
                and_(
                    OutboxEventTable.status == OutboxStatus.PROCESSING,
                    OutboxEventTable.updated_at < threshold,
                )
            )
            .values(
                status=OutboxStatus.PENDING,
                updated_at=now_in_utc(),
            )
        )

        count = result.rowcount
        await session.commit()

        if count > 0:
            self.logger.warning(f'Reset {count} stale processing events')

        return count

    async def get_stats(self, session: AsyncSession) -> dict:
        """
        Get outbox statistics.

        Returns:
            Dictionary with statistics
        """
        # Count by status
        result = await session.execute(
            select(
                OutboxEventTable.status,
                func.count(OutboxEventTable.id).label('count'),
            ).group_by(OutboxEventTable.status)
        )
        status_counts = {row.status: row.count for row in result}

        # Oldest pending event
        result = await session.execute(
            select(OutboxEventTable.created_at)
            .where(OutboxEventTable.status == OutboxStatus.PENDING)
            .order_by(OutboxEventTable.created_at.asc())
            .limit(1)
        )
        oldest_pending = result.scalar_one_or_none()

        return {
            'pending': status_counts.get(OutboxStatus.PENDING, 0),
            'processing': status_counts.get(OutboxStatus.PROCESSING, 0),
            'published': status_counts.get(OutboxStatus.PUBLISHED, 0),
            'failed': status_counts.get(OutboxStatus.FAILED, 0),
            'dead_letter': status_counts.get(OutboxStatus.DEAD_LETTER, 0),
            'oldest_pending_age_seconds': (
                (now_in_utc() - oldest_pending).total_seconds()
                if oldest_pending
                else None
            ),
        }
