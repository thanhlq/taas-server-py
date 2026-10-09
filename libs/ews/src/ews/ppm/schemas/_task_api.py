"""Request/response schemas for the Task API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

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
        'parent_id',
        'progress_mode',
        'description_doc',
        'recurrence_rule',
        'phase_id',
        'duration_days',
        'schedule_mode',
        'constraint_type',
        'constraint_date',
        'remaining_minutes',
    }
)
PROGRESS_MODES = frozenset({'manual', 'checklist'})
"""``progress_mode`` values; ``None`` = automatic (from subtasks when there are some, Ppm-0831)."""


class TaskCreateRequest(ApiRequest):
    """Create a task inside a project (optionally in a specific stage/column or task list)."""

    project_id: str
    name: str
    description: Optional[str] = None
    description_html: Optional[str] = None
    # The description as a site document (shared editor, ADR-35); ``description`` / ``html`` derive from it.
    description_doc: Optional[dict[str, Any]] = None
    # Placement: a stage (id), else the first stage of ``stage_type`` in the
    # workflow (default: the project's default workflow), else its default stage.
    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None
    stage_type: Optional[str] = None
    work_item_type: Optional[str] = None
    parent_id: Optional[str] = None
    requested_user_id: Optional[str] = None
    progress: Optional[int] = None
    # Owner (id / email until IAM users exist) + collaborators (Ppm-0825).
    user_id: Optional[str] = None
    collaborator_ids: Optional[list[str]] = None
    task_list_id: Optional[str] = None
    iteration_id: Optional[str] = None
    labels: Optional[list[str]] = None
    priority: Optional[int] = None
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None
    progress_mode: Optional[str] = None
    # Custom field values ``{key: value}`` (work-model §3, Ppm-0850); defaults fill the gaps.
    custom_fields: Optional[dict[str, Any]] = None
    # Copy a checklist template into the new item (Ppm-0833); else the item type's default template.
    checklist_template_id: Optional[str] = None
    # RRULE subset (Ppm-0890), e.g. ``FREQ=WEEKLY;BYDAY=MO``.
    recurrence_rule: Optional[str] = None
    # Schedule (taas-specs/ppm/schedule): phase of a top-level item, working-day duration, ``auto`` / ``manual``
    # (null = the project's mode), constraint ``asap`` · ``snet`` · ``mso`` · ``fnlt`` + its date.
    phase_id: Optional[str] = None
    duration_days: Optional[int] = None
    schedule_mode: Optional[str] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[datetime] = None


class TaskUpdateRequest(ApiRequest):
    """Partial update — quick view, full editor and drag-and-drop moves.

    Omitted (null) fields are unchanged; list a field in ``clear`` to reset it
    (see ``TASK_CLEARABLE_FIELDS``).
    """

    name: Optional[str] = None
    description: Optional[str] = None
    # Rich text (HTML) of the description; ``description`` keeps its plain text.
    description_html: Optional[str] = None
    # The description as a site document (ADR-35): validated; its plain text replaces ``description``.
    description_doc: Optional[dict[str, Any]] = None
    # Move to another workflow (same stage type when possible) / stage.
    workflow_id: Optional[str] = None
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
    # Make it a subtask of another item of the project (Ppm-0816); ``clear: ["parent_id"]`` = top level.
    parent_id: Optional[str] = None
    # ``manual`` · ``checklist``; clear = automatic (Ppm-0831).
    progress_mode: Optional[str] = None
    # ``{key: value}``; ``null`` clears one value.
    custom_fields: Optional[dict[str, Any]] = None
    recurrence_rule: Optional[str] = None
    # Schedule (taas-specs/ppm/schedule): phase of a top-level item, working-day duration, ``auto`` / ``manual``
    # (null = the project's mode), constraint ``asap`` · ``snet`` · ``mso`` · ``fnlt`` + its date.
    phase_id: Optional[str] = None
    duration_days: Optional[int] = None
    schedule_mode: Optional[str] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[datetime] = None
    # Remaining effort typed by a person (manual, Ppm-1203); ``clear: ["remaining_minutes"]`` = back to auto.
    remaining_minutes: Optional[int] = None
    clear: Optional[list[str]] = None


class TaskMoveRequest(ApiRequest):
    """Move an item with its subtree to another project of the organization (Ppm-0808)."""

    project_id: str


class TaskAssigneesRequest(ApiRequest):
    """Replace the owner and the collaborators of an item (Ppm-0825); ``owner_id`` null = no owner."""

    owner_id: Optional[str] = None
    collaborator_ids: list[str] = []


class TaskResponse(ApiResponse):
    id: str
    project_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    description_html: Optional[str] = None
    description_doc: Optional[dict[str, Any]] = None
    # Human key, ``<project code>-<sequence>`` (e.g. ``TT-67``).
    code: Optional[str] = None
    workflow_id: Optional[str] = None
    stage_id: Optional[str] = None
    # Mirrors the stage's type (analytics across workflows).
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
    # Sum of the task's time entries (not rejected).
    actual_minutes: Optional[int] = None
    # Effort (time-tracking-spec §5.1, §5.2): remaining (typed = manual), forecast, variance, subtree roll-ups.
    remaining_minutes: Optional[int] = None
    remaining_manual: bool = False
    forecast_minutes: Optional[int] = None
    variance_minutes: Optional[int] = None
    variance_pct: Optional[int] = None
    rollup_estimated_minutes: Optional[int] = None
    rollup_actual_minutes: Optional[int] = None
    rollup_remaining_minutes: Optional[int] = None
    rollup_forecast_minutes: Optional[int] = None
    rollup_variance_pct: Optional[int] = None
    variance_alert_level: Optional[str] = None
    progress: Optional[int] = None
    progress_mode: Optional[str] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None
    # Owner = ``user_id``; collaborators work on it too (Ppm-0825).
    collaborators: list[str] = []
    # Roll-ups (Ppm-0817): counted / done subtasks, checklist done / total, children's date span.
    child_count: int = 0
    done_child_count: int = 0
    checklist_total: int = 0
    checklist_done: int = 0
    rollup_start_date: Optional[datetime] = None
    rollup_due_date: Optional[datetime] = None
    # Behaviour of the item type (§5.1): ``task`` · ``milestone`` · ``deliverable`` · ``approval`` · ``request`` · …
    behaviour: Optional[str] = None
    recurrence_rule: Optional[str] = None
    recurrence_id: Optional[str] = None
    # Schedule (taas-specs/ppm/schedule): phase of a top-level item, working-day duration, ``auto`` / ``manual``
    # (null = the project's mode), constraint ``asap`` · ``snet`` · ``mso`` · ``fnlt`` + its date.
    phase_id: Optional[str] = None
    duration_days: Optional[int] = None
    schedule_mode: Optional[str] = None
    constraint_type: Optional[str] = None
    constraint_date: Optional[datetime] = None
    # Actual start: first *active* / *review* / *done* stage.
    started_at: Optional[datetime] = None
    # Custom field values ``{key: value}`` (stored ones; hidden when the field is not bound to the type).
    custom_fields: dict[str, Any] = {}
    # Status of the item's latest approval (``pending`` · ``approved`` · ``rejected`` · ``changes_requested`` · …).
    approval_status: Optional[str] = None
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
    """A comment: plain ``text`` or rich ``html`` (sanitized; mention chips notify, Ppm-0510)."""

    text: Optional[str] = None
    html: Optional[str] = None
    # Ignored: the author is the session user (Ppm-0502).
    user_id: Optional[str] = None


class TaskCommentUpdateRequest(ApiRequest):
    text: Optional[str] = None
    html: Optional[str] = None


class TaskCommentResponse(ApiResponse):
    id: str
    # The commented item (``subject_type = task``) or project.
    task_id: str
    subject_type: str = 'task'
    # Author (session e-mail / id, ADR-12).
    user_id: Optional[str] = None
    text: Optional[str] = None
    html: Optional[str] = None
    mentions: list[str] = []
    # Mentioned users who cannot read the subject: not notified (Ppm-1708).
    unreachable_mentions: list[str] = []
    created_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    deleted: bool = False
    can_edit: bool = False
    can_delete: bool = False


class TimelogCreateRequest(ApiRequest):
    """A time log on a task; ``minutes`` wins over ``start_time``/``end_time``."""

    user_id: Optional[str] = None
    # The day of the entry (``log_date`` = older clients).
    entry_date: Optional[date] = None
    log_date: Optional[datetime] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    minutes: Optional[int] = None
    is_billable: Optional[bool] = None
    description: Optional[str] = None
