"""Comments, Activity and time logs of items and projects (EWS PPM).

- Comments are ``ProjectComment`` rows with ``object_type`` ``task`` · ``project`` and ``object_id`` (newest first);
  the author is the session user; rules in ``ews.ppm._comments`` (rich text, mentions, edit, soft delete).
- Activity = the audit store read model (``ews.ppm._activity``).
- Time logs are ``Timelog`` rows; every change refreshes ``Task.actual_minutes``.
- Both are reached through their task's project (``ppm.task_activity``, Ppm-0002); deletes are soft (Ppm-0011):
  own entries, or with ``ppm.task_activity:delete``.
"""

from __future__ import annotations

from datetime import datetime

import db.models.ews as ews_models
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import NotFoundException
from foundation.http import BaseController, delete, get, patch, post, status

from ews.security import RequestScope, current_scope

from .. import _access as access
from .. import _activity as activity
from .. import _comments as comments
from .. import _time as time

from ..schemas._activity_api import PpmActivityOut, PpmActorOut
from ..schemas._time_api import PpmTimeEntryOut
from ..schemas._task_api import (
    TaskCommentCreateRequest,
    TaskCommentResponse,
    TaskCommentUpdateRequest,
    TimelogCreateRequest,
)
from ._project_api import _touch_project
from ._task_support import (
    TASK_COMMENT_OBJECT_TYPE,
    uuid7_time,
)

ACTIVITY = access.TASK_ACTIVITY


async def _require_own_or_delete(
    scope: RequestScope, project_id, owner: str | None
) -> None:
    """Own comment / time log, or ``ppm.task_activity:delete`` (project admins)."""
    if owner and owner == access.author(scope):
        return
    await access.require(scope, project_id, ACTIVITY, 'delete')


def _naive(value: datetime | None) -> datetime | None:
    """The timelog columns are naive TIMESTAMPs: drop the offset (values are sent as local wall time)."""
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


async def _comment_out(
    scope: RequestScope,
    project: ews_models.Project,
    c: ews_models.ProjectComment,
    *,
    mentions: list[str] | None = None,
    unreachable: list[str] | None = None,
) -> TaskCommentResponse:
    deleted = c.deleted_at is not None
    mine = bool(c.user_id) and c.user_id == access.author(scope)
    return TaskCommentResponse(
        id=str(c.id),
        task_id=c.object_id or '',
        subject_type=c.object_type or 'task',
        user_id=c.user_id,
        text=None if deleted else c.comment_text,
        html=None if deleted else c.html_text,
        mentions=mentions or [],
        unreachable_mentions=unreachable or [],
        created_at=uuid7_time(c.id),
        edited_at=c.edited_at,
        deleted=deleted,
        can_edit=mine and not deleted,
        can_delete=not deleted and await comments.can_delete(scope, project, c),
    )


def _activity_out(e) -> PpmActivityOut:
    return PpmActivityOut(
        id=str(e.id),
        event=e.event,
        subject_type=e.subject_type,
        subject_id=e.subject_id,
        actor=PpmActorOut(type=e.actor_type, ref=e.actor_ref, name=e.actor_name),
        cause=e.cause,
        changes=e.changes or {},
        data=e.data or {},
        occurred_at=e.occurred_at,
    )


