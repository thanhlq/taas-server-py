"""Request/response schemas for the Task API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from foundation.serialization import ApiRequest, ApiResponse

# Fields a PATCH may reset to null through ``clear`` (``None`` means "unchanged").
TASK_CLEARABLE_FIELDS = frozenset(
    {
        'description',
        'description_html',
        'user_id',
        'task_list_id',
        'iteration_id',
        'start_date',
        'due_date',
        'estimated_minutes',
    }
)


class TaskCreateRequest(ApiRequest):
    """Create a task inside a project (optionally in a specific stage/column or task list)."""

    project_id: str
    name: str
    description: Optional[str] = None
    description_html: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    parent_id: Optional[str] = None
    requested_user_id: Optional[str] = None
    progress: Optional[int] = None
    # Single assignee (id / email until IAM users exist).
    user_id: Optional[str] = None
    task_list_id: Optional[str] = None
    iteration_id: Optional[str] = None
    labels: Optional[list[str]] = None
    priority: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None


class TaskUpdateRequest(ApiRequest):
    """Partial update — quick view, full editor and drag-and-drop moves.

    Omitted (null) fields are unchanged; list a field in ``clear`` to reset it
    (see ``TASK_CLEARABLE_FIELDS``).
    """

    name: Optional[str] = None
    description: Optional[str] = None
    # Rich text (HTML) of the description; ``description`` keeps its plain text.
    description_html: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    progress: Optional[int] = None
    requested_user_id: Optional[str] = None
    user_id: Optional[str] = None
    task_list_id: Optional[str] = None
    iteration_id: Optional[str] = None
    labels: Optional[list[str]] = None
    priority: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None
    # Users watching (following) the task.
    watchers: Optional[list[str]] = None
    clear: Optional[list[str]] = None


class TaskResponse(ApiResponse):
    id: str
    project_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    description_html: Optional[str] = None
    # Human key, ``<project code>-<sequence>`` (e.g. ``TT-67``).
    code: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    parent_id: Optional[str] = None
    requested_user_id: Optional[str] = None
    user_id: Optional[str] = None
    task_list_id: Optional[str] = None
    iteration_id: Optional[str] = None
    labels: Optional[list[str]] = None
    watchers: Optional[list[str]] = None
    # 0 (none) → 5 (immediately).
    priority: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None
    # Sum of the task's time logs.
    actual_minutes: Optional[int] = None
    progress: Optional[int] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TaskListCreateRequest(ApiRequest):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[float] = None


class TaskListUpdateRequest(ApiRequest):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[float] = None


class TaskListResponse(ApiResponse):
    id: str
    project_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[float] = None


class IterationCreateRequest(ApiRequest):
    name: str
    goal: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None


class IterationUpdateRequest(ApiRequest):
    name: Optional[str] = None
    goal: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None


class IterationResponse(ApiResponse):
    id: str
    project_id: Optional[str] = None
    name: Optional[str] = None
    goal: Optional[str] = None
    # planned | active | completed
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None


class TaskCommentCreateRequest(ApiRequest):
    text: str
    # Author (id / email until IAM users exist).
    user_id: Optional[str] = None


class TaskCommentResponse(ApiResponse):
    id: str
    task_id: str
    user_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None


class TimelogCreateRequest(ApiRequest):
    """A time log on a task; ``minutes`` wins over ``start_time``/``end_time``."""

    user_id: Optional[str] = None
    log_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    minutes: Optional[int] = None
    is_billable: Optional[bool] = None
    description: Optional[str] = None


class TimelogResponse(ApiResponse):
    id: str
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    log_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    minutes: Optional[int] = None
    is_billable: Optional[bool] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
