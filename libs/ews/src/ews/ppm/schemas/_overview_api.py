"""Wire types of the server-side PPM figures (ADR-27): ``/api/v1/ppm/overview``, ``/api/v1/projects/{id}/metrics``."""

from __future__ import annotations

import msgspec
from foundation.serialization import ApiResponse

from ._project_api import ProjectListItem
from ._task_api import TaskResponse


class PpmStatusCount(ApiResponse, kw_only=True):
    value: str
    color: str
    group: str
    count: int


class PpmOverviewOut(ApiResponse, kw_only=True):
    total: int = 0
    statuses: list[PpmStatusCount] = msgspec.field(default_factory=list)
    """Statuses in use, most frequent first (tiles show the first three, Ppm-0003)."""
    recent: list[ProjectListItem] = msgspec.field(default_factory=list)
    # Ppm-1901 tiles: open projects (status not closed), at risk (health 🔴, else risk statuses), my overdue items,
    # my items due within 7 days.
    open: int = 0
    at_risk: int = 0
    my_overdue: int = 0
    my_due_week: int = 0


class PpmScheduleHealth(ApiResponse, kw_only=True):
    health: str
    """``unscheduled`` · ``notStarted`` · ``onTrack`` · ``atRisk`` · ``overdue`` · ``completed``."""
    elapsed: int | None = None
    days_left: int | None = None


class PpmPersonWorkload(ApiResponse, kw_only=True):
    user: str | None = None
    open: int = 0
    overdue: int = 0
    done: int = 0
    total: int = 0


class PpmProjectMetricsOut(ApiResponse, kw_only=True):
    total: int = 0
    done: int = 0
    open: int = 0
    overdue: int = 0
    due_soon: int = 0
    progress: int = 0
    bands: dict[str, int] = msgspec.field(default_factory=dict)
    overdue_tasks: list[TaskResponse] = msgspec.field(default_factory=list)
    upcoming_tasks: list[TaskResponse] = msgspec.field(default_factory=list)
    people: list[PpmPersonWorkload] = msgspec.field(default_factory=list)
    schedule: PpmScheduleHealth
