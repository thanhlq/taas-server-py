from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from advanced_alchemy.base import UUIDv7Base
from advanced_alchemy.types import GUID
from sqlalchemy import (
    TEXT,
    TIMESTAMP,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, TENANT_ID_COLUMN_TYPE, SoftDeleteColumns
from .constants import PROJECTS_TABLE

if TYPE_CHECKING:
    from ._project_user import ProjectUser
    from ._task import Task
    from ._timelog import Timelog
    from ._workflow import Workflow


class Project(UUIDv7Base, SoftDeleteColumns):
    """Project"""

    __tablename__ = PROJECTS_TABLE

    org_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    """Legacy, unused: the organization is ``organization_id``."""
    tenant_id: Mapped[TENANT_ID_COLUMN_TYPE | None] = mapped_column(
        GUID(length=16), index=True, nullable=True, default=None
    )
    organization_id: Mapped[TENANT_ID_COLUMN_TYPE | None] = mapped_column(
        GUID(length=16), index=True, nullable=True, default=None
    )
    """Organization of the project (``taas_organizations.id``); every request is scoped to it (Ppm-0001)."""

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    code: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'")
    )
    html_text: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    start_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True, index=True
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True, index=True
    )

    engagement_type_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'New'"), index=True
    )
    status_updated_time: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    status_updated_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    auto_archived: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True, index=True
    )

    privacy: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    parent_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_TABLE}.id'), nullable=True
    )
    program_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    team_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)

    properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    workflow: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    analytics: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    checklists: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)

    last_activity_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    starred: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    pinned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    starred_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    display_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    default_view: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    kind: Mapped[str] = mapped_column(
        TEXT, nullable=False, server_default=text("'project'"), index=True
    )
    """``project`` · ``template`` (ADR-30, Ppm-0880) · ``personal`` (the owner's Inbox, ADR-29); lists show projects only."""
    schedule_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    """Concurrency counter of the schedule (Ppm-1064), + 1 on each recalculation."""
    created_from_template_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    wiki_start_page_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    color: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    icon_name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    budget: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 7), nullable=True, server_default=text('0')
    )
    budget_currency_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    budget_privacy: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    estimated_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    spent_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    estimated_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    spent_cost: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2), nullable=True)
    estimated_cost_currency: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    estimated_expense: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    estimated_expense_currency: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True
    )
    total_contract_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    total_contract_value_currency: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True
    )

    cost_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    billing_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    billing_rate_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    time_and_expense_to_bill: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    invoice_currency_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    sms_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    mail_template_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)

    parent_project: Mapped[Optional['Project']] = relationship(
        remote_side='Project.id', foreign_keys=[parent_id]
    )
    tasks: Mapped[list['Task']] = relationship(
        back_populates='project', foreign_keys='Task.project_id'
    )
    workflows: Mapped[list['Workflow']] = relationship(
        back_populates='project', foreign_keys='Workflow.project_id'
    )
    timelogs: Mapped[list['Timelog']] = relationship(
        back_populates='project', foreign_keys='Timelog.project_id'
    )
    users: Mapped[list['ProjectUser']] = relationship(
        back_populates='project',
        foreign_keys='ProjectUser.project_id',
        cascade='all, delete-orphan',
    )
