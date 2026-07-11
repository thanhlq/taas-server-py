"""
Database-backed outbox service.

Application-level entry point for the transactional-outbox pattern. Callers use
:meth:`OutboxService.save_event` / :meth:`save_raw_message` inside their own
business transaction so the domain write and the message enqueue commit
atomically. A separate relay/poller (out of scope here) later publishes the
``PENDING`` rows to the broker.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from db.models.resiliant import OutboxEventTable, OutboxStatus
from foundation import BaseService
from foundation.resiliant.outbox import IOutboxService, OutboxConfig
from sqlalchemy.ext.asyncio import AsyncSession

from .outbox_repository import OutboxRepository


class OutboxService(IOutboxService, BaseService):
    """High-level API for saving events to the outbox.

    Instances are cheap; one repository is created per service. Persistence is
    always scoped to the ``session`` passed by the caller.
    """

    def __init__(
        self,
        config: OutboxConfig,
        repository: OutboxRepository | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.repository = repository or OutboxRepository(config)

    async def save_event(
        self,
        session: AsyncSession,
        event: Any,
        channel: str,
        *,
        partition_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> OutboxEventTable:
        """Persist a domain ``event`` to the outbox within ``session``.

        The event is duck-typed: any object exposing ``event_id`` /
        ``event_type`` / ``correlation_id`` / ``source`` attributes and an
        ``as_dict()`` (or ``__dict__``) payload is accepted, so this service
        stays decoupled from any concrete event base class.

        Args:
            session: Business-transaction session (the event commits with it).
            event: Domain event object to publish.
            channel: Destination channel/topic/queue name.
            partition_key: Optional partition key (e.g. Kafka).
            headers: Optional message headers; correlation/event metadata is
                merged in automatically when present on the event.
            max_retries: Override the configured retry cap for this event.

        Returns:
            The persisted :class:`OutboxEventTable` row (flushed, not committed).
        """
        payload = self._extract_payload(event)
        event_id = str(getattr(event, "event_id", None) or uuid.uuid4())

        merged_headers: Dict[str, Any] = dict(headers or {})
        for attr in ("correlation_id", "event_id", "source"):
            value = getattr(event, attr, None)
            if value is not None:
                merged_headers.setdefault(attr, value)

        outbox_event = OutboxEventTable(
            event_id=event_id,
            event_type=getattr(event, "event_type", None)
            or type(event).__name__,
            channel=channel,
            partition_key=partition_key,
            payload=payload,
            headers=merged_headers,
            status=OutboxStatus.PENDING,
            retry_count=0,
            max_retries=max_retries or self.config.max_retries,
            source_service=getattr(event, "source", None),
            correlation_id=getattr(event, "correlation_id", None),
            user_id=getattr(event, "user_id", None),
            tenant_id=getattr(event, "tenant_id", None),
        )
        saved = await self.repository.save(session, outbox_event)
        self.logger.debug(
            "Saved event to outbox: %s (id=%s, channel=%s)",
            outbox_event.event_type,
            saved.id,
            channel,
        )
        return saved

    async def save_raw_message(
        self,
        session: AsyncSession,
        *,
        channel: str,
        payload: Dict[str, Any],
        event_type: str,
        partition_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> OutboxEventTable:
        """Persist an already-serialised message to the outbox.

        Use this when there is no domain-event object, only a raw JSON payload.
        """
        outbox_event = OutboxEventTable(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            channel=channel,
            partition_key=partition_key,
            payload=payload,
            headers=headers or {},
            status=OutboxStatus.PENDING,
            retry_count=0,
            max_retries=max_retries or self.config.max_retries,
        )
        return await self.repository.save(session, outbox_event)

    async def get_stats(self, session: AsyncSession) -> dict:
        """Return counters describing the current outbox backlog."""
        return await self.repository.get_stats(session)

    @staticmethod
    def _extract_payload(event: Any) -> Dict[str, Any]:
        """Best-effort conversion of a domain event into a JSON-safe payload."""
        as_dict = getattr(event, "as_dict", None)
        if callable(as_dict):
            return as_dict()
        to_dict = getattr(event, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        if isinstance(event, dict):
            return event
        return dict(getattr(event, "__dict__", {}) or {})
