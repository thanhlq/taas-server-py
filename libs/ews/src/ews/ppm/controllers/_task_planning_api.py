"""Task planning HTTP controllers (EWS PPM): a project's task lists and iterations.

- Task lists group a project's tasks (category for management / automation);
  a task belongs to at most one (``Task.task_list_id``).
- Iterations (sprints) are time boxes tasks are planned into (``Task.iteration_id``).
"""

from __future__ import annotations

import db.models.ews as ews_models
from advanced_alchemy.exceptions import NotFoundError
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from sqlalchemy import func, select, update

from ..repos import ProjectIterationRepository, RepoFactory, TaskListRepository
from ..schemas._task_api import (
    IterationCreateRequest,
    IterationResponse,
    IterationUpdateRequest,
    TaskListCreateRequest,
    TaskListResponse,
    TaskListUpdateRequest,
)
from ._task_support import to_uuid

_ITERATION_STATUSES = frozenset({'planned', 'active', 'completed'})


def _task_list_to_response(t: ews_models.TaskList) -> TaskListResponse:
    return TaskListResponse(
        id=str(t.id),
        project_id=str(t.project_id) if t.project_id else None,
        name=t.name,
        description=t.description,
        color=t.color,
        display_order=t.display_order,
    )


def _iteration_to_response(i: ews_models.ProjectIteration) -> IterationResponse:
    return IterationResponse(
        id=str(i.id),
        project_id=str(i.project_id) if i.project_id else None,
        name=i.name,
        goal=i.goal,
        status=i.status,
        start_date=i.start_date,
        due_date=i.due_date,
    )


def _iteration_status(value: str | None) -> str:
    return value if value in _ITERATION_STATUSES else 'planned'


async def _get_owned(repo, project_id: str, item_id: str):
    """The record ``item_id`` of project ``project_id`` (404 otherwise)."""
    item = await repo.get(to_uuid(item_id))
    if str(item.project_id) != str(to_uuid(project_id)):
        raise NotFoundError(f'{item_id} does not belong to project {project_id}')
    return item


class ProjectTaskListController(BaseController):
    """A project's task lists: list (display order), create, rename / recolour, delete."""

    api_prefix = '/api/v1/projects'
    tags = ('Task lists',)

    @get('/{project_id}/task-lists')
    @db_context_session
    async def list_task_lists(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> list[TaskListResponse]:
        rows = await session.scalars(
            select(ews_models.TaskList)
            .where(
                ews_models.TaskList.project_id == to_uuid(project_id),
                ews_models.TaskList.deleted_at.is_(None),
            )
            .order_by(ews_models.TaskList.display_order, ews_models.TaskList.id)
        )
        return [_task_list_to_response(t) for t in rows.all()]

    @post('/{project_id}/task-lists', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task_list(
        self,
        project_id: str,
        data: TaskListCreateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskListResponse:
        pid = to_uuid(project_id)
        order = data.display_order
        if order is None:
            last = await session.scalar(
                select(func.max(ews_models.TaskList.display_order)).where(
                    ews_models.TaskList.project_id == pid
                )
            )
            order = max(float(last or 0), 0) + 1
        repo = RepoFactory.get_repo(TaskListRepository, session)
        created = await repo.add(
            ews_models.TaskList(
                project_id=pid,
                name=data.name.strip(),
                description=data.description,
                color=data.color,
                display_order=order,
            )
        )
        return _task_list_to_response(created)

    @patch('/{project_id}/task-lists/{task_list_id}')
    @db_context_session(auto_commit=True)
    async def update_task_list(
        self,
        project_id: str,
        task_list_id: str,
        data: TaskListUpdateRequest,
        session: DBAsyncScopedSession,
    ) -> TaskListResponse:
        repo = RepoFactory.get_repo(TaskListRepository, session)
        item = await _get_owned(repo, project_id, task_list_id)
        for field, value in data.as_dict().items():
            setattr(item, field, value.strip() if field == 'name' else value)
        return _task_list_to_response(await repo.update(item))

    @delete(
        '/{project_id}/task-lists/{task_list_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    @db_context_session(auto_commit=True)
    async def delete_task_list(
        self, project_id: str, task_list_id: str, session: DBAsyncScopedSession
    ) -> None:
        """Delete a task list; its tasks stay in the project without a list."""
        repo = RepoFactory.get_repo(TaskListRepository, session)
        item = await _get_owned(repo, project_id, task_list_id)
        await session.execute(
            update(ews_models.Task)
            .where(ews_models.Task.task_list_id == item.id)
            .values(task_list_id=None)
        )
        await repo.delete(item.id)


class ProjectIterationController(BaseController):
    """A project's iterations (sprints): list (by start date), create, update, delete."""

    api_prefix = '/api/v1/projects'
    tags = ('Iterations',)

    @get('/{project_id}/iterations')
    @db_context_session
    async def list_iterations(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> list[IterationResponse]:
        it = ews_models.ProjectIteration
        rows = await session.scalars(
            select(it)
            .where(it.project_id == to_uuid(project_id), it.deleted_at.is_(None))
            .order_by(it.start_date.nulls_last(), it.id)
        )
        return [_iteration_to_response(i) for i in rows.all()]

    @post('/{project_id}/iterations', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_iteration(
        self,
        project_id: str,
        data: IterationCreateRequest,
        session: DBAsyncScopedSession,
    ) -> IterationResponse:
        repo = RepoFactory.get_repo(ProjectIterationRepository, session)
        created = await repo.add(
            ews_models.ProjectIteration(
                project_id=to_uuid(project_id),
                name=data.name.strip(),
                goal=data.goal,
                status=_iteration_status(data.status),
                start_date=data.start_date,
                due_date=data.due_date,
            )
        )
        return _iteration_to_response(created)

    @patch('/{project_id}/iterations/{iteration_id}')
    @db_context_session(auto_commit=True)
    async def update_iteration(
        self,
        project_id: str,
        iteration_id: str,
        data: IterationUpdateRequest,
        session: DBAsyncScopedSession,
    ) -> IterationResponse:
        repo = RepoFactory.get_repo(ProjectIterationRepository, session)
        item = await _get_owned(repo, project_id, iteration_id)
        fields = data.as_dict()
        if 'status' in fields:
            fields['status'] = _iteration_status(fields['status'])
        for field, value in fields.items():
            setattr(item, field, value.strip() if field == 'name' else value)
        return _iteration_to_response(await repo.update(item))

    @delete(
        '/{project_id}/iterations/{iteration_id}',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    @db_context_session(auto_commit=True)
    async def delete_iteration(
        self, project_id: str, iteration_id: str, session: DBAsyncScopedSession
    ) -> None:
        """Delete an iteration; its tasks become unplanned."""
        repo = RepoFactory.get_repo(ProjectIterationRepository, session)
        item = await _get_owned(repo, project_id, iteration_id)
        await session.execute(
            update(ews_models.Task)
            .where(ews_models.Task.iteration_id == item.id)
            .values(iteration_id=None)
        )
        await repo.delete(item.id)
