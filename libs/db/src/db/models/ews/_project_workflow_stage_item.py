from __future__ import annotations
from foundation.types.types import SimpleStatus

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, TIMESTAMP, Boolean, ForeignKey, Integer, text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, SoftDeleteColumns, ArchivedColumns
from .constants import (
    PROJECTS_TABLE,
    PROJECTS_WORKFLOWS_STAGES_ITEMS_TABLE,
    TASKS_TABLE,
    WORKFLOWS_STAGES_TABLE,
    WORKFLOWS_TABLE,
)

if TYPE_CHECKING:
    from ._task import Task
    from ._workflow_stage import WorkflowStage


class ProjectWorkflowStageItem(UUIDv7Base, SoftDeleteColumns, ArchivedColumns):
    """Project Workflow Stage Item (Task in Stage)"""

    __tablename__ = PROJECTS_WORKFLOWS_STAGES_ITEMS_TABLE

    workflow_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{WORKFLOWS_TABLE}.id'), nullable=True
    )
    stage_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{WORKFLOWS_STAGES_TABLE}.id'), nullable=True
    )
    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )
    task_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True
    )

    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text("'-1'::integer")
    )

    status: Mapped[SimpleStatus] = mapped_column(
        Enum(SimpleStatus), nullable=False, default=SimpleStatus.ACTIVE
    )

    stage: Mapped[Optional['WorkflowStage']] = relationship(
        back_populates='stage_items', foreign_keys=[stage_id]
    )
    task: Mapped[Optional['Task']] = relationship(foreign_keys=[task_id])
