from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from ..types import JSONB, PROJECTS_TABLE, PROJECTS_TEAMS_TABLE

if TYPE_CHECKING:
    from ._project import Project


class ProjectTeam(UUIDv7Base, SoftDeleteColumns):
    """Project Team.

    Enhanced project-team relationship supporting workflow assignments. Manages
    which teams are assigned to which projects and their roles.
    """

    __tablename__ = PROJECTS_TEAMS_TABLE

    project_id: Mapped[ID_COLUMN_TYPE] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=False, index=True
    )
    team_id: Mapped[str] = mapped_column(TEXT, nullable=False, index=True)

    team_role: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('true')
    )
    joined_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    permissions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )

    project: Mapped[Optional['Project']] = relationship(foreign_keys=[project_id])
