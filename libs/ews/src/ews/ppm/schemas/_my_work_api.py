"""Wire types of ``/api/v1/ppm/my-work`` (taas-specs/ppm/my-work/my-work-spec.md §7)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import msgspec
from foundation.serialization import ApiRequest, ApiResponse


class PpmMyWorkProjectRef(ApiResponse, kw_only=True):
    id: str
    name: str | None = None
    color: str | None = None
    kind: str = 'project'


class PpmMyWorkStageRef(ApiResponse, kw_only=True):
    id: str
    name: str | None = None
    stage_type: str | None = None


class PpmMyWorkCount(ApiResponse, kw_only=True):
    done: int = 0
    total: int = 0


class PpmMyWorkEntryOut(ApiResponse, kw_only=True):
    source_type: str
    """``task`` · ``checklist_item`` · ``mention``."""
    source_id: str
    task_id: str
    code: str | None = None
    name: str
    """The item's name (checklist step: the step's text; ``task_name`` = its item)."""
    task_name: str | None = None
    project: PpmMyWorkProjectRef
    item_type: str | None = None
    priority: int = 0
    stage: PpmMyWorkStageRef | None = None
    start_date: datetime | None = None
    due_date: date | None = None
    planned_date: date | None = None
    snoozed_until: datetime | None = None
    bucket: str
    overdue_reason: str | None = None
    """``due`` (red) · ``plan`` (only my planned date passed, amber)."""
    sort_key: float | None = None
    role: str | None = None
    """``owner`` · ``collaborator`` (assigned items)."""
    subtasks: PpmMyWorkCount | None = None
    checklist: PpmMyWorkCount | None = None
    remaining_minutes: int | None = None
    excerpt: str | None = None
    actor_name: str | None = None
    workflow_id: str | None = None


class PpmMyWorkDoneOut(ApiResponse, kw_only=True):
    task_id: str
    code: str | None = None
    name: str | None = None
    project_name: str | None = None
    completed_at: datetime | None = None


class PpmMyWorkOut(ApiResponse, kw_only=True):
    entries: list[PpmMyWorkEntryOut] = msgspec.field(default_factory=list)
    counts: dict[str, int] = msgspec.field(default_factory=dict)
    """Per bucket (``overdue`` · ``today`` · ``tomorrow`` · ``this_week`` · ``later`` · ``no_date``), complete even
    when ``entries`` is cut at 500."""
    today: date
    week_end: date
    inbox_project_id: str | None = None
    done_today: list[PpmMyWorkDoneOut] = msgspec.field(default_factory=list)
    settings: dict[str, Any] = msgspec.field(default_factory=dict)
    planned_minutes_today: int = 0
    """Σ remaining effort of Today's items (capacity bar, Ppm-0931)."""


class PpmMyWorkCountsOut(ApiResponse, kw_only=True):
    counts: dict[str, int] = msgspec.field(default_factory=dict)
    badge: int = 0
    """Overdue + Today (sidebar badge, Ppm-0901)."""


class PpmMyWorkPlanIn(ApiRequest, kw_only=True):
    planned_date: date | None = None
    sort_key: float | None = None
    snoozed_until: datetime | None = None


class PpmMyWorkRef(ApiRequest, kw_only=True):
    source_type: str
    source_id: str


class PpmMyWorkRescheduleIn(ApiRequest, kw_only=True):
    planned_date: date
    refs: list[PpmMyWorkRef] | None = None
    """``None`` = every overdue entry."""


class PpmQuickAddIn(ApiRequest, kw_only=True):
    name: str
    project_id: str | None = None
    """``None`` = my Inbox (created on first use)."""
    planned_date: date | None = None
    due_date: datetime | None = None
    priority: int | None = None
