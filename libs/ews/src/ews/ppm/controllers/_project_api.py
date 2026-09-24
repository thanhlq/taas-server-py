"""Project and Task HTTP controllers (EWS PPM).

Thin controllers over the existing PPM repositories. Projects can be created
with or without a workflow template; tasks are placed on the board by
``stage_type`` (the same value the Kanban board groups by).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

import db.models.ews as ews_models
from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter, StatementFilter
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.response import PaginatedResponse, create_paginated_response
from sqlalchemy import func, or_, select, update

from ..repos import ProjectRepository, RepoFactory, TaskRepository
from ..schemas._project_api import (
    ProjectCreateRequest,
    ProjectListItem,
    ProjectResponse,
    ProjectUpdateRequest,
)
from ..schemas._task_api import TaskCreateRequest, TaskResponse, TaskUpdateRequest

# Default board seeded when a project is created from a template but the template
# does not specify its own stages. Grouping on the board is by ``stage_type``.
_DEFAULT_TEMPLATE_STAGES: list[dict[str, Any]] = [
    {'name': 'Backlog', 'stage_type': 'backlog', 'tone': 'gray', 'order': 1},
    {'name': 'In Progress', 'stage_type': 'in_progress', 'tone': 'blue', 'order': 2},
    {'name': 'Review', 'stage_type': 'review', 'tone': 'amber', 'order': 3},
    {'name': 'Done', 'stage_type': 'done', 'tone': 'green', 'order': 4},
]


def _to_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _seed_workflow(template_id: str, category: Optional[str]) -> dict[str, Any]:
    """Build the denormalized workflow payload for a templated project."""
    return {
        'template_id': template_id,
        'category': category,
        'stages': _DEFAULT_TEMPLATE_STAGES,
    }


def _project_fields(p: ews_models.Project) -> dict[str, Any]:
    """Fields shared by the list item and the detail response."""
    return {
        'id': str(p.id),
        'name': p.name,
        'code': p.code,
        'status': p.status,
        'color': p.color,
        'icon_name': p.icon_name,
        'default_view': p.default_view,
        'starred': p.starred,
        'pinned': p.pinned,
        'start_date': p.start_date,
        'due_date': p.due_date,
        'created_at': getattr(p, 'created_at', None),
        'updated_at': getattr(p, 'updated_at', None),
        'description': p.description,
        'avatar_url': p.avatar_url,
        'user_id': p.user_id,
        'client_id': p.client_id,
        'last_activity_at': p.last_activity_at,
    }


def _with_progress(
    fields: dict[str, Any], stats: Optional[tuple[int, int]]
) -> dict[str, Any]:
    total, done = stats or (0, 0)
    return {
        **fields,
        'task_count': total,
        'done_task_count': done,
        'progress': round(done * 100 / total) if total else 0,
    }


def _project_to_response(
    p: ews_models.Project, stats: Optional[tuple[int, int]] = None
) -> ProjectResponse:
    return ProjectResponse(
        **_with_progress(_project_fields(p), stats),
        org_id=p.org_id,
        workflow=p.workflow,
        settings=p.settings,
        properties=p.properties,
    )


def _project_to_list_item(
    p: ews_models.Project, stats: Optional[tuple[int, int]] = None
) -> ProjectListItem:
    return ProjectListItem(**_with_progress(_project_fields(p), stats))


def _now() -> datetime:
    """Naive UTC timestamp (``last_activity_at`` is a plain TIMESTAMP column)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _task_stats(
    session: DBAsyncScopedSession, project_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    """``{project_id: (tasks, done tasks)}``; a task is done in the ``done`` stage or once completed."""
    if not project_ids:
        return {}
    task = ews_models.Task
    done = func.count(task.id).filter(
        or_(task.stage_type == 'done', task.completed_at.is_not(None))
    )
    result = await session.execute(
        select(task.project_id, func.count(task.id), done)
        .where(task.project_id.in_(project_ids), task.deleted_at.is_(None))
        .group_by(task.project_id)
    )
    return {row[0]: (int(row[1]), int(row[2])) for row in result.all()}


async def _touch_project(
    session: DBAsyncScopedSession, project_id: Optional[UUID]
) -> None:
    """Record activity on a project (a task in it changed)."""
    if project_id is None:
        return
    await session.execute(
        update(ews_models.Project)
        .where(ews_models.Project.id == project_id)
        .values(last_activity_at=_now())
    )


def _task_to_response(t: ews_models.Task) -> TaskResponse:
    return TaskResponse(
        id=str(t.id),
        project_id=str(t.project_id) if t.project_id else None,
        name=t.name,
        description=t.description,
        code=t.code,
        stage_id=str(t.stage_id) if t.stage_id else None,
        stage_type=t.stage_type,
        work_item_type=t.work_item_type,
        parent_id=str(t.parent_id) if t.parent_id else None,
        requested_user_id=t.requested_user_id,
        progress=t.progress,
        completed_at=t.completed_at,
        created_at=getattr(t, 'created_at', None),
        updated_at=getattr(t, 'updated_at', None),
    )


class ProjectController(BaseController):
    """Projects: create (with/without template), list, detail, update, delete."""

    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @get('/')
    @db_context_session
    async def list_projects(
        self,
        session: DBAsyncScopedSession,
        limit: int = 50,
        offset: int = 0,
        q: Optional[str] = None,
    ) -> PaginatedResponse[ProjectListItem]:
        """List projects; ``q`` searches name, code and description (case-insensitive)."""
        repo = RepoFactory.get_repo(ProjectRepository, session)
        filters: list[StatementFilter] = [
            LimitOffset(limit=limit, offset=offset),
            OrderBy(field_name='id', sort_order='desc'),
        ]
        if q and q.strip():
            filters.append(
                SearchFilter(
                    field_name={'name', 'code', 'description'},
                    value=q.strip(),
                    ignore_case=True,
                )
            )
        rows, total = await repo.list_and_count(*filters)
        stats = await _task_stats(session, [p.id for p in rows])
        return create_paginated_response(
            [_project_to_list_item(p, stats.get(p.id)) for p in rows], total=total
        )

    @get('/{project_id}')
    @db_context_session
    async def get_project(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        repo = RepoFactory.get_repo(ProjectRepository, session)
        p = await repo.get(_to_uuid(project_id))
        stats = await _task_stats(session, [p.id])
        return _project_to_response(p, stats.get(p.id))

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_project(
        self, data: ProjectCreateRequest, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        repo = RepoFactory.get_repo(ProjectRepository, session)
        project = ews_models.Project(
            name=data.name,
            description=data.description,
            code=data.code,
            status=data.status or 'New',
            start_date=data.start_date,
            due_date=data.due_date,
            color=data.color,
            icon_name=data.icon_name,
            default_view=data.default_view,
            org_id=data.org_id,
            client_id=data.client_id,
            user_id=data.user_id,
            last_activity_at=_now(),
        )
        if data.template_id:
            project.workflow = _seed_workflow(data.template_id, data.category)
            project.default_view = data.default_view or 'kanban'
        elif data.category:
            project.workflow = {'category': data.category}
        created = await repo.add(project)
        return _project_to_response(created)

    @patch('/{project_id}')
    @db_context_session(auto_commit=True)
    async def update_project(
        self, project_id: str, data: ProjectUpdateRequest, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        repo = RepoFactory.get_repo(ProjectRepository, session)
        p = await repo.get(_to_uuid(project_id))
        for field, value in data.as_dict().items():
            setattr(p, field, value)
        p.last_activity_at = _now()
        updated = await repo.update(p)
        stats = await _task_stats(session, [updated.id])
        return _project_to_response(updated, stats.get(updated.id))

    @delete('/{project_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_project(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> None:
        repo = RepoFactory.get_repo(ProjectRepository, session)
        await repo.delete(_to_uuid(project_id))


class TaskController(BaseController):
    """Tasks: create (in a column), list by project, quick update, delete."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/')
    @db_context_session
    async def list_tasks(
        self,
        session: DBAsyncScopedSession,
        project_id: str,
        limit: int = 200,
        offset: int = 0,
        q: Optional[str] = None,
    ) -> PaginatedResponse[TaskResponse]:
        """List a project's tasks; ``q`` searches name and description (case-insensitive)."""
        repo = RepoFactory.get_repo(TaskRepository, session)
        filters: list[StatementFilter] = [LimitOffset(limit=limit, offset=offset)]
        if q and q.strip():
            filters.append(
                SearchFilter(
                    field_name={'name', 'description'}, value=q.strip(), ignore_case=True
                )
            )
        rows, total = await repo.list_and_count(
            *filters,
            project_id=_to_uuid(project_id),
        )
        return create_paginated_response(
            [_task_to_response(t) for t in rows], total=total
        )

    @get('/{task_id}')
    @db_context_session
    async def get_task(self, task_id: str, session: DBAsyncScopedSession) -> TaskResponse:
        repo = RepoFactory.get_repo(TaskRepository, session)
        t = await repo.get(_to_uuid(task_id))
        return _task_to_response(t)

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task(
        self, data: TaskCreateRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        repo = RepoFactory.get_repo(TaskRepository, session)
        task = ews_models.Task(
            project_id=_to_uuid(data.project_id),
            name=data.name,
            description=data.description,
            stage_id=_to_uuid(data.stage_id),
            stage_type=data.stage_type,
            work_item_type=data.work_item_type,
            parent_id=_to_uuid(data.parent_id),
            requested_user_id=data.requested_user_id,
            progress=data.progress or 0,
        )
        created = await repo.add(task)
        await _touch_project(session, created.project_id)
        return _task_to_response(created)

    @patch('/{task_id}')
    @db_context_session(auto_commit=True)
    async def update_task(
        self, task_id: str, data: TaskUpdateRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        repo = RepoFactory.get_repo(TaskRepository, session)
        t = await repo.get(_to_uuid(task_id))
        for field, value in data.as_dict().items():
            setattr(t, field, value)
        updated = await repo.update(t)
        await _touch_project(session, updated.project_id)
        return _task_to_response(updated)

    @delete('/{task_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task(self, task_id: str, session: DBAsyncScopedSession) -> None:
        repo = RepoFactory.get_repo(TaskRepository, session)
        deleted = await repo.delete(_to_uuid(task_id))
        await _touch_project(session, deleted.project_id)
