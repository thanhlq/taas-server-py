"""
Outbox repository for database operations.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from db import DBUtils
from db.models.resiliant import OutboxEventTable
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.outbox import IOutboxRepository, OutboxConfig, OutboxStatus
from foundation.utils import now_in_utc
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class OutboxRepository(IOutboxRepository):
    """
    Repository for outbox event database operations.

    Provides optimized queries with proper indexing and locking strategies.
    """

    def __init__(self, config: OutboxConfig):
        self.config = config
        self.logger = LogFactory().get_logger(self.__class__.__name__)

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
        cutoff = datetime.now() - timedelta(days=7)

        # Build query
        query = (
            select(OutboxEventTable)
            .where(
                and_(
                    OutboxEventTable.status == OutboxStatus.PENDING,  # ty:ignore[unresolved-reference]
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
                    updated_at=DBUtils.now(),
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
                updated_at=now_in_utc().replace(tzinfo=None),
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
                updated_at=DBUtils.now(),
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
        threshold = (now_in_utc() - timedelta(seconds=timeout_seconds)).replace(
            tzinfo=None
        )

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
                updated_at=DBUtils.now(),
            )
        )

        count = result.rowcount
        await session.commit()

        if count > 0:
            self.logger.warning(f'Reset {count} stale processing events')

        return count

    async def archive_published_events(
        self,
        session: AsyncSession,
        days: Optional[int] = None,
    ) -> int:
        """
        Move published events to archive table.

        Args:
            session: Database session
            days: Archive events older than N days (defaults to config)

        Returns:
            Number of events archived
        """
        days = days or self.config.archive_after_days
        threshold = (now_in_utc() - timedelta(days=days)).replace(tzinfo=None)

        # Find events to archive
        result = await session.execute(
            select(OutboxEventTable).where(
                and_(
                    OutboxEventTable.status == OutboxStatus.PUBLISHED,
                    OutboxEventTable.processed_at < threshold,
                )
            )
        )
        events = result.scalars().all()

        if not events:
            return 0

        # Insert into archive
        for event in events:
            archive = OutboxEventArchiveTable(
                id=event.id,
                event_id=event.event_id,
                event_type=event.event_type,
                channel=event.channel,
                partition_key=event.partition_key,
                payload=event.payload,
                headers=event.headers,
                status=event.status,
                retry_count=event.retry_count,
                max_retries=event.max_retries,
                last_error=event.last_error,
                created_at=event.created_at,
                updated_at=event.updated_at,
                processed_at=event.processed_at,
                source_service=event.source_service,
                correlation_id=event.correlation_id,
                user_id=event.user_id,
                tenant_id=event.tenant_id,
                archived_at=now_in_utc().replace(tzinfo=None),
            )
            session.add(archive)

        # Delete from main table
        event_ids = [e.id for e in events]
        await session.execute(
            delete(OutboxEventTable).where(OutboxEventTable.id.in_(event_ids))
        )

        await session.commit()

        self.logger.info(f'Archived {len(events)} published events')
        return len(events)

    async def cleanup_archive(
        self,
        session: AsyncSession,
        days: Optional[int] = None,
    ) -> int:
        """
        Delete old archived events.

        Args:
            session: Database session
            days: Delete archived events older than N days (defaults to config)

        Returns:
            Number of events deleted
        """
        days = days or self.config.cleanup_archive_after_days
        threshold = (now_in_utc() - timedelta(days=days)).replace(tzinfo=None)

        result = await session.execute(
            delete(OutboxEventArchiveTable).where(
                OutboxEventArchiveTable.archived_at < threshold
            )
        )

        count = result.rowcount
        await session.commit()

        if count > 0:
            self.logger.info(f'Cleaned up {count} archived events')

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
                (now_in_utc().replace(tzinfo=None) - oldest_pending).total_seconds()
                if oldest_pending
                else None
            ),
        }
