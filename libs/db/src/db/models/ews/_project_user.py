from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Boolean, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import PROJECTS_TABLE, PROJECTS_USERS_TABLE

if TYPE_CHECKING:
    from ._project import Project


class ProjectUser(UUIDv7Base, SoftDeleteColumns):
    """Project Users"""

    __tablename__ = PROJECTS_USERS_TABLE

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    starred: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    starred_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    pinned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    is_observing: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    email_notification_enabled: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    permissions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    project: Mapped[Optional['Project']] = relationship(
        back_populates='users', foreign_keys=[project_id]
    )
