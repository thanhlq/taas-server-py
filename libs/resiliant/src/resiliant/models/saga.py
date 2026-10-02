"""Saga state (same table as ``@taas/resiliant``): one row per saga instance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from foundation.resiliant.saga import SagaStatus
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from resiliant.models.base import (
    EnumText,
    Jsonb,
    ResiliantBase,
    Timestamptz,
    bigint_identity_pk,
)
from resiliant.models.config import RESILIANT_TABLE_PREFIX


class SagaStateTable(ResiliantBase):
    __tablename__ = f'{RESILIANT_TABLE_PREFIX}saga_state'

    id: Mapped[int] = bigint_identity_pk()
    saga_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    """Public id of the saga instance."""
    name: Mapped[str] = mapped_column(Text, nullable=False)
    saga_key: Mapped[str | None] = mapped_column(Text)
    """Business key: at most one saga per ``(name, saga_key)``."""
    status: Mapped[SagaStatus] = mapped_column(EnumText(SagaStatus), nullable=False)
    current_step: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(Jsonb, nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(Jsonb, nullable=False)
    """Step records ``{name, status, error?, ...}`` in execution order."""
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Timestamptz, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(Timestamptz, nullable=False)


__all__ = ['SagaStateTable']
