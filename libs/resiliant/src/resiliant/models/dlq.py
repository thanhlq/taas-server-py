"""
Dead-letter queue tables (same as ``@taas/resiliant``): live dead letters and their archive.

Statuses (``DLQStatus``): ``pending`` → ``approved`` → ``processing`` → ``resolved``;
``cancelled`` / ``abandoned`` are terminal. Terminal rows move to the archive table
(same columns + ``archived_at``, same id).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from foundation.resiliant.dlq import DLQStatus
from sqlalchemy import BigInteger, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

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


class DLQEventColumnsMixin:
    """Columns shared by the live and the archive table."""

    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    handler_name: Mapped[str] = mapped_column(Text, nullable=False)
    """Handler that failed — the retry invokes it again."""
    source_destination: Mapped[str | None] = mapped_column(Text)
    source_service: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(Jsonb, nullable=False)
    headers: Mapped[dict[str, Any] | None] = mapped_column(Jsonb)
    status: Mapped[DLQStatus] = mapped_column(
        EnumText(DLQStatus),
        nullable=False,
        default=DLQStatus.PENDING,
        server_default=text("'pending'"),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text('0')
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default=text('3')
    )
    original_error: Mapped[str] = mapped_column(Text, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    failed_at: Mapped[datetime] = mapped_column(Timestamptz, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(Timestamptz)
    next_attempt_at: Mapped[datetime | None] = mapped_column(Timestamptz)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class DLQEventTable(DLQEventColumnsMixin, ResiliantBase):
    __tablename__ = f'{RESILIANT_TABLE_PREFIX}dlq_events'

    id: Mapped[int] = bigint_identity_pk()

    def __repr__(self) -> str:
        return f'<DLQEvent(id={self.id}, event_type={self.event_type}, handler={self.handler_name}, status={self.status})>'


class DLQEventArchiveTable(DLQEventColumnsMixin, ResiliantBase):
    __tablename__ = f'{RESILIANT_TABLE_PREFIX}dlq_events_archive'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    """Same id as the live row it was moved from."""
    archived_at: Mapped[datetime] = mapped_column(
        Timestamptz, nullable=False, server_default=func.now()
    )


__all__ = ['DLQEventArchiveTable', 'DLQEventColumnsMixin', 'DLQEventTable']
