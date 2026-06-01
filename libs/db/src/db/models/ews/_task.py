from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import (
    PROJECTS_TABLE,
    TASKS_TABLE,
    WORKFLOWS_STAGES_TABLE,
    WORKFLOWS_TABLE,
)

if TYPE_CHECKING:
    from ._project import Project
    from ._timelog import Timelog
    from ._workflow import Workflow
    from ._workflow_stage import WorkflowStage


class Task(UUIDv7Base, SoftDeleteColumns):
    """Task"""

    __tablename__ = TASKS_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'::character")
    )
    html_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    sequence_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )
    progress: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )

    requested_user_id: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, index=True
    )

    workflow_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{WORKFLOWS_TABLE}.id'), nullable=True, index=True
    )
    stage_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{WORKFLOWS_STAGES_TABLE}.id'), nullable=True, index=True
    )
    stage_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    work_item_type_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    work_item_type_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    work_item_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True, index=True
    )
    completed_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True, index=True
    )
    milestone_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    is_recurrence: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, index=True
    )
    recurrence_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    ancestor_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    parent_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True, index=True
    )

    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )
    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 6), nullable=True
    )
    estimated_cost_currency: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    sale_order_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    contact_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    privacy: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    checklists: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    attachments: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    assignees: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    followers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    analytics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    priority: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('1')
    )
    start_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True, index=True
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True, index=True
    )

    starred: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    pinned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    starred_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    display_order: Mapped[Optional[float]] = mapped_column(
        Float(precision=6), nullable=True, server_default=text('-1')
    )
    position: Mapped[Optional[float]] = mapped_column(
        Float(precision=6), nullable=True, server_default=text('-1')
    )

    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    icon_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    time_expense_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    timelog_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    cost_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    sms_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    mail_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    project: Mapped[Optional['Project']] = relationship(
        back_populates='tasks', foreign_keys=[project_id]
    )
    parent_task: Mapped[Optional['Task']] = relationship(
        remote_side='Task.id', foreign_keys=[parent_id]
    )
    workflow: Mapped[Optional['Workflow']] = relationship(foreign_keys=[workflow_id])
    stage: Mapped[Optional['WorkflowStage']] = relationship(foreign_keys=[stage_id])
    timelogs: Mapped[list['Timelog']] = relationship(
        back_populates='task', foreign_keys='Timelog.task_id'
    )
