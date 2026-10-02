"""
Outbox writers — records are written inside the caller's transaction, never on their
own (same services as ``@taas/resiliant``):

* :class:`OutboxService`            — generic ``enqueue`` for any registered outbox;
* :class:`MessagingOutboxService`   — domain events → broker, idempotent on ``event_id``
  (a re-append is ignored by the unique key);
* :class:`TransactionOutboxService` — inbound requests, idempotent on ``request_id``.

Validation happens here, before any SQL, so a bad record fails the business
transaction with a clear :class:`OutboxError` instead of a CHECK violation.
With the ``notify`` strategy every write ``NOTIFY``s the relay on commit.
"""

from __future__ import annotations

from typing import Any

from foundation.messaging.types import BaseEvent
from foundation.resiliant.outbox import (
    IOutboxService,
    ITransactionOutboxService,
    OutboxConfig,
    OutboxError,
    OutboxTarget,
)
from foundation.utils.id import generate_id
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models.outbox import (
    MessagingOutboxTable,
    OutboxRecordMixin,
    TransactionOutboxTable,
)

from .outbox_repository import OutboxRepository
from .registry import OutboxDefinition


class OutboxService:
    """Generic outbox writer: ``enqueue`` works for any registered outbox table."""

    def __init__(
        self,
        definition: OutboxDefinition,
        config: OutboxConfig,
        *,
        target: OutboxTarget | str | None = None,
        repository: OutboxRepository[Any] | None = None,
    ) -> None:
        self.definition = definition
        self.config = config
        self.target = target or definition.default_target
        self.repository = repository or OutboxRepository(definition.model, config)

    @property
    def notify_channel(self) -> str | None:
        return (
            self.config.notify_channel
            if self.config.poll_strategy == 'notify'
            else None
        )

    def common_values(
        self, *, event_type: str, payload: Any, max_retries: int | None, **values: Any
    ) -> dict[str, Any]:
        if not event_type:
            raise OutboxError('an outbox record needs an event_type')
        if not isinstance(payload, dict):
            raise OutboxError(
                f'outbox record {event_type}: payload must be a JSON object'
            )
        retries = max_retries if max_retries is not None else self.config.max_retries
        if not isinstance(retries, int) or retries < 1:
            raise OutboxError(
                f'outbox record {event_type}: max_retries must be >= 1, got {retries}'
            )
        return {
            'event_type': event_type,
            'target': values.pop('target', None) or self.target,
            'channel': values.pop('channel', None),
            'ordering_key': values.pop('ordering_key', None),
            'payload': payload,
            'headers': values.pop('headers', None) or None,
            'correlation_id': values.pop('correlation_id', None),
            'max_retries': retries,
            **values,
        }

    async def enqueue_many(
        self, session: AsyncSession, records: list[dict[str, Any]]
    ) -> int:
        """Append records (each: common fields + the table's own columns); returns how many were new."""
        values = [self.common_values(**dict(record)) for record in records]
        return await self.repository.append(session, values, self.notify_channel)

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        payload: dict[str, Any],
        channel: str | None = None,
        target: OutboxTarget | str | None = None,
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        max_retries: int | None = None,
        **columns: Any,
    ) -> OutboxRecordMixin | None:
        """Append one record; returns it, or ``None`` when a unique key already holds it."""
        value = self.common_values(
            event_type=event_type,
            payload=payload,
            max_retries=max_retries,
            channel=channel,
            target=target,
            ordering_key=ordering_key,
            headers=headers,
            correlation_id=correlation_id,
            **columns,
        )
        return await self.repository.insert_returning(
            session, value, self.notify_channel
        )

    async def get_stats(
        self, session: AsyncSession, *, exact_published: bool = False
    ) -> dict[str, Any]:
        """``{outbox, table, counts, oldest_pending_age_ms}`` of this outbox."""
        stats = await self.repository.stats(session, exact_published=exact_published)
        return {
            'outbox': self.definition.name,
            'table': self.repository.table_name,
            **stats,
        }


class MessagingOutboxService(OutboxService, IOutboxService):
    """Messaging outbox (``resiliant_outbox_messages``): domain events for the broker."""

    async def save_event(
        self,
        session: AsyncSession,
        event: BaseEvent,
        channel: str,
        *,
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
        correlation_id: str | None = None,
    ) -> MessagingOutboxTable | None:
        """A domain event: its envelope (``as_dict()``) is the payload, its ``event_id`` the dedup key.

        Returns the new record, ``None`` when this event id was already appended.
        """
        if not event.event_id:
            raise OutboxError(
                f'messaging outbox record {event.event_type}: event_id is required'
            )
        if not channel:
            raise OutboxError(
                f'messaging outbox record {event.event_type}: channel is required'
            )
        return await self.enqueue(  # type: ignore[return-value]
            session,
            event_type=event.event_type or type(event).__name__,
            payload=event.as_dict(),
            channel=channel,
            ordering_key=ordering_key,
            headers=headers,
            correlation_id=correlation_id or getattr(event, 'correlation_id', None),
            max_retries=max_retries,
            event_id=str(event.event_id),
            source_service=getattr(event, 'source', None),
            user_id=getattr(event, 'user_id', None)
            or getattr(event, 'user_uuid', None),
        )

    async def save_raw_message(
        self,
        session: AsyncSession,
        *,
        channel: str,
        payload: dict[str, Any],
        event_type: str,
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        max_retries: int | None = None,
        event_id: str | None = None,
    ) -> MessagingOutboxTable | None:
        """An already-serialised message; a fresh event id unless given (so NOT idempotent by default)."""
        if not channel:
            raise OutboxError(
                f'messaging outbox record {event_type}: channel is required'
            )
        return await self.enqueue(  # type: ignore[return-value]
            session,
            event_type=event_type,
            payload=payload,
            channel=channel,
            ordering_key=ordering_key,
            headers=headers,
            max_retries=max_retries,
            event_id=event_id or generate_id(),
        )


class TransactionOutboxService(OutboxService, ITransactionOutboxService):
    """Transaction outbox (``resiliant_outbox_transactions``): inbound requests relayed to the target."""

    async def save_transaction(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        transaction_type: str,
        payload: dict[str, Any],
        channel: str | None = None,
        ordering_key: str | None = None,
        account_ref: str | None = None,
        source_system: str | None = None,
        headers: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        max_retries: int | None = None,
    ) -> TransactionOutboxTable:
        """Record a request; a repeated ``request_id`` (retry, concurrent duplicate) returns the stored record.

        The unique key settles races (``ON CONFLICT DO NOTHING``), so no savepoint is needed.
        ``ordering_key`` defaults to ``account_ref`` so one account's requests stay ordered.
        """
        if not request_id:
            raise OutboxError('a transaction request needs a request_id')
        inserted = await self.enqueue(
            session,
            event_type=transaction_type,
            payload=payload,
            channel=channel,
            ordering_key=ordering_key or account_ref,
            headers=headers,
            correlation_id=correlation_id,
            max_retries=max_retries,
            request_id=request_id,
            account_ref=account_ref,
            source_system=source_system,
        )
        if inserted is not None:
            return inserted  # type: ignore[return-value]
        existing = await self.repository.find_by(session, 'request_id', request_id)
        if existing is None:
            raise OutboxError(
                f'transaction request {request_id} was rejected by a unique constraint'
            )
        return existing  # type: ignore[return-value]


__all__ = ['MessagingOutboxService', 'OutboxService', 'TransactionOutboxService']
