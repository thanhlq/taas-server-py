"""Project and Task HTTP controllers (EWS PPM).

Thin controllers over the existing PPM repositories. A project is created with
or without a workflow template (its sticky *process*) and gets a default
workflow; tasks live in one workflow stage — rules in ``ews.ppm._workflow_service``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional
from uuid import UUID

import db.models.ews as ews_models
from db.models.ews.ews_enums import ProjectStatus
from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter, StatementFilter
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, status
from foundation.http.response import PaginatedResponse, create_paginated_response
from sqlalchemy import ColumnElement, func, or_, select, update

from ews.security import current_scope

from .. import _access as access
from .. import _workflow_service as wfs
from .. import workflow_catalog as catalog
from .._project_status import PROJECT_STATUS_CATALOG, project_status_color
from ..repos import ProjectRepository, RepoFactory, TaskRepository
from ..schemas._project_api import (
    ProjectCreateRequest,
    ProjectListItem,
    ProjectResponse,
    ProjectStatusOption,
    ProjectUpdateRequest,
)
from ..schemas._task_api import TaskCreateRequest, TaskResponse, TaskUpdateRequest
from ._task_support import (
    TASK_COMMENT_OBJECT_TYPE,
    apply_task_update,
    clamp_priority,
    clean_list,
    next_task_code,
    task_to_response,
)

def _to_uuid(value: Optional[str]) -> Optional[UUID]:
    if not value:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def _labels(p: ews_models.Project) -> list[str]:
    """Project labels, stored as ``tags = {'labels': [...]}``."""
    tags = p.tags if isinstance(p.tags, dict) else {}
    labels = tags.get('labels')
    return [str(label) for label in labels] if isinstance(labels, list) else []


def _with_labels(p: ews_models.Project, labels: Optional[list[str]]) -> None:
    """Store labels (trimmed, de-duplicated, order kept) in ``tags.labels``."""
    if labels is None:
        return
    clean = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
    p.tags = {**(p.tags if isinstance(p.tags, dict) else {}), 'labels': clean}


def _project_fields(p: ews_models.Project) -> dict[str, Any]:
    """Fields shared by the list item and the detail response."""
    return {
        'id': str(p.id),
        'name': p.name,
        'code': p.code,
        'status': p.status,
        'status_color': project_status_color(p.status),
        'labels': _labels(p),
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
    p: ews_models.Project,
    stats: Optional[tuple[int, int]] = None,
    locale: Optional[str] = None,
) -> ProjectResponse:
    process = wfs.ProjectProcess.of(p)
    template = catalog.get_template(process.template_id, locale) if process.template_id else None
    return ProjectResponse(
        **_with_progress(_project_fields(p), stats),
        workflow=p.workflow,
        settings=p.settings,
        properties=p.properties,
        template_id=process.template_id,
        template_name=template['name'] if template else None,
        work_item_types=process.work_item_types,
        work_item_types_locked=process.work_item_types_locked,
        allowed_stage_types=process.allowed_stage_types,
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
    """``{project_id: (tasks, done tasks)}`` — by stage type: a task is done in a
    *done*-band stage (or once completed); cancelled / rejected tasks do not count."""
    if not project_ids:
        return {}
    task = ews_models.Task
    done = func.count(task.id).filter(
        or_(task.stage_type.in_(catalog.done_stage_types()), task.completed_at.is_not(None))
    )
    counted = or_(task.stage_type.is_(None), task.stage_type.not_in(catalog.excluded_stage_types()))
    result = await session.execute(
        select(task.project_id, func.count(task.id), done)
        .where(task.project_id.in_(project_ids), task.deleted_at.is_(None), counted)
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
        """Projects of the request's organization the caller may read; ``q`` searches name, code and
        description (case-insensitive)."""
        scope = await current_scope()
        repo = RepoFactory.get_repo(ProjectRepository, session)
        filters: list[StatementFilter | ColumnElement[bool]] = [
            LimitOffset(limit=limit, offset=offset),
            OrderBy(field_name='id', sort_order='desc'),
            await access.readable_projects(scope),
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

    @get('/statuses')
    async def list_project_statuses(self) -> list[ProjectStatusOption]:
        """The project status catalog: every status with its badge colour and group."""
        await current_scope()
        return [
            ProjectStatusOption(value=status.value, color=color.value, group=group.value)
            for status, (color, group) in PROJECT_STATUS_CATALOG.items()
        ]

    @get('/{project_id}')
    @db_context_session(auto_commit=True)
    async def get_project(
        self, project_id: str, session: DBAsyncScopedSession, locale: Optional[str] = None
    ) -> ProjectResponse:
        p = await access.load_project(session, await current_scope(), project_id)
        # Projects made before workflows existed get their process + default workflow now.
        await wfs.ensure_workflows(session, p)
        stats = await _task_stats(session, [p.id])
        return _project_to_response(p, stats.get(p.id), locale)

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_project(
        self, data: ProjectCreateRequest, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        scope = await current_scope()
        await access.require_create_project(scope)
        repo = RepoFactory.get_repo(ProjectRepository, session)
        project = ews_models.Project(
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            name=data.name,
            description=data.description,
            code=data.code,
            status=data.status or ProjectStatus.NEW,
            start_date=data.start_date,
            due_date=data.due_date,
            color=data.color,
            icon_name=data.icon_name,
            default_view=data.default_view,
            client_id=data.client_id,
            user_id=data.user_id,
            last_activity_at=_now(),
        )
        _with_labels(project, data.labels)
        seed = wfs.seed_process(data.template_id, data.locale)
        seed.process.save(project)
        if data.template_id:
            project.default_view = data.default_view or 'kanban'
        created = await repo.add(project)
        await wfs.create_workflow(
            session,
            created,
            name=seed.workflow_name,
            stages=seed.stages,
            workflow_type=seed.workflow_type,
            is_default=True,
            template_id=seed.process.template_id,
        )
        await access.grant_creator(scope, created.id)
        return _project_to_response(created, locale=data.locale)

    @patch('/{project_id}')
    @db_context_session(auto_commit=True)
    async def update_project(
        self, project_id: str, data: ProjectUpdateRequest, session: DBAsyncScopedSession
    ) -> ProjectResponse:
        repo = RepoFactory.get_repo(ProjectRepository, session)
        p = await access.load_project(session, await current_scope(), project_id, access.PROJECT, 'update')
        fields = data.as_dict()
        _with_labels(p, fields.pop('labels', None))
        work_item_types = fields.pop('work_item_types', None)
        if work_item_types is not None:
            await wfs.ensure_workflows(session, p)
            process = wfs.ProjectProcess.of(p)
            process.work_item_types = wfs.checked_work_item_types(process, work_item_types, p)
            process.save(p)
        for field, value in fields.items():
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
        project = await access.load_project(session, await current_scope(), project_id, access.PROJECT, 'delete')
        # Soft delete (audit, Ppm-0011): the project and everything in it stay in the database, unreachable.
        project.deleted_at = datetime.now(UTC)
        await session.flush()
        pid = project.id
        await access.forget_project(pid)


class TaskController(BaseController):
    """Tasks: create (in a column), list by project, quick update, delete."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/')
    @db_context_session(auto_commit=True)
    async def list_tasks(
        self,
        session: DBAsyncScopedSession,
        project_id: str,
        limit: int = 200,
        offset: int = 0,
        q: Optional[str] = None,
    ) -> PaginatedResponse[TaskResponse]:
        """List a project's tasks (oldest first); ``q`` searches name, code and description
        (case-insensitive). Tasks of ``assigned`` workflows the caller is not on are left out."""
        scope = await current_scope()
        project = await access.load_project(session, scope, project_id, access.TASK, 'read')
        workflows = await wfs.ensure_workflows(session, project)
        repo = RepoFactory.get_repo(TaskRepository, session)
        filters: list[StatementFilter] = [
            LimitOffset(limit=limit, offset=offset),
            OrderBy(field_name='id', sort_order='asc'),
        ]
        if q and q.strip():
            filters.append(
                SearchFilter(
                    field_name={'name', 'code', 'description'},
                    value=q.strip(),
                    ignore_case=True,
                )
            )
        viewer = await access.workflow_viewer(scope, project.id)
        if viewer:
            assigned = await wfs.load_assignments(session, [w.id for w in workflows])
            hidden = [
                w.id for w in workflows if not wfs.visible_to(w, assigned.get(w.id, []), viewer, project)
            ]
            if hidden:
                filters.append(
                    or_(ews_models.Task.workflow_id.is_(None), ews_models.Task.workflow_id.not_in(hidden))
                )
        filters.append(ews_models.Task.deleted_at.is_(None))
        rows, total = await repo.list_and_count(
            *filters,
            project_id=project.id,
        )
        return create_paginated_response(
            [task_to_response(t) for t in rows], total=total
        )

    @get('/{task_id}')
    @db_context_session
    async def get_task(self, task_id: str, session: DBAsyncScopedSession) -> TaskResponse:
        t, _ = await access.load_task(session, await current_scope(), task_id)
        return task_to_response(t)

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task(
        self, data: TaskCreateRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        repo = RepoFactory.get_repo(TaskRepository, session)
        project = await access.load_project(session, await current_scope(), data.project_id, access.TASK, 'create')
        project_id = project.id
        refs = await access.task_refs(
            session,
            project_id,
            parent_id=data.parent_id,
            task_list_id=data.task_list_id,
            iteration_id=data.iteration_id,
        )
        process = wfs.ProjectProcess.of(project)
        placement = await wfs.place_task(
            session,
            project,
            workflow_id=data.workflow_id,
            stage_id=data.stage_id,
            stage_type=data.stage_type,
        )
        work_item_type = (
            process.check_work_item_type(data.work_item_type) or process.default_work_item_type()
        )
        sequence_id, code = await next_task_code(session, project_id)
        task = ews_models.Task(
            project_id=project_id,
            name=data.name,
            description=data.description,
            html_text=data.description_html,
            content_type='html' if data.description_html else None,
            code=code,
            sequence_id=sequence_id,
            workflow_id=placement.workflow_id,
            stage_id=placement.stage_id,
            stage_type=placement.stage_type,
            work_item_type=work_item_type,
            parent_id=refs['parent_id'],
            requested_user_id=data.requested_user_id,
            user_id=data.user_id or None,
            task_list_id=refs['task_list_id'],
            iteration_id=refs['iteration_id'],
            tags={'labels': clean_list(data.labels)} if data.labels else None,
            priority=clamp_priority(data.priority),
            start_date=data.start_date,
            due_date=data.due_date,
            estimated_minutes=data.estimated_minutes,
            progress=data.progress or 0,
        )
        created = await repo.add(task)
        await _touch_project(session, created.project_id)
        return task_to_response(created)

    @patch('/{task_id}')
    @db_context_session(auto_commit=True)
    async def update_task(
        self, task_id: str, data: TaskUpdateRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        repo = RepoFactory.get_repo(TaskRepository, session)
        t, project = await access.load_task(session, await current_scope(), task_id, access.TASK, 'update')
        fields = data.as_dict()
        refs = await access.task_refs(
            session, project.id, task_list_id=fields.get('task_list_id'), iteration_id=fields.get('iteration_id')
        )
        for key in ('task_list_id', 'iteration_id'):
            if key in fields:
                fields[key] = refs[key]
        workflow_id = fields.pop('workflow_id', None)
        stage_id = fields.pop('stage_id', None)
        stage_type = fields.pop('stage_type', None)
        if workflow_id or stage_id or stage_type or fields.get('work_item_type'):
            if fields.get('work_item_type'):
                wfs.ProjectProcess.of(project).check_work_item_type(fields['work_item_type'])
            if workflow_id or stage_id or stage_type:
                placement = await wfs.place_task(
                    session,
                    project,
                    workflow_id=workflow_id,
                    stage_id=stage_id,
                    # Moving to another workflow keeps the task's lifecycle position.
                    stage_type=stage_type or (t.stage_type if workflow_id else None),
                    current_workflow_id=t.workflow_id,
                )
                if stage_type and not stage_id and not workflow_id and placement.stage_type != stage_type:
                    # No stage of this type in the task's workflow: keep it where it is.
                    placement = None
                if placement is not None:
                    t.workflow_id = placement.workflow_id
                    t.stage_id = placement.stage_id
                    t.stage_type = placement.stage_type
        apply_task_update(t, fields)
        updated = await repo.update(t)
        await _touch_project(session, updated.project_id)
        return task_to_response(updated)

    @delete('/{task_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task(self, task_id: str, session: DBAsyncScopedSession) -> None:
        task, _ = await access.load_task(session, await current_scope(), task_id, access.TASK, 'delete')
        now = datetime.now(UTC)
        # Soft delete (audit, Ppm-0011): the task, its time logs and its comments are kept, flagged deleted.
        await session.execute(
            update(ews_models.Timelog)
            .where(ews_models.Timelog.task_id == task.id, ews_models.Timelog.deleted_at.is_(None))
            .values(deleted_at=now)
        )
        await session.execute(
            update(ews_models.ProjectComment)
            .where(
                ews_models.ProjectComment.object_type == TASK_COMMENT_OBJECT_TYPE,
                ews_models.ProjectComment.object_id == str(task.id),
                ews_models.ProjectComment.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        task.deleted_at = now
        await session.flush()
        await _touch_project(session, task.project_id)
