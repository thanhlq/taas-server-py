"""``/api/v1/tasks`` — work items: create (in a stage, under a parent), list by project, partial update, complete /
reopen, owner + collaborators, delete with the subtree (taas-specs/ppm/work-model/work-model-spec.md). Rules live
in ``ews.ppm._work_items`` (hierarchy, roll-ups, done band) and ``_workflow_service`` (placement); every change
emits its events (Ppm-0008)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

import db.models.ews as ews_models
from advanced_alchemy.filters import LimitOffset, OrderBy, SearchFilter, StatementFilter
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, delete, get, patch, post, put, status
from foundation.http.response import PaginatedResponse, create_paginated_response
from sqlalchemy import or_, select, update

from ews.security import current_scope

from db.models.ppm import PpmApproval, PpmItemType
from foundation.http.context_state import get_request_context

from .. import _access as access
from .. import _checklist_templates as checklist_templates
from .. import _custom_fields as custom_fields
from .. import _time as time
from .. import _events as events
from .. import _item_update as item_update
from .. import _work_items as items
from .. import _workflow_rules as workflow_rules
from .. import _workflow_service as wfs
from ..repos import RepoFactory, TaskRepository
from ..schemas._task_api import (
    TaskAssigneesRequest,
    TaskMoveRequest,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
)
from ._project_api import _touch_project
from ._task_support import (
    TASK_COMMENT_OBJECT_TYPE,
    task_to_response,
    to_uuid,
)


SCHEDULE_FIELDS = (
    'phase_id',
    'duration_days',
    'schedule_mode',
    'constraint_type',
    'constraint_date',
)


async def responses(
    session: DBAsyncScopedSession, tasks: list[ews_models.Task]
) -> list[TaskResponse]:
    """Wire items with collaborators, custom field values and their latest approval status (batched)."""
    if not tasks:
        return []
    ids = [t.id for t in tasks]
    collabs = await items.collaborators(session, ids)
    project = (
        await session.get(ews_models.Project, tasks[0].project_id)
        if tasks[0].project_id
        else None
    )
    values = await custom_fields.values_of(
        session, project.organization_id if project else None, ids
    )
    a = PpmApproval
    statuses: dict[str, str] = {}
    for subject_id, status_ in (
        await session.execute(
            select(a.subject_id, a.status)
            .where(a.subject_type == 'task', a.subject_id.in_([str(i) for i in ids]))
            .order_by(a.requested_at)
        )
    ).all():
        statuses[subject_id] = status_  # the latest wins
    return [
        task_to_response(
            t,
            collabs.get(t.id),
            values.get(t.id),
            statuses.get(str(t.id)),
            time.effort_out(t),
        )
        for t in tasks
    ]


async def _response(
    session: DBAsyncScopedSession, task: ews_models.Task
) -> TaskResponse:
    return (await responses(session, [task]))[0]


def _cf_params() -> list[tuple[str, str]]:
    ctx = get_request_context()
    if ctx is None:
        return []
    return [
        (k, v) for k, v in ctx.req.query_params.multi_items() if k.startswith('cf_')
    ]


class TaskController(BaseController):
    """Work items: create, list by project, quick update, complete / reopen, assignees, delete."""

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
        parent_id: Optional[str] = None,
    ) -> PaginatedResponse[TaskResponse]:
        """List a project's items (oldest first); ``q`` searches name, code and description (case-insensitive);
        ``parent_id`` lists the subtasks of one item. Items of ``assigned`` workflows the caller is not on are left
        out."""
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.TASK, 'read'
        )
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
        if parent_id:
            filters.append(
                ews_models.Task.parent_id == access.parse_uuid(parent_id, 'parent task')
            )
        viewer = await access.workflow_viewer(scope, project.id)
        if viewer:
            assigned = await wfs.load_assignments(session, [w.id for w in workflows])
            teams = await workflow_rules.viewer_teams(session, scope)
            hidden = [
                w.id
                for w in workflows
                if not wfs.visible_to(w, assigned.get(w.id, []), viewer, project, teams)
            ]
            if hidden:
                filters.append(
                    or_(
                        ews_models.Task.workflow_id.is_(None),
                        ews_models.Task.workflow_id.not_in(hidden),
                    )
                )
        filters.append(ews_models.Task.deleted_at.is_(None))
        if project.organization_id is not None:
            filters += await custom_fields.filter_clauses(
                session,
                project.organization_id,
                project.id,
                custom_fields.parse_filters(_cf_params()),
            )
        rows, total = await repo.list_and_count(*filters, project_id=project.id)
        return create_paginated_response(
            await responses(session, list(rows)), total=total
        )

    @get('/{task_id}')
    @db_context_session
    async def get_task(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> TaskResponse:
        t, _ = await access.load_task(session, await current_scope(), task_id)
        return await _response(session, t)

    @post('/', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_task(
        self, data: TaskCreateRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, data.project_id, access.TASK, 'create'
        )
        created = await items.create_item(
            session,
            scope,
            project,
            items.NewItem(
                name=data.name,
                description=data.description,
                description_html=data.description_html,
                description_doc=data.description_doc,
                workflow_id=data.workflow_id,
                stage_id=data.stage_id,
                stage_type=data.stage_type,
                work_item_type=data.work_item_type,
                parent_id=data.parent_id,
                requested_user_id=data.requested_user_id,
                owner=data.user_id,
                collaborators=data.collaborator_ids,
                task_list_id=data.task_list_id,
                iteration_id=data.iteration_id,
                labels=data.labels,
                priority=data.priority,
                start_date=data.start_date,
                due_date=data.due_date,
                estimated_minutes=data.estimated_minutes,
                progress=data.progress,
                progress_mode=item_update.check_progress_mode(data.progress_mode),
                recurrence_rule=item_update.clean_recurrence_rule(data.recurrence_rule),
                schedule={
                    k: v for k in SCHEDULE_FIELDS if (v := getattr(data, k)) is not None
                },
            ),
        )
        await custom_fields.set_values(
            session, scope, project, created, data.custom_fields or {}, creating=True
        )
        template_id = data.checklist_template_id
        if not template_id and project.organization_id is not None:
            default = await session.scalar(
                select(PpmItemType.default_checklist_template_id).where(
                    PpmItemType.organization_id == project.organization_id,
                    PpmItemType.key == created.work_item_type,
                    PpmItemType.archived_at.is_(None),
                )
            )
            template_id = str(default) if default else None
        if template_id:
            template = await checklist_templates.get(session, scope, template_id)
            await checklist_templates.apply(session, scope, created, template)
        return await _response(session, created)

    @patch('/{task_id}')
    @db_context_session(auto_commit=True)
    async def update_task(
        self, task_id: str, data: TaskUpdateRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        t, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        updated = await item_update.update_item(session, scope, t, project, data.as_dict())
        return await _response(session, updated)

    @post(
        '/{task_id}/complete',
        summary='Complete an item (first done-band stage); ?cascade=true completes open subtasks',
    )
    @db_context_session(auto_commit=True)
    async def complete_task(
        self, task_id: str, session: DBAsyncScopedSession, cascade: bool = False
    ) -> TaskResponse:
        scope = await current_scope()
        t, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        await items.complete(session, scope, t, project, cascade=cascade)
        await _touch_project(session, project.id)
        return await _response(session, t)

    @post(
        '/{task_id}/reopen', summary='Reopen a done item (back to its previous stage)'
    )
    @db_context_session(auto_commit=True)
    async def reopen_task(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        t, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        await items.reopen(session, scope, t, project)
        await _touch_project(session, project.id)
        return await _response(session, t)

    @post(
        '/{task_id}/move',
        summary='Move an item (with its subtasks) to another project of the organization',
    )
    @db_context_session(auto_commit=True)
    async def move_task(
        self, task_id: str, data: TaskMoveRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        t, source = await access.load_task(
            session, scope, task_id, access.TASK, 'delete'
        )
        target = await access.load_project(
            session, scope, data.project_id, access.TASK, 'create'
        )
        await items.move_item(session, scope, t, source, target)
        return await _response(session, t)

    @put(
        '/{task_id}/assignees',
        summary='Replace the owner and the collaborators of an item',
    )
    @db_context_session(auto_commit=True)
    async def set_assignees(
        self, task_id: str, data: TaskAssigneesRequest, session: DBAsyncScopedSession
    ) -> TaskResponse:
        scope = await current_scope()
        t, project = await access.load_task(
            session, scope, task_id, access.TASK, 'update'
        )
        before = items.state(t)
        await items.set_assignees(
            session,
            scope,
            t,
            owner=data.owner_id,
            collaborator_list=data.collaborator_ids,
        )
        await items.record_update(session, scope, t, project, before)
        await _touch_project(session, project.id)
        return await _response(session, t)

    @delete('/{task_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_task(self, task_id: str, session: DBAsyncScopedSession) -> None:
        scope = await current_scope()
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, 'delete'
        )
        now = datetime.now(UTC)
        subtree = await items.delete_subtree(session, task)
        ids = [task.id, *subtree]
        # Soft delete (audit, Ppm-0011): the items, their time logs and comments are kept, flagged deleted.
        await session.execute(
            update(ews_models.Timelog)
            .where(
                ews_models.Timelog.task_id.in_(ids),
                ews_models.Timelog.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        await session.execute(
            update(ews_models.ProjectComment)
            .where(
                ews_models.ProjectComment.object_type == TASK_COMMENT_OBJECT_TYPE,
                ews_models.ProjectComment.object_id.in_([str(i) for i in ids]),
                ews_models.ProjectComment.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        task.deleted_at = now
        await session.flush()
        await items.refresh_rollups(session, task.parent_id)
        await events.emit(
            session,
            scope,
            'ppm.task.deleted',
            'task',
            task.id,
            project_id=project.id,
            data={
                'code': task.code,
                'name': task.name,
                'subtree': [str(i) for i in subtree],
            },
        )
        await _touch_project(session, task.project_id)


__all__ = ['TaskController', 'to_uuid']
