"""Bulk actions and CSV exports of projects and items (common UI "⋯" menus, Ppm-0014). Each project is checked on
its own (404 / 403 per id, reported in ``failed``); every change emits its events like a single edit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import db.models.ews as ews_models
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, HTTPException
from foundation.http import BaseController, get, post
from foundation.http.context import Context
from sqlalchemy import select

from ews.security import current_scope
from ews.shared import raw_response

from .. import _access as access
from .. import _events as events
from .. import _export
from .. import _work_items as items
from ..schemas._bulk_api import PpmBulkFailure, PpmBulkOut, PpmProjectBulkIn
from .._projects import with_labels
from ._project_api import _labels, _task_stats

MAX_BULK = 200


class ProjectBulkController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @post(
        '/bulk',
        summary='Delete or update several projects (status, responsible, labels)',
    )
    @db_context_session(auto_commit=True)
    async def bulk(
        self, data: PpmProjectBulkIn, session: DBAsyncScopedSession
    ) -> PpmBulkOut:
        scope = await current_scope()
        if data.action not in ('delete', 'update'):
            raise ClientException(detail='action must be delete or update')
        if len(data.ids) > MAX_BULK:
            raise ClientException(detail=f'at most {MAX_BULK} projects at once')
        out = PpmBulkOut()
        for project_id in dict.fromkeys(data.ids):
            try:
                async with session.begin_nested():
                    if data.action == 'delete':
                        project = await access.load_project(
                            session, scope, project_id, access.PROJECT, 'delete'
                        )
                        project.deleted_at = datetime.now(UTC)
                        await session.flush()
                        await events.emit(
                            session,
                            scope,
                            'ppm.project.deleted',
                            'project',
                            project.id,
                            project_id=project.id,
                            data={
                                'name': project.name,
                                'code': project.code,
                                'bulk': True,
                            },
                        )
                        await access.forget_project(project.id)
                    else:
                        project = await access.load_project(
                            session, scope, project_id, access.PROJECT, 'update'
                        )
                        before = {
                            'status': project.status,
                            'user_id': project.user_id,
                            'labels': _labels(project),
                        }
                        if data.status is not None:
                            project.status = data.status
                        if data.user_id is not None:
                            project.user_id = data.user_id.strip() or None
                        if data.add_labels or data.remove_labels:
                            drop = {label.strip() for label in data.remove_labels}
                            labels = [lb for lb in _labels(project) if lb not in drop]
                            with_labels(project, [*labels, *data.add_labels])
                        project.last_activity_at = items.now()
                        await session.flush()
                        changes = events.diff(
                            before,
                            {
                                'status': project.status,
                                'user_id': project.user_id,
                                'labels': _labels(project),
                            },
                        )
                        if changes:
                            await events.emit(
                                session,
                                scope,
                                'ppm.project.updated',
                                'project',
                                project.id,
                                project_id=project.id,
                                changes=changes,
                                data={
                                    'name': project.name,
                                    'code': project.code,
                                    'bulk': True,
                                },
                            )
                out.done.append(str(project.id))
            except HTTPException as error:
                out.failed.append(
                    PpmBulkFailure(
                        id=project_id, status=error.status_code, detail=error.detail
                    )
                )
        return out

    @get(
        '/export.csv', summary='CSV of the projects the caller can read (or of ``ids``)'
    )
    @db_context_session
    async def export_projects(
        self, ctx: Context, session: DBAsyncScopedSession, ids: str | None = None
    ) -> Any:
        scope = await current_scope()
        p = ews_models.Project
        query = select(p).where(
            await access.readable_projects(scope), p.kind == 'project'
        )
        wanted = [i for i in (ids or '').split(',') if i.strip()]
        if wanted:
            query = query.where(
                p.id.in_([access.parse_uuid(i, 'project') for i in wanted])
            )
        rows = list((await session.scalars(query.order_by(p.name).limit(5000))).all())
        stats = await _task_stats(session, [r.id for r in rows])
        body = _export.to_csv(
            [
                'Code',
                'Name',
                'Status',
                'Responsible',
                'Start',
                'Due',
                'Progress %',
                'Items',
                'Done',
                'Labels',
                'Last activity',
            ],
            (
                [
                    r.code,
                    r.name,
                    r.status,
                    r.user_id,
                    r.start_date,
                    r.due_date,
                    round(stats.get(r.id, (0, 0))[1] * 100 / stats[r.id][0])
                    if stats.get(r.id, (0, 0))[0]
                    else 0,
                    stats.get(r.id, (0, 0))[0],
                    stats.get(r.id, (0, 0))[1],
                    _labels(r),
                    r.last_activity_at,
                ]
                for r in rows
            ),
        )
        return raw_response(
            body,
            media_type='text/csv; charset=utf-8',
            request=ctx.req,
            headers={
                'content-disposition': 'attachment; filename="projects.csv"',
                'cache-control': 'no-store',
            },
        )


class TaskExportController(BaseController):
    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @get('/export.csv', summary="CSV of a project's items")
    @db_context_session
    async def export_tasks(
        self, project_id: str, ctx: Context, session: DBAsyncScopedSession
    ) -> Any:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.TASK, 'read'
        )
        t = ews_models.Task
        rows = list(
            (
                await session.scalars(
                    select(t)
                    .where(t.project_id == project.id, t.deleted_at.is_(None))
                    .order_by(t.sequence_id)
                    .limit(20000)
                )
            ).all()
        )
        stages = {
            s.id: s.name
            for s in (
                await session.scalars(
                    select(ews_models.WorkflowStage).where(
                        ews_models.WorkflowStage.id.in_(
                            {r.stage_id for r in rows if r.stage_id}
                        )
                    )
                )
            ).all()
        }
        codes = {r.id: r.code for r in rows}
        body = _export.to_csv(
            [
                'Code',
                'Name',
                'Type',
                'Status',
                'Parent',
                'Owner',
                'Priority',
                'Start',
                'Due',
                'Estimate (min)',
                'Actual (min)',
                'Progress %',
                'Completed',
            ],
            (
                [
                    r.code,
                    r.name,
                    r.work_item_type,
                    stages.get(r.stage_id),
                    codes.get(r.parent_id),
                    r.user_id,
                    r.priority,
                    r.start_date,
                    r.due_date,
                    r.estimated_minutes,
                    r.actual_minutes,
                    r.progress,
                    r.completed_at,
                ]
                for r in rows
            ),
        )
        name = (project.code or 'project').lower()
        return raw_response(
            body,
            media_type='text/csv; charset=utf-8',
            request=ctx.req,
            headers={
                'content-disposition': f'attachment; filename="{name}-items.csv"',
                'cache-control': 'no-store',
            },
        )
