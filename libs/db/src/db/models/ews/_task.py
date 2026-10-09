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
    Float,
    ForeignKey,
    Integer,
    Numeric,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import ID_COLUMN_TYPE, JSONB, SoftDeleteColumns
from .constants import (
    PROJECTS_ITERATIONS_TABLE,
    PROJECTS_TABLE,
    TASKS_LISTS_TABLE,
    TASKS_TABLE,
    WORKFLOWS_STAGES_TABLE,
    WORKFLOWS_TABLE,
)

if TYPE_CHECKING:
    from ._project import Project
    from ._project_iteration import ProjectIteration
    from ._task_list import TaskList
    from ._timelog import Timelog
    from ._workflow import Workflow
    from ._workflow_stage import WorkflowStage


class Task(UUIDv7Base, SoftDeleteColumns):
    """Task"""

    __tablename__ = TASKS_TABLE

    name: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    description_doc: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    """The description as a site document (shared document editor: Visual · Markdown, ADR-35); ``description`` keeps its
    plain text, ``html_text`` its rich text for older readers and e-mails."""
    content_type: Mapped[Optional[str]] = mapped_column(
        TEXT, nullable=True, server_default=text("'md'")
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
    # The single assignee (id / email until IAM users exist).
    user_id: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    task_list_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_LISTS_TABLE}.id'), nullable=True, index=True
    )
    iteration_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{PROJECTS_ITERATIONS_TABLE}.id'), nullable=True, index=True
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
    tenant_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    """Tenant of the item's project (set on create, Ppm-0001)."""
    progress_mode: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    behaviour: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True, index=True)
    """Mirror of the item type's behaviour (Ppm-0803): ``task`` · ``milestone`` · ``deliverable`` · ``approval`` ·
    ``request`` · ``risk`` · ``issue`` · ``assumption`` · ``decision``; null = ``task``."""
    recurrence_rule: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    """RFC 5545 RRULE subset (Ppm-0890): ``FREQ``, ``INTERVAL``, ``BYDAY``, ``BYMONTHDAY``, ``COUNT``, ``UNTIL``."""
    created_from_template_item_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    # Schedule (schedule-spec §3): phase of a top-level item, duration in working days (null = from the dates),
    # per-item mode override, constraint, actual start.
    phase_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True, index=True
    )
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schedule_mode: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    constraint_type: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    constraint_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)
    """``manual`` · ``checklist``; ``None`` = automatic (from subtasks when it has some, else manual) — Ppm-0831."""
    child_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    done_child_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    checklist_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    checklist_done: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text('0')
    )
    rollup_start_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    rollup_due_date: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    previous_stage_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        GUID(length=16), nullable=True
    )
    """Stage before *complete*, where *reopen* returns (Ppm-0807)."""
    parent_id: Mapped[Optional[ID_COLUMN_TYPE]] = mapped_column(
        ForeignKey(f'{TASKS_TABLE}.id'), nullable=True, index=True
    )

    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default=text('0')
    )
    # Effort (taas-specs/ppm/time-expense/time-tracking-spec.md §3.2): manual remaining (null = auto), the actual at the
    # time it was typed (later entries reduce it), subtree sums, last variance alert band.
    remaining_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    remaining_base_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    remaining_set_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP, nullable=True
    )
    remaining_set_by: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
    rollup_estimated_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    rollup_actual_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rollup_remaining_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    variance_alert_level: Mapped[Optional[str]] = mapped_column(TEXT, nullable=True)
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
    task_list: Mapped[Optional['TaskList']] = relationship(foreign_keys=[task_list_id])
    iteration: Mapped[Optional['ProjectIteration']] = relationship(
        foreign_keys=[iteration_id]
    )
    timelogs: Mapped[list['Timelog']] = relationship(
        back_populates='task', foreign_keys='Timelog.task_id'
    )
