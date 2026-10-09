"""Schedule routes (taas-specs/ppm/schedule/schedule-spec.md §7): the Gantt payload, schedule settings + preview, batch
changes of a Gantt drop, phases, dependency links of an item. Rules live in ``ews.ppm._schedule`` (engine
``_schedule_engine``); capabilities ``gantt`` and ``dependencies`` (Ppm-0009) are enforced here. Item links are under
``/tasks/{id}/dependencies`` (``/links`` = the web links of V1 files, ADR-41)."""

from __future__ import annotations

from typing import Any

import db.models.ews as ews_models
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from foundation.http import BaseController, delete, get, patch, post, put, status
from sqlalchemy import select

from ews.authz import EwsResources
from ews.security import RequestScope, current_scope

from .. import _access as access
from .. import _schedule as schedule
from .. import _settings
from .. import _work_items as items
from ..schemas._schedule_api import (
    PpmDependencyIn,
    PpmDependencyUpdateIn,
    PpmItemLinkOut,
    PpmPhaseIn,
    PpmPhaseOrderIn,
    PpmPhaseOut,
    PpmScheduleChangeOut,
    PpmScheduleChangesIn,
    PpmScheduleChangesOut,
    PpmScheduleOut,
    PpmSchedulePreviewOut,
    PpmScheduleSavedOut,
    PpmScheduleSettingsIn,
    PpmScheduleSettingsOut,
)
from ._project_api import _touch_project

SCHEDULE = EwsResources.SCHEDULE.value


async def _project(
    session: DBAsyncScopedSession, project_id: str, resource: str, action: str
) -> tuple[RequestScope, ews_models.Project]:
    scope = await current_scope()
    await _settings.require_capability(session, scope, 'gantt')
    return scope, await access.load_project(
        session, scope, project_id, resource, action
    )


def _changes(rows: list[dict[str, Any]]) -> list[PpmScheduleChangeOut]:
    return [PpmScheduleChangeOut(**row) for row in rows]


def _settings_patch(data: PpmScheduleSettingsIn) -> dict[str, Any]:
    patch_ = {
        k: v for k, v in data.as_dict().items() if k not in ('clear', 'base_version')
    }
    for key in data.clear or []:
        patch_[key] = None
    return patch_


