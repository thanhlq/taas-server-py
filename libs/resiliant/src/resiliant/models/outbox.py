"""
Outbox tables — one per use case, sharing the columns of :class:`OutboxRecordMixin`.

Same tables as ``@taas/resiliant`` (``createOutboxTable``): the Node and Python
relays can serve the same rows. The generic relay (``resiliant.outbox``) only
touches the mixin columns (``IOutboxRecord``), so each use case shapes its own table:

* :class:`MessagingOutboxTable`   — domain events for the broker, unique ``event_id``.
* :class:`TransactionOutboxTable` — inbound transaction requests, unique ``request_id``.

Statuses: ``pending`` → ``published`` | ``failed`` (backoff, retried) → ``dead_letter``.
There is no ``processing`` state: claims are row locks held by the relay's
transaction (``FOR UPDATE SKIP LOCKED``). To add a use case: subclass
``OutboxRecordMixin, ResiliantBase`` with its own table + a drizzle migration in
taas-server-js, then register it (``resiliant.outbox.registry``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from foundation.resiliant.outbox import OutboxStatus, OutboxTarget
from sqlalchemy import Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, synonym

from resiliant.models.base import (
    EnumText,
    Jsonb,
    ResiliantBase,
    Timestamptz,
    bigint_identity_pk,
    created_at_column,
    updated_at_column,
)
from resiliant.models.config import RESILIANT_TABLE_PREFIX

# Default ``max_retries`` of a row written without one (the services always set it).
DEFAULT_OUTBOX_MAX_RETRIES = 10


class OutboxRecordMixin:
    """Columns every outbox table has — what the generic relay reads and updates."""

    id: Mapped[int] = bigint_identity_pk()
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    """Kind of record (event type, transaction type, …) — for logs and routing."""
    target: Mapped[OutboxTarget] = mapped_column(
        EnumText(OutboxTarget),
        nullable=False,
        default=OutboxTarget.MESSAGING,
        server_default=text("'messaging'"),
    )
    """Where the relay delivers the record (selects the dispatcher)."""
    channel: Mapped[str | None] = mapped_column(Text)
    """Destination on the target, e.g. the Kafka topic for ``messaging``."""
    ordering_key: Mapped[str | None] = mapped_column(Text)
    """Records of one key are delivered in id order (per target + channel)."""
    payload: Mapped[dict[str, Any]] = mapped_column(Jsonb, nullable=False)
    headers: Mapped[dict[str, Any] | None] = mapped_column(Jsonb)
    status: Mapped[OutboxStatus] = mapped_column(
        EnumText(OutboxStatus),
        nullable=False,
        default=OutboxStatus.PENDING,
        server_default=text("'pending'"),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text('0')
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_OUTBOX_MAX_RETRIES,
        server_default=text(str(DEFAULT_OUTBOX_MAX_RETRIES)),
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamptz)
    """Earliest retry of a failed record (capped exponential backoff); ``None`` = now."""
    correlation_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    processed_at: Mapped[datetime | None] = mapped_column(Timestamptz)
    """When the record was delivered."""


class MessagingOutboxTable(OutboxRecordMixin, ResiliantBase):
    """Messaging outbox (``OutboxName.MESSAGING``): domain events, a re-append of an ``event_id`` is a no-op."""

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}outbox_messages'

    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(Text)
    source_service: Mapped[str | None] = mapped_column(Text)


class TransactionOutboxTable(OutboxRecordMixin, ResiliantBase):
    """Transaction outbox (``OutboxName.TRANSACTION``): inbound requests, idempotent on ``request_id``.

    ``event_type`` holds the transaction type (also exposed as ``transaction_type``).
    """

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}outbox_transactions'

    request_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    account_ref: Mapped[str | None] = mapped_column(Text)
    """Account / wallet the request applies to (also the default ordering key)."""
    source_system: Mapped[str | None] = mapped_column(Text)

    transaction_type = synonym('event_type')


__all__ = [
    'DEFAULT_OUTBOX_MAX_RETRIES',
    'MessagingOutboxTable',
    'OutboxRecordMixin',
    'TransactionOutboxTable',
]
