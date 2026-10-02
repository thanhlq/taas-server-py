"""
Processed events — the Postgres idempotency store (same table as ``@taas/resiliant``).

One row per ``idempotency_key`` = ``"<handler_name>:<event_id>"``: the same event
can be handled by several handlers without false duplicates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Text, text
from sqlalchemy.orm import Mapped, mapped_column

from resiliant.models.base import (
    Jsonb,
    ResiliantBase,
    bigint_identity_pk,
    created_at_column,
)
from resiliant.models.config import RESILIANT_TABLE_PREFIX


class ProcessedEventTable(ResiliantBase):
    __tablename__ = f'{RESILIANT_TABLE_PREFIX}processed_events'

    id: Mapped[int] = bigint_identity_pk()
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    """``<handler>:<event_id>`` (≤ 512 chars) — the only column the hot path touches."""
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(
        Text, nullable=False, default='', server_default=text("''")
    )
    handler_name: Mapped[str] = mapped_column(Text, nullable=False)
    saga_id: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    # `metadata` is reserved by SQLAlchemy's declarative API: mapped as `extra_metadata`.
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column('metadata', Jsonb)
    created_at: Mapped[datetime] = created_at_column()

    def __repr__(self) -> str:
        return f'<ProcessedEventTable key={self.idempotency_key!r} handler={self.handler_name!r}>'


__all__ = ['ProcessedEventTable']
