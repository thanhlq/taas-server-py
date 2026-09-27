"""Task activity HTTP controllers (EWS PPM): comments and time logs of a task.

- Comments are ``ProjectComment`` rows with ``object_type='task'`` and
  ``object_id=<task id>`` (newest first).
- Time logs are ``Timelog`` rows; every change refreshes ``Task.actual_minutes``.
"""

from __future__ import annotations

from datetime import datetime

import db.models.ews as ews_models
from advanced_alchemy.exceptions import NotFoundError
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, post, status
from sqlalchemy import select

from ..repos import (
    ProjectCommentRepository,
    RepoFactory,
    TaskRepository,
    TimelogRepository,
)
from ..schemas._task_api import (
    TaskCommentCreateRequest,
    TaskCommentResponse,
    TimelogCreateRequest,
    TimelogResponse,
)
from ._project_api import _now, _touch_project
from ._task_support import (
    TASK_COMMENT_OBJECT_TYPE,
    refresh_actual_minutes,
    to_uuid,
    uuid7_time,
)


def _comment_to_response(c: ews_models.ProjectComment) -> TaskCommentResponse:
    return TaskCommentResponse(
        id=str(c.id),
        task_id=c.object_id or '',
        user_id=c.user_id,
        text=c.comment_text,
        created_at=uuid7_time(c.id),
    )


def _timelog_to_response(t: ews_models.Timelog) -> TimelogResponse:
    return TimelogResponse(
        id=str(t.id),
        task_id=str(t.task_id) if t.task_id else None,
        project_id=str(t.project_id) if t.project_id else None,
        user_id=t.user_id,
        log_date=t.log_date,
        start_time=t.start_time,
        end_time=t.end_time,
        minutes=t.log_minutes or 0,
        is_billable=bool(t.is_billable),
        description=t.description,
        created_at=uuid7_time(t.id),
    )


def _naive(value: datetime | None) -> datetime | None:
    """The timelog columns are naive TIMESTAMPs: drop the offset (values are sent as local wall time)."""
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


def _log_minutes(data: TimelogCreateRequest) -> int:
    if data.minutes is not None:
        return max(0, int(data.minutes))
    if data.start_time and data.end_time:
        return max(
            0,
            int(
                (_naive(data.end_time) - _naive(data.start_time)).total_seconds() // 60
            ),
        )
    return 0


class TaskCommentController(BaseController):
    """A task's comments: list (newest first), add, delete."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/{task_id}/comments')
    @db_context_session
    async def list_task_comments(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[TaskCommentResponse]:
        c = ews_models.ProjectComment
        rows = await session.scalars(
            select(c)
            .where(
                c.object_type == TASK_COMMENT_OBJECT_TYPE,
                c.object_id == str(to_uuid(task_id)),
                c.deleted_at.is_(None),
            )
            .order_by(c.id.desc())
        )
        return [_comment_to_response(row) for row in rows.all()]

    @post('/{task_id}/comments', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task_comment(
        self,
        task_id: str,
        data: TaskCommentCreateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskCommentResponse:
        task = await RepoFactory.get_repo(TaskRepository, session).get(to_uuid(task_id))
        repo = RepoFactory.get_repo(ProjectCommentRepository, session)
        created = await repo.add(
            ews_models.ProjectComment(
                user_id=data.user_id,
                comment_text=data.text.strip(),
                content_type='text',
                project_id=str(task.project_id) if task.project_id else None,
                object_id=str(task.id),
                object_type=TASK_COMMENT_OBJECT_TYPE,
            )
        )
        await _touch_project(session, task.project_id)
        return _comment_to_response(created)

    @delete('/{task_id}/comments/{comment_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task_comment(
        self, task_id: str, comment_id: str, session: DBAsyncScopedSession
    ) -> None:
        repo = RepoFactory.get_repo(ProjectCommentRepository, session)
        comment = await repo.get(to_uuid(comment_id))
        if comment.object_id != str(to_uuid(task_id)):
            raise NotFoundError(
                f'Comment {comment_id} does not belong to task {task_id}'
            )
        await repo.delete(comment.id)


class TaskTimelogController(BaseController):
    """A task's time logs: list (newest first), log time, delete."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/{task_id}/timelogs')
    @db_context_session
    async def list_task_timelogs(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[TimelogResponse]:
        t = ews_models.Timelog
        rows = await session.scalars(
            select(t)
            .where(t.task_id == to_uuid(task_id), t.deleted_at.is_(None))
            .order_by(t.log_date.desc().nulls_last(), t.id.desc())
        )
        return [_timelog_to_response(row) for row in rows.all()]

    @post('/{task_id}/timelogs', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task_timelog(
        self, task_id: str, data: TimelogCreateRequest, session: DBAsyncScopedSession
    ) -> TimelogResponse:
        task_repo = RepoFactory.get_repo(TaskRepository, session)
        task = await task_repo.get(to_uuid(task_id))
        repo = RepoFactory.get_repo(TimelogRepository, session)
        created = await repo.add(
            ews_models.Timelog(
                task_id=task.id,
                project_id=task.project_id,
                user_id=data.user_id,
                email=data.user_id if data.user_id and '@' in data.user_id else None,
                log_date=_naive(data.log_date) or _now(),
                start_time=_naive(data.start_time),
                end_time=_naive(data.end_time),
                log_minutes=_log_minutes(data),
                is_billable=bool(data.is_billable),
                description=data.description,
            )
        )
        await refresh_actual_minutes(session, task)
        await task_repo.update(task)
        await _touch_project(session, task.project_id)
        return _timelog_to_response(created)

    @delete('/{task_id}/timelogs/{timelog_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task_timelog(
        self, task_id: str, timelog_id: str, session: DBAsyncScopedSession
    ) -> None:
        repo = RepoFactory.get_repo(TimelogRepository, session)
        log = await repo.get(to_uuid(timelog_id))
        if str(log.task_id) != str(to_uuid(task_id)):
            raise NotFoundError(
                f'Time log {timelog_id} does not belong to task {task_id}'
            )
        await repo.delete(log.id)
        task_repo = RepoFactory.get_repo(TaskRepository, session)
        task = await task_repo.get(to_uuid(task_id))
        await refresh_actual_minutes(session, task)
        await task_repo.update(task)
