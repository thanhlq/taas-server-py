"""
Outbox tables — one per use case, sharing the columns of :class:`OutboxRecordMixin`.

The generic relay (``resiliant.outbox``: repository, poller, dispatchers) only
touches the mixin columns (the ``IOutboxRecord`` contract in
``foundation.resiliant.outbox``), so each use case can shape its own table:

* :class:`MessagingOutboxTable`   — domain events for the broker.
* :class:`TransactionOutboxTable` — inbound transaction requests, idempotent on
  ``request_id``.

To add a use case: subclass ``OutboxRecordMixin, UUIDv7AuditBase`` with its own
``__tablename__`` / columns, then register it (``resiliant.outbox.registry``).

The outbox relies on explicit status transitions / hard deletion rather than
soft deletion, so no ``deleted_at`` column is used.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from advanced_alchemy.base import UUIDv7AuditBase
from advanced_alchemy.types import DateTimeUTC
from foundation.resiliant.outbox import OutboxStatus, OutboxTarget
from sqlalchemy import JSON, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, synonym

from resiliant.models.config import RESILIANT_TABLE_PREFIX

# Shared Postgres enum types (one type, used by every outbox table).
OUTBOX_STATUS_ENUM = Enum(OutboxStatus, name='outboxstatus')
OUTBOX_TARGET_ENUM = Enum(OutboxTarget, name='outboxtarget')


class OutboxRecordMixin:
    """Columns every outbox table has — what the generic relay reads and updates."""

    event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    """Kind of record (event class name, transaction type, …) — for logs and routing."""

    target: Mapped[OutboxTarget] = mapped_column(
        OUTBOX_TARGET_ENUM, nullable=False, default=OutboxTarget.MESSAGING
    )
    """Where the relay delivers the record (selects the dispatcher)."""

    channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """Destination on the target, e.g. the Kafka topic for ``MESSAGING``."""

    ordering_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    """Optional partition / ordering key (e.g. user id, account id)."""

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    headers: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, default=dict)

    status: Mapped[OutboxStatus] = mapped_column(
        OUTBOX_STATUS_ENUM, nullable=False, default=OutboxStatus.PENDING, index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    """Earliest time a failed record may be retried (exponential backoff); ``None`` = now."""

    processed_at: Mapped[datetime | None] = mapped_column(DateTimeUTC(timezone=True), nullable=True)
    """When the record was delivered."""

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    @declared_attr.directive
    @classmethod
    def __table_args__(cls) -> tuple[Any, ...]:
        # Index names include the table name so every outbox table gets its own.
        name = cls.__tablename__  # type: ignore[attr-defined]
        return (
            # Polling: pending records oldest first, under the retry cap.
            Index(f'ix_{name}_status_retry', 'status', 'retry_count', 'created_at'),
            # Stale-processing recovery, stats and cleanup.
            Index(f'ix_{name}_status_created', 'status', 'created_at'),
        )

    def as_dict(self) -> dict[str, Any]:
        """Every column as a JSON-friendly dict (timestamps as ISO strings)."""
        result: dict[str, Any] = {}
        for column in self.__table__.columns:  # type: ignore[attr-defined]
            value = getattr(self, column.key)
            result[column.key] = value.isoformat() if isinstance(value, datetime) else value
        return result


class MessagingOutboxTable(OutboxRecordMixin, UUIDv7AuditBase):
    """Messaging outbox: domain events written with the business transaction,
    published to the broker by the relay (``OutboxName.MESSAGING``)."""

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}outbox_messages'

    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_service: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TransactionOutboxTable(OutboxRecordMixin, UUIDv7AuditBase):
    """Transaction outbox: inbound transaction requests (deposits, transfers, …)
    accepted with the business transaction and relayed to their ``target``
    (``OutboxName.TRANSACTION``).

    ``request_id`` is the caller's idempotency key (unique); ``event_type``
    holds the transaction type (also exposed as ``transaction_type``).
    """

    __tablename__ = f'{RESILIANT_TABLE_PREFIX}outbox_transactions'

    request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    account_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    """Account / wallet the request applies to (also a natural ordering key)."""
    source_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """System that submitted the request (API client, partner, …)."""

    transaction_type = synonym('event_type')


__all__ = [
    'MessagingOutboxTable',
    'OUTBOX_STATUS_ENUM',
    'OUTBOX_TARGET_ENUM',
    'OutboxRecordMixin',
    'TransactionOutboxTable',
]