class ProjectScheduleController(BaseController):
    """The schedule of a project: Gantt payload, settings, preview, batch changes, phases."""

    api_prefix = '/api/v1/projects'
    tags = ('Project schedule',)

    @get(
        '/{project_id}/schedule',
        summary='Gantt payload: phases, items (plan, forecast, float), links',
    )
    @db_context_session
    async def get_schedule(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmScheduleOut:
        _, project = await _project(session, project_id, SCHEDULE, 'read')
        return PpmScheduleOut(**await schedule.read(session, project))

    @patch(
        '/{project_id}/schedule/settings',
        summary='Mode, critical threshold, default duration',
    )
    @db_context_session(auto_commit=True)
    async def update_settings(
        self,
        project_id: str,
        data: PpmScheduleSettingsIn,
        session: DBAsyncScopedSession,
    ) -> PpmScheduleSavedOut:
        scope, project = await _project(session, project_id, SCHEDULE, 'update')
        changes = await schedule.update_settings(
            session,
            scope,
            project,
            _settings_patch(data),
            base_version=data.base_version,
        )
        return PpmScheduleSavedOut(
            schedule_version=project.schedule_version or 0,
            settings=PpmScheduleSettingsOut(**schedule.settings_of(project)),
            changes=_changes(changes),
        )

    @post(
        '/{project_id}/schedule/preview',
        summary='What a settings change would move (nothing saved)',
    )
    @db_context_session
    async def preview(
        self,
        project_id: str,
        data: PpmScheduleSettingsIn,
        session: DBAsyncScopedSession,
    ) -> PpmSchedulePreviewOut:
        _, project = await _project(session, project_id, SCHEDULE, 'read')
        out = await schedule.preview_settings(session, project, _settings_patch(data))
        return PpmSchedulePreviewOut(**{**out, 'changes': _changes(out['changes'])})

    @post(
        '/{project_id}/schedule/changes',
        summary='Save a Gantt drop (several items), then recalculate',
    )
    @db_context_session(auto_commit=True)
    async def save_changes(
        self, project_id: str, data: PpmScheduleChangesIn, session: DBAsyncScopedSession
    ) -> PpmScheduleChangesOut:
        scope, project = await _project(session, project_id, access.TASK, 'update')
        schedule.check_version(project, data.base_version)
        if len(data.changes) > 500:
            raise ClientException(detail='at most 500 changes per request')
        ids = [access.parse_uuid(c.task_id, 'task') for c in data.changes]
        tasks = {
            t.id: t
            for t in (
                await session.scalars(
                    select(ews_models.Task).where(
                        ews_models.Task.id.in_(ids),
                        ews_models.Task.project_id == project.id,
                        ews_models.Task.deleted_at.is_(None),
                    )
                )
            ).all()
        }
        updated: list[str] = []
        with schedule.batch():
            for change, tid in zip(data.changes, ids, strict=True):
                task = tasks.get(tid)
                if task is None:
                    raise ClientException(
                        detail=f'task {change.task_id} is not in this project'
                    )
                fields = {
                    k: v
                    for k, v in change.as_dict().items()
                    if k not in ('task_id', 'clear')
                }
                clear = set(change.clear or []) & {
                    'phase_id',
                    'duration_days',
                    'constraint_type',
                    'constraint_date',
                }
                await schedule.check_item_fields(session, task, project, fields, clear)
                before = items.state(task)
                if 'progress' in fields:
                    fields['progress'] = max(0, min(100, int(fields['progress'])))
                for key, value in fields.items():
                    setattr(task, key, value)
                for key in clear:
                    setattr(task, key, None)
                await session.flush()
                await items.refresh_rollups(session, task.parent_id)
                await items.record_update(session, scope, task, project, before)
                updated.append(str(task.id))
        moved = await schedule.recalculate(session, scope, project, cause='gantt')
        if updated and not moved:
            project.schedule_version = (project.schedule_version or 0) + 1
        await _touch_project(session, project.id)
        return PpmScheduleChangesOut(
            schedule_version=project.schedule_version or 0,
            updated=updated,
            changes=_changes(moved),
        )

    # --- phases -----------------------------------------------------------------------------------

    @get('/{project_id}/phases', summary='Phases of a project in order')
    @db_context_session
    async def list_phases(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> list[PpmPhaseOut]:
        _, project = await _project(session, project_id, SCHEDULE, 'read')
        counts = await schedule.phase_counts(session, project.id)
        return [
            PpmPhaseOut(**schedule.phase_to_out(p, counts.get(p.id, 0)))
            for p in await schedule.phases_of(session, project.id)
        ]

    @post('/{project_id}/phases', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_phase(
        self, project_id: str, data: PpmPhaseIn, session: DBAsyncScopedSession
    ) -> PpmPhaseOut:
        scope, project = await _project(session, project_id, SCHEDULE, 'update')
        fields = {k: v for k, v in data.as_dict().items() if k != 'clear'}
        row = await schedule.create_phase(session, scope, project, fields)
        return PpmPhaseOut(**schedule.phase_to_out(row))

    @put(
        '/{project_id}/phases/order',
        summary='Reorder: every phase id once, in the new order',
    )
    @db_context_session(auto_commit=True)
    async def order_phases(
        self, project_id: str, data: PpmPhaseOrderIn, session: DBAsyncScopedSession
    ) -> list[PpmPhaseOut]:
        scope, project = await _project(session, project_id, SCHEDULE, 'update')
        rows = await schedule.order_phases(session, scope, project, data.phase_ids)
        counts = await schedule.phase_counts(session, project.id)
        return [
            PpmPhaseOut(**schedule.phase_to_out(p, counts.get(p.id, 0))) for p in rows
        ]

    @patch('/{project_id}/phases/{phase_id}')
    @db_context_session(auto_commit=True)
    async def update_phase(
        self,
        project_id: str,
        phase_id: str,
        data: PpmPhaseIn,
        session: DBAsyncScopedSession,
    ) -> PpmPhaseOut:
        scope, project = await _project(session, project_id, SCHEDULE, 'update')
        row = await schedule.load_phase(session, project, phase_id)
        fields = {k: v for k, v in data.as_dict().items() if k != 'clear'}
        row = await schedule.update_phase(
            session, scope, project, row, fields, set(data.clear or [])
        )
        counts = await schedule.phase_counts(session, project.id)
        return PpmPhaseOut(**schedule.phase_to_out(row, counts.get(row.id, 0)))

    @delete('/{project_id}/phases/{phase_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_phase(
        self, project_id: str, phase_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope, project = await _project(session, project_id, SCHEDULE, 'update')
        row = await schedule.load_phase(session, project, phase_id)
        await schedule.delete_phase(session, scope, project, row)


class TaskDependencyController(BaseController):
    """Links of an item (Ppm-1020…1022): dependencies FS · SS · FF · SF with lag, ``relates`` · ``duplicates`` ·
    ``blocks``; cycle check on create."""

    api_prefix = '/api/v1/tasks'
    tags = ('Tasks',)

    @staticmethod
    async def _task(
        session: DBAsyncScopedSession, task_id: str, action: str
    ) -> tuple[RequestScope, ews_models.Task, ews_models.Project]:
        scope = await current_scope()
        await _settings.require_capability(session, scope, 'dependencies')
        task, project = await access.load_task(
            session, scope, task_id, access.TASK, action
        )
        return scope, task, project

    @staticmethod
    def _out(
        row: Any, tasks: dict[Any, ews_models.Task], task_id: Any
    ) -> PpmItemLinkOut:
        direction = 'predecessor' if row.target_task_id == task_id else 'successor'
        return PpmItemLinkOut(**schedule.link_to_out(row, tasks), direction=direction)

    @get('/{task_id}/dependencies', summary='Links of an item, both directions')
    @db_context_session
    async def list_dependencies(
        self, task_id: str, session: DBAsyncScopedSession
    ) -> list[PpmItemLinkOut]:
        _, task, _ = await self._task(session, task_id, 'read')
        rows, tasks = await schedule.task_links(session, task.id)
        return [self._out(r, tasks, task.id) for r in rows]

    @post('/{task_id}/dependencies', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create_dependency(
        self, task_id: str, data: PpmDependencyIn, session: DBAsyncScopedSession
    ) -> PpmItemLinkOut:
        scope, task, project = await self._task(session, task_id, 'update')
        if bool(data.predecessor_id) == bool(data.successor_id):
            raise ClientException(detail='give predecessor_id or successor_id')
        other_id = data.predecessor_id or data.successor_id
        other, _ = await access.load_task(session, scope, other_id, access.TASK, 'read')
        source, target = (other, task) if data.predecessor_id else (task, other)
        row = await schedule.create_link(
            session, scope, project, source, target, data.type, data.lag_days
        )
        await _touch_project(session, project.id)
        return self._out(row, {task.id: task, other.id: other}, task.id)

    @patch('/{task_id}/dependencies/{link_id}')
    @db_context_session(auto_commit=True)
    async def update_dependency(
        self,
        task_id: str,
        link_id: str,
        data: PpmDependencyUpdateIn,
        session: DBAsyncScopedSession,
    ) -> PpmItemLinkOut:
        scope, task, project = await self._task(session, task_id, 'update')
        row = await schedule.load_link(session, task.id, link_id)
        row = await schedule.update_link(
            session, scope, project, row, kind=data.type, lag=data.lag_days
        )
        _, tasks = await schedule.task_links(session, task.id)
        return self._out(row, tasks, task.id)

    @delete('/{task_id}/dependencies/{link_id}', status_code=status.HTTP_204_NO_CONTENT)
    @db_context_session(auto_commit=True)
    async def delete_dependency(
        self, task_id: str, link_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope, task, project = await self._task(session, task_id, 'update')
        row = await schedule.load_link(session, task.id, link_id)
        await schedule.delete_link(session, scope, project.id, row)


__all__ = ['ProjectScheduleController', 'TaskDependencyController']
