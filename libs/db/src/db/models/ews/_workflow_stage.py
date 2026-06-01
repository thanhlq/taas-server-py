from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from sqlalchemy import TEXT, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import (
    PROJECTS_TABLE,
    WORKFLOWS_STAGES_TABLE,
    WORKFLOWS_TABLE,
)

if TYPE_CHECKING:
    from ._project_workflow_stage_item import ProjectWorkflowStageItem
    from ._workflow import Workflow


class WorkflowStage(UUIDv7Base, SoftDeleteColumns):
    """Project Workflow Stage"""

    __tablename__ = WORKFLOWS_STAGES_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    stage_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'active'::character")
    )

    workflow_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{WORKFLOWS_TABLE}.id'), nullable=True
    )
    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )

    owner_user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    default_assignee_ids: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    auto_assign: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    auto_move_criteria: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    allowed_next_stages: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    allowed_previous_stages: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )

    wip_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    require_assignee: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    require_due_date: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )

    enable_notifications: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    notification_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )
    position: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )

    sort_by: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'manual'::character")
    )
    sort_order: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'asc'::character")
    )
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    assignees_ids: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    next_stages: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    previous_stages: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    enabled: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    is_default: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )

    sms_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    mail_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    workflow: Mapped[Optional['Workflow']] = relationship(
        back_populates='stages', foreign_keys=[workflow_id]
    )
    stage_items: Mapped[list['ProjectWorkflowStageItem']] = relationship(
        back_populates='stage',
        foreign_keys='ProjectWorkflowStageItem.stage_id',
    )
