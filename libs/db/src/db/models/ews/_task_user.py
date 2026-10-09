from __future__ import annotations

from datetime import datetime
from typing import Optional

from advanced_alchemy.base import UUIDv7Base
from advanced_alchemy.types import GUID, DateTimeUTC
from sqlalchemy import TEXT, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import TASKS_TABLE, TASKS_USERS_TABLE


class TaskUser(UUIDv7Base, SoftDeleteColumns):
    """Task-User relationship"""

    __tablename__ = TASKS_USERS_TABLE
    __table_args__ = (
        Index('ix_taas_tasks_users_user', 'user_id', 'task_id'),
        Index(
            'ux_taas_tasks_users_live',
            'task_id',
            'user_id',
            unique=True,
            postgresql_where=text('deleted_at IS NULL'),
        ),
    )

    organization_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    task_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    """Assignee (IAM user id or e-mail, ADR-12)."""
    tenant_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    role: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'collaborator'")
    )
    """``owner`` (≤ 1, mirrored in ``taas_tasks.user_id``) · ``collaborator`` — Ppm-0825."""
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTimeUTC(timezone=True), nullable=True, server_default=text('now()')
    )
    created_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
