from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import (
    PROJECTS_TABLE,
    PROJECTS_WORKFLOWS_ASSIGNMENTS_TABLE,
    WORKFLOWS_TABLE,
)

if TYPE_CHECKING:
    from ._project import Project
    from ._workflow import Workflow


class ProjectWorkflowAssignment(UUIDv7Base, SoftDeleteColumns):
    """Project Workflow Assignment.

    Manages workflow assignments to projects and teams. This enables flexible
    workflow assignment where:
    - A project can have one workflow for all users (team_id = None)
    - A project can have multiple teams with different workflows (team_id set)
    """

    __tablename__ = PROJECTS_WORKFLOWS_ASSIGNMENTS_TABLE

    project_id: Mapped[ID_COLUMN_TYPE] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=False
    )
    workflow_id: Mapped[ID_COLUMN_TYPE] = mapped_column(
        ForeignKey(f'{WORKFLOWS_TABLE}.id'), nullable=False
    )

    team_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    assigned_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    assigned_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('100')
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text('true')
    )

    effective_from: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    effective_until: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )

    project: Mapped[Optional['Project']] = relationship(foreign_keys=[project_id])
    workflow: Mapped[Optional['Workflow']] = relationship(foreign_keys=[workflow_id])
