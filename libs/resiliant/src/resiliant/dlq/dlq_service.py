"""
Database-backed Dead Letter Queue (DLQ) service.

Application-level API for recording poison messages that failed processing
after exhausting their in-process retry budget, and for querying the backlog.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from db.models.resiliant import DLQEventTable
from foundation import BaseService
from foundation.resiliant.dlq import DeadLetterConfig, DLQStatus, IDLQService
from foundation.utils import now_in_utc
from sqlalchemy.ext.asyncio import AsyncSession

from .dlq_repository import DLQRepository


class DLQService(IDLQService, BaseService):
    """High-level API for saving and inspecting dead-lettered events."""

    def __init__(
        self,
        config: DeadLetterConfig,
        repository: DLQRepository | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.repository = repository or DLQRepository(config)

    async def save_event(
        self,
        session: AsyncSession,
        *,
        event_id: str,
        event_type: str,
        handler_name: str,
        payload: Dict[str, Any],
        error: str,
        source_destination: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> DLQEventTable:
        """Persist a failed event to the DLQ within ``session``.

        Args:
            session: Database session.
            event_id: Id of the original event that failed.
            event_type: Logical event type (e.g. ``"OrderCreated"``).
            handler_name: Handler that failed — required to target the retry.
            payload: Full event payload, stored for replay.
            error: The error that caused the initial failure.
            source_destination: Original topic/queue, if known.
            headers: Optional headers (trace context, etc.).
            max_retries: Override the configured retry cap for this event.
            correlation_id: Optional correlation id for tracing.
            user_id / tenant_id: Optional ownership metadata.

        Returns:
            The persisted :class:`DLQEventTable` row (flushed, not committed).
        """
        dlq_event = DLQEventTable(
            event_id=event_id,
            event_type=event_type,
            handler_name=handler_name,
            source_destination=source_destination,
            payload=payload,
            headers=headers or {},
            status=DLQStatus.PENDING,
            retry_count=0,
            max_retries=max_retries or self.config.max_retries,
            original_error=error,
            correlation_id=correlation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            failed_at=now_in_utc().replace(tzinfo=None),
        )
        saved = await self.repository.save(session, dlq_event)
        self.logger.debug(
            "Saved failed event to DLQ: %s (id=%s, handler=%s)",
            event_type,
            saved.id,
            handler_name,
        )
        return saved

    async def get(
        self,
        session: AsyncSession,
        dlq_id: str,
    ) -> Optional[DLQEventTable]:
        """Return a single DLQ record by id (or ``None``)."""
        return await self.repository.get(session, dlq_id)

    async def list_pending(
        self,
        session: AsyncSession,
        *,
        limit: Optional[int] = None,
    ) -> List[DLQEventTable]:
        """Return pending DLQ records awaiting retry (newest first)."""
        return await self.repository.list_messages(
            session, status=DLQStatus.PENDING, limit=limit
        )

    async def list(
        self,
        session: AsyncSession,
        *,
        status: Optional[DLQStatus] = None,
        handler_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[DLQEventTable]:
        """List DLQ records with optional status/handler filters."""
        return await self.repository.list_messages(
            session, status=status, handler_name=handler_name, limit=limit
        )

    async def resolve(self, session: AsyncSession, dlq_id: str) -> None:
        """Mark a DLQ record as successfully reprocessed."""
        await self.repository.mark_resolved(session, dlq_id)

    async def fail(self, session: AsyncSession, dlq_id: str, error: str) -> None:
        """Record a failed retry attempt (may abandon when budget exhausted)."""
        await self.repository.mark_failed(session, dlq_id, error)

    async def abandon(self, session: AsyncSession, dlq_id: str) -> None:
        """Force a DLQ record to the ABANDONED state."""
        await self.repository.mark_abandoned(session, dlq_id)

    async def get_stats(self, session: AsyncSession) -> dict:
        """Return per-status counters describing the DLQ backlog."""
        return await self.repository.get_stats(session)
