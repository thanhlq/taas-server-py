"""Task helpers shared by the task, task list, iteration, comment and time log controllers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import func, select

from ..schemas._task_api import TASK_CLEARABLE_FIELDS, TaskResponse

# ``ProjectComment.object_type`` of task comments.
TASK_COMMENT_OBJECT_TYPE = 'task'

# Task code prefix when the project has no code.
_DEFAULT_CODE_PREFIX = 'T'


def to_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def uuid7_time(value: Any) -> Optional[datetime]:
    """Creation time embedded in a UUIDv7 id (naive UTC) — the models have no ``created_at``."""
    try:
        uid = value if isinstance(value, UUID) else UUID(str(value))
    except TypeError, ValueError:
        return None
    if uid.version != 7:
        return None
    millis = int(uid.hex[:12], 16)
    return datetime.fromtimestamp(millis / 1000, UTC).replace(tzinfo=None)


def clean_list(values: Optional[list[str]]) -> list[str]:
    """Trimmed, de-duplicated (order kept) non-empty strings."""
    return list(dict.fromkeys(v.strip() for v in values or [] if v and v.strip()))


def _json_list(container: Any, key: str) -> list[str]:
    data = container if isinstance(container, dict) else {}
    values = data.get(key)
    return [str(v) for v in values] if isinstance(values, list) else []


def task_labels(t: ews_models.Task) -> list[str]:
    """Labels, stored as ``tags = {'labels': [...]}`` (same as projects)."""
    return _json_list(t.tags, 'labels')


def task_watchers(t: ews_models.Task) -> list[str]:
    """Watchers (followers), stored as ``followers = {'users': [...]}``."""
    return _json_list(t.followers, 'users')


def clamp_priority(value: Optional[int]) -> Optional[int]:
    return None if value is None else max(0, min(5, int(value)))


def apply_task_update(t: ews_models.Task, fields: dict[str, Any]) -> None:
    """Apply a ``TaskUpdateRequest.as_dict()`` (omitted = unchanged) to a task."""
    clear = set(fields.pop('clear', None) or []) & TASK_CLEARABLE_FIELDS
    labels = fields.pop('labels', None)
    watchers = fields.pop('watchers', None)
    html = fields.pop('description_html', None)
    for key in ('task_list_id', 'iteration_id', 'stage_id'):
        if key in fields:
            fields[key] = to_uuid(fields[key])
    if 'priority' in fields:
        fields['priority'] = clamp_priority(fields['priority'])
    for field, value in fields.items():
        setattr(t, field, value)
    if labels is not None:
        t.tags = {
            **(t.tags if isinstance(t.tags, dict) else {}),
            'labels': clean_list(labels),
        }
    if watchers is not None:
        t.followers = {
            **(t.followers if isinstance(t.followers, dict) else {}),
            'users': clean_list(watchers),
        }
    if html is not None:
        t.html_text = html
        t.content_type = 'html'
    for field in clear:
        if field == 'description_html':
            t.html_text = None
            t.content_type = 'md'
        else:
            setattr(t, field, None)


def task_to_response(t: ews_models.Task) -> TaskResponse:
    return TaskResponse(
        id=str(t.id),
        project_id=str(t.project_id) if t.project_id else None,
        name=t.name,
        description=t.description,
        description_html=t.html_text,
        code=t.code,
        stage_id=str(t.stage_id) if t.stage_id else None,
        stage_type=t.stage_type,
        work_item_type=t.work_item_type,
        parent_id=str(t.parent_id) if t.parent_id else None,
        requested_user_id=t.requested_user_id,
        user_id=t.user_id,
        task_list_id=str(t.task_list_id) if t.task_list_id else None,
        iteration_id=str(t.iteration_id) if t.iteration_id else None,
        labels=task_labels(t),
        watchers=task_watchers(t),
        priority=t.priority,
        start_date=t.start_date,
        due_date=t.due_date,
        estimated_minutes=t.estimated_minutes,
        actual_minutes=t.actual_minutes or 0,
        progress=t.progress,
        completed_at=t.completed_at,
        created_at=uuid7_time(t.id),
        updated_at=getattr(t, 'updated_at', None),
    )


async def next_task_code(
    session: DBAsyncScopedSession, project_id: Optional[UUID]
) -> tuple[Optional[int], Optional[str]]:
    """Next ``(sequence_id, code)`` of a project's task, e.g. ``(67, 'TT-67')``."""
    if project_id is None:
        return None, None
    last = await session.scalar(
        select(func.max(ews_models.Task.sequence_id)).where(
            ews_models.Task.project_id == project_id
        )
    )
    prefix = await session.scalar(
        select(ews_models.Project.code).where(ews_models.Project.id == project_id)
    )
    sequence = int(last or 0) + 1
    return sequence, f'{(prefix or _DEFAULT_CODE_PREFIX).strip()}-{sequence}'


async def refresh_actual_minutes(
    session: DBAsyncScopedSession, task: ews_models.Task
) -> None:
    """``actual_minutes`` = the sum of the task's time logs."""
    total = await session.scalar(
        select(func.coalesce(func.sum(ews_models.Timelog.log_minutes), 0)).where(
            ews_models.Timelog.task_id == task.id,
            ews_models.Timelog.deleted_at.is_(None),
        )
    )
    task.actual_minutes = int(total or 0)
