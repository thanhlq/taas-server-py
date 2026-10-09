"""Server-side PPM figures (ADR-27): the PPM overview and a project's metrics (counts, workload, schedule health)."""

from __future__ import annotations

from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.http import BaseController, get

from ews.security import current_scope

from .. import _access as access
from .. import _overview
from ..schemas._overview_api import (
    PpmOverviewOut,
    PpmPersonWorkload,
    PpmProjectMetricsOut,
    PpmScheduleHealth,
    PpmStatusCount,
)
from ._project_api import _project_to_list_item, _task_stats
from ._task_support import task_to_response


class PpmOverviewController(BaseController):
    api_prefix = '/api/v1/ppm'
    tags = ('PPM overview',)

    @get(
        '/overview',
        summary='Project total, statuses in use and recently active projects',
    )
    @db_context_session
    async def overview(
        self, session: DBAsyncScopedSession, recent: int = 10
    ) -> PpmOverviewOut:
        data = await _overview.overview(session, await current_scope(), recent)
        stats = await _task_stats(session, [p.id for p in data['recent']])
        return PpmOverviewOut(
            total=data['total'],
            statuses=[PpmStatusCount(**s) for s in data['statuses']],
            recent=[_project_to_list_item(p, stats.get(p.id)) for p in data['recent']],
            open=data['open'],
            at_risk=data['at_risk'],
            my_overdue=data['my_overdue'],
            my_due_week=data['my_due_week'],
        )


class ProjectMetricsController(BaseController):
    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @get(
        '/{project_id}/metrics',
        summary='Counts, attention lists, workload and schedule health of a project',
    )
    @db_context_session
    async def metrics(
        self, project_id: str, session: DBAsyncScopedSession
    ) -> PpmProjectMetricsOut:
        scope = await current_scope()
        project = await access.load_project(
            session, scope, project_id, access.TASK, 'read'
        )
        m = await _overview.project_metrics(session, project)
        return PpmProjectMetricsOut(
            total=m.total,
            done=m.done,
            open=m.open,
            overdue=m.overdue,
            due_soon=m.due_soon,
            progress=m.progress,
            bands=m.bands,
            overdue_tasks=[task_to_response(t) for t in m.overdue_tasks[:10]],
            upcoming_tasks=[task_to_response(t) for t in m.upcoming_tasks[:10]],
            people=[
                PpmPersonWorkload(
                    user=p.user,
                    open=p.open,
                    overdue=p.overdue,
                    done=p.done,
                    total=p.total,
                )
                for p in m.people
            ],
            schedule=PpmScheduleHealth(**m.schedule),
        )
