from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7AuditBase
from sqlalchemy import TEXT, Boolean, ForeignKey, Integer, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB
from .constants import PROJECTS_TABLE, WORKFLOWS_TABLE

if TYPE_CHECKING:
    from ._project import Project
    from ._workflow_stage import WorkflowStage


class Workflow(UUIDv7AuditBase):
    """Project Workflow"""

    __tablename__ = WORKFLOWS_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'::character")
    )
    html_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    workflow_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'kanban'::character")
    )
    scope: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'project'::character")
    )

    project_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True, index=True
    )
    team_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    allowed_stage_types: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('true')
    )
    is_default: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )
    is_template: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, server_default=text('false')
    )

    privacy: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'project'::character")
    )

    allowed_work_item_types: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    work_item_types: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    work_items: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    display_order: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )

    sms_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    mail_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    project: Mapped[Optional['Project']] = relationship(
        back_populates='workflows', foreign_keys=[project_id]
    )
    stages: Mapped[list['WorkflowStage']] = relationship(
        back_populates='workflow', foreign_keys='WorkflowStage.workflow_id'
    )