class TaskCommentController(BaseController):
    """An item's comments (newest first; deleted ones as placeholders) and its Activity (Ppm-05xx)."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/{task_id}/comments')
    @db_context_session
    async def list_task_comments(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[TaskCommentResponse]:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, ACTIVITY, 'read'
        )
        rows = await comments.listing(session, TASK_COMMENT_OBJECT_TYPE, str(task.id))
        return [await _comment_out(scope, project, row) for row in rows]

    @post('/{task_id}/comments', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task_comment(
        self,
        task_id: str,
        data: TaskCommentCreateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskCommentResponse:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, ACTIVITY, 'create'
        )
        saved = await comments.create(
            session, scope, project, task, text=data.text, html=data.html
        )
        await _touch_project(session, task.project_id)
        return await _comment_out(
            scope,
            project,
            saved.comment,
            mentions=saved.mentions,
            unreachable=saved.unreachable,
        )

    @patch('/{task_id}/comments/{comment_id}', summary='Edit an own comment (Ppm-0504)')
    @db_context_session(auto_commit=True)
    async def update_task_comment(
        self,
        task_id: str,
        comment_id: str,
        data: TaskCommentUpdateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskCommentResponse:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, ACTIVITY, 'update'
        )
        comment = await comments.get(
            session, TASK_COMMENT_OBJECT_TYPE, str(task.id), comment_id
        )
        saved = await comments.edit(
            session, scope, project, task, comment, text=data.text, html=data.html
        )
        return await _comment_out(
            scope,
            project,
            saved.comment,
            mentions=saved.mentions,
            unreachable=saved.unreachable,
        )

    @delete('/{task_id}/comments/{comment_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task_comment(
        self, task_id: str, comment_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, ACTIVITY, 'read'
        )
        comment = await comments.get(
            session, TASK_COMMENT_OBJECT_TYPE, str(task.id), comment_id
        )
        await comments.remove(session, scope, project, task, comment)

    @get(
        '/{task_id}/activity',
        summary='Activity of an item: changes, comments, people, checklist, time, files',
    )
    @db_context_session
    async def task_activity(
        self,
        task_id: str,
        session: DBAsyncScopedSession,
        type: str | None = None,  # noqa: A002 — query parameter name of the spec
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[PpmActivityOut]:
        scope = await current_scope()
        task, _ = await access.load_task(session, scope, task_id)
        rows = await activity.listing(
            session,
            tenant_id=scope.tenant_id,
            subject=('task', str(task.id)),
            kind=type,
            before=before,
            limit=limit,
        )
        return [_activity_out(e) for e in rows]


class ProjectCommentController(BaseController):
    """A project's comments (dashboard *comments* tab, Ppm-0505) and its Activity."""

    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @get('/{project_id}/comments')
    @db_context_session
    async def list_project_comments(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> list[TaskCommentResponse]:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, ACTIVITY, 'read'
        )
        rows = await comments.listing(session, 'project', str(project.id))
        return [await _comment_out(scope, project, row) for row in rows]

    @post('/{project_id}/comments', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_project_comment(
        self,
        project_id: str,
        data: TaskCommentCreateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskCommentResponse:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, ACTIVITY, 'create'
        )
        saved = await comments.create(
            session, scope, project, None, text=data.text, html=data.html
        )
        await _touch_project(session, project.id)
        return await _comment_out(
            scope,
            project,
            saved.comment,
            mentions=saved.mentions,
            unreachable=saved.unreachable,
        )

    @patch('/{project_id}/comments/{comment_id}')
    @db_context_session(auto_commit=True)
    async def update_project_comment(
        self,
        project_id: str,
        comment_id: str,
        data: TaskCommentUpdateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskCommentResponse:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, ACTIVITY, 'update'
        )
        comment = await comments.get(session, 'project', str(project.id), comment_id)
        saved = await comments.edit(
            session, scope, project, None, comment, text=data.text, html=data.html
        )
        return await _comment_out(
            scope,
            project,
            saved.comment,
            mentions=saved.mentions,
            unreachable=saved.unreachable,
        )

    @delete(
        '/{project_id}/comments/{comment_id}', status_code=status.HTTP_204_NO_CONTENT
    )
    @db_context_session(auto_commit=True)
    async def delete_project_comment(
        self, project_id: str, comment_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, ACTIVITY, 'read'
        )
        comment = await comments.get(session, 'project', str(project.id), comment_id)
        await comments.remove(session, scope, project, None, comment)

    @get(
        '/{project_id}/activity',
        summary='Activity of a project: every event of the project, newest first',
    )
    @db_context_session
    async def project_activity(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        type: str | None = None,  # noqa: A002
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[PpmActivityOut]:
        scope = await current_scope()
        project = await access.load_project(session, scope, project_id)
        rows = await activity.listing(
            session,
            tenant_id=scope.tenant_id,
            project_id=project.id,
            kind=type,
            before=before,
            limit=limit,
        )
        return [_activity_out(e) for e in rows]


class TaskTimelogController(BaseController):
    """A task's time entries (the item Time tab): list, log time, delete — the rules of ``ews.ppm._time``
    (validation, weekly timesheet, locks, effort)."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/{task_id}/timelogs')
    @db_context_session
    async def list_task_timelogs(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[PpmTimeEntryOut]:
        task, _ = await access.load_task(
            session, await current_scope(), task_id, time.TIME_ENTRY, 'read'
        )
        rows = await time.task_entries(session, task)
        return [PpmTimeEntryOut(**e) for e in await time.entries_out(session, rows)]

    @post('/{task_id}/timelogs', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task_timelog(
        self, task_id: str, data: TimelogCreateRequest, session: DBAsyncScopedSession
    ) -> PpmTimeEntryOut:
        scope = await current_scope()
        day = data.entry_date or (data.log_date.date() if data.log_date else None)
        entry = await time.create_entry(
            session,
            scope,
            time.EntryIn(
                task_id=task_id,
                entry_date=day,
                minutes=data.minutes,
                start_time=_naive(data.start_time),
                end_time=_naive(data.end_time),
                is_billable=data.is_billable,
                description=data.description,
                user=data.user_id,
            ),
        )
        return PpmTimeEntryOut(**(await time.entries_out(session, [entry]))[0])

    @delete('/{task_id}/timelogs/{timelog_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task_timelog(
        self, task_id: str, timelog_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope = await current_scope()
        task, _ = await access.load_task(session, scope, task_id)
        entry = await time.load_entry(session, scope, timelog_id, 'delete')
        if entry.task_id != task.id:
            raise NotFoundException(detail='time log not found')
        await time.delete_entry(session, scope, entry)
