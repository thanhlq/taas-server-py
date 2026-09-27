"""
Outbox services — write records inside the caller's business transaction.

* :class:`OutboxService`            — generic ``enqueue`` for any registered outbox.
* :class:`MessagingOutboxService`   — ``IOutboxService``: domain events → broker.
* :class:`TransactionOutboxService` — ``ITransactionOutboxService``: transaction
  requests, idempotent on ``request_id``.

Each service is bound to an :class:`OutboxDefinition` (table model) and a default
:class:`OutboxTarget`; the relay (``OutboxPoller``) later delivers the ``PENDING``
records. Build them via ``ResiliantServiceFactory`` / ``resiliant.outbox.factory``.
"""

from __future__ import annotations

from typing import Any

from foundation import BaseService
from foundation.messaging.types import BaseEvent
from foundation.resiliant.outbox import (
    IOutboxService,
    ITransactionOutboxService,
    OutboxConfig,
    OutboxStatus,
    OutboxTarget,
)
from foundation.utils.id import generate_id
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models.outbox import MessagingOutboxTable, OutboxRecordMixin, TransactionOutboxTable

from .outbox_repository import OutboxRepository
from .registry import OutboxDefinition


class OutboxService(BaseService):
    """Generic outbox writer: ``enqueue`` works for any registered outbox table."""

    def __init__(
        self,
        definition: OutboxDefinition,
        config: OutboxConfig,
        *,
        target: OutboxTarget | None = None,
        repository: OutboxRepository[Any] | None = None,
    ) -> None:
        super().__init__()
        self.definition = definition
        self.config = config
        self.target = target or definition.default_target
        self.repository = repository or OutboxRepository(definition.model, config)

    async def enqueue(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        payload: dict[str, Any],
        channel: str | None = None,
        target: OutboxTarget | None = None,
        ordering_key: str | None = None,
        headers: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        max_retries: int | None = None,
        **columns: Any,
    ) -> OutboxRecordMixin:
        """Add a ``PENDING`` record to the business transaction (flushed, not committed).

        ``columns`` are the use-case specific columns of the outbox table.
        """
        # The concrete table (an OutboxRecordMixin subclass) takes its columns as kwargs.
        model: Any = self.definition.model
        record = model(
            event_type=event_type,
            target=target or self.target,
            channel=channel,
            ordering_key=ordering_key,
            payload=payload,
            headers=headers or {},
            correlation_id=correlation_id,
            status=OutboxStatus.PENDING,
            retry_count=0,
            max_retries=max_retries or self.config.max_retries,
            **columns,
        )
        saved = await self.repository.save(session, record)
        self.logger.debug(
            'Outbox %s: enqueued %s (id=%s, target=%s, channel=%s)',
            self.definition.name, event_type, saved.id, record.target, channel,  # type: ignore[attr-defined]
        )
        return saved

    async def get_stats(self, session: AsyncSession) -> dict[str, Any]:
        """Counters describing the current backlog of this outbox."""
        return await self.repository.get_stats(session)


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
    ) -> MessagingOutboxTable:
        """Persist a domain ``event`` for publication to ``channel`` within ``session``."""
        record = await self.enqueue(
            session,
            event_type=event.event_type or type(event).__name__,
            payload=event.as_dict(),
            channel=channel,
            ordering_key=ordering_key,
            headers=headers,
            correlation_id=getattr(event, 'correlation_id', None),
            max_retries=max_retries,
            event_id=event.event_id,
            source_service=getattr(event, 'source', None),
            user_id=getattr(event, 'user_id', None),
        )
        return record  # type: ignore[return-value]

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
    ) -> MessagingOutboxTable:
        """Persist an already-serialised message (no domain event object)."""
        record = await self.enqueue(
            session,
            event_type=event_type,
            payload=payload,
            channel=channel,
            ordering_key=ordering_key,
            headers=headers,
            max_retries=max_retries,
            event_id=generate_id(),
        )
        return record  # type: ignore[return-value]


class TransactionOutboxService(OutboxService, ITransactionOutboxService):
    """Transaction outbox (``resiliant_outbox_transactions``): inbound transaction
    requests relayed to the service's target."""

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
        """Persist a transaction request; a repeated ``request_id`` returns the existing record.

        ``ordering_key`` defaults to ``account_ref`` so one account's requests stay ordered.
        The unique ``request_id`` column settles concurrent duplicates: the insert runs
        in a savepoint, and the loser gets the winner's record.
        """
        existing = await self.repository.find_one(session, request_id=request_id)
        if existing is not None:
            self.logger.info('Transaction outbox: request %s already recorded (id=%s)', request_id, existing.id)  # type: ignore[attr-defined]
            return existing  # type: ignore[return-value]

        try:
            async with session.begin_nested():
                record = await self.enqueue(
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
        except IntegrityError:
            winner = await self.repository.find_one(session, request_id=request_id)
            if winner is None:
                raise
            return winner  # type: ignore[return-value]
        return record  # type: ignore[return-value]
