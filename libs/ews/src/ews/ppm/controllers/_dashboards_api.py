"""Dashboards, widgets, reports and exports (taas-specs/ppm/reporting/dashboards-reports-spec.md §7). Rules in
``ews.ppm._dashboards`` / ``_widgets`` / ``_reports`` / ``_stats``. Custom dashboards, reports and exports need the
``dashboards`` capability; the system dashboards (PPM overview, My dashboard, project Overview tab) are open to every
reader, their widgets read data with the viewer's own permissions."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmDashboard
from foundation.db.advanced_db_manager import db_context_session
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from foundation.http import BaseController, delete, get, patch, post, put, status

from ews.security import RequestScope, current_scope
from ews.shared import file_response

from .. import _access as access
from .. import _dashboards as dashboards
from .. import _reports as reports
from .. import _settings
from .. import _stats as stats
from .. import _widgets as widgets
from ..schemas._dashboards_api import (
    PpmDashboardCopyIn,
    PpmDashboardIn,
    PpmDashboardItemOut,
    PpmDashboardOut,
    PpmDashboardPatch,
    PpmDashboardShareOut,
    PpmDashboardSharesIn,
    PpmDataOut,
    PpmExportIn,
    PpmReportOut,
    PpmReportRunIn,
    PpmWidgetCatalogOut,
    PpmWidgetPreviewIn,
    PpmWidgetSourceOut,
    PpmWidgetTypeOut,
)


async def _scope(
    session: DBAsyncScopedSession, *, capability: bool = True
) -> RequestScope:
    scope = await current_scope()
    if capability:
        await _settings.require_capability(session, scope, 'dashboards')
    return scope


def _data(result: widgets.Result) -> PpmDataOut:
    return PpmDataOut(**result.as_dict())


def _filters(raw: Optional[str]) -> dict[str, Any]:
    """``?filters=`` = URL-encoded JSON of the filter bar."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ClientException(
            detail='filters must be JSON', extra={'code': 'invalid_query'}
        ) from exc
    return widgets.clean_filters(value)


def _out(view: dashboards.View) -> PpmDashboardOut:
    row = view.row
    return PpmDashboardOut(
        id=str(row.id) if row else f'{dashboards.SYSTEM_PREFIX}{view.system_key}',
        name=view.name,
        scope_type=view.scope_type,
        scope_id=str(view.scope_id) if view.scope_id else None,
        system_key=view.system_key,
        description=row.description if row else None,
        owner=row.owner if row else None,
        visibility=row.visibility if row else 'scope',
        layout=view.layout,
        filters=view.filters,
        version=row.version if row else 0,
        can_edit=view.can_edit,
        is_owner=view.is_owner,
        updated_at=row.updated_at if row else None,
    )


def _item(row: PpmDashboard, can_edit: bool) -> PpmDashboardItemOut:
    return PpmDashboardItemOut(
        id=str(row.id),
        name=row.name,
        scope_type=row.scope_type,
        scope_id=str(row.scope_id) if row.scope_id else None,
        owner=row.owner,
        visibility=row.visibility,
        can_edit=can_edit,
        updated_at=row.updated_at,
    )


async def _view(
    session: DBAsyncScopedSession, dashboard_id: str, project_id: Optional[str]
) -> tuple[RequestScope, dashboards.View]:
    system = dashboard_id.startswith(dashboards.SYSTEM_PREFIX)
    scope = await _scope(session, capability=not system)
    project = (
        await access.load_project(session, scope, project_id) if project_id else None
    )
    view = await dashboards.view_of(session, scope, dashboard_id, project=project)
    if view.scope_type == 'project' and view.scope_id is None:
        raise ClientException(
            detail='project_id is required for a project dashboard',
            extra={'code': 'invalid_query'},
        )
    return scope, view


async def _widget_result(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    view: dashboards.View,
    widget_id: str,
    filters: dict[str, Any],
) -> widgets.Result:
    widget = dashboards.widget_of(view, widget_id)
    if widget['type'] == 'text':
        return widgets.Result([], [], 0)
    capability = dashboards.WIDGET_CAPABILITY.get(widget['type'])
    if capability:
        await _settings.require_capability(session, scope, capability)
    forced = (
        {'project_ids': [str(view.scope_id)]}
        if view.scope_type == 'project' and view.scope_id
        else {}
    )
    return await widgets.run(
        session, scope, widget['query'], view.filters, filters, forced
    )


class PpmWidgetController(BaseController):
    """Widget catalog and the preview of an unsaved widget."""

    api_prefix = '/api/v1/ppm'
    tags = ('PPM dashboards',)

    @get(
        '/widget-types',
        summary='Widget types, data sources (measures, metrics, group by) and filters',
    )
    @db_context_session
    async def catalog(self, session: DBAsyncScopedSession) -> PpmWidgetCatalogOut:
        await _scope(session, capability=False)
        return PpmWidgetCatalogOut(
            types=[
                PpmWidgetTypeOut(
                    type=t['type'],
                    sources=list(t['sources']),
                    w=t['w'],
                    h=t['h'],
                    capability=dashboards.WIDGET_CAPABILITY.get(t['type']),
                )
                for t in dashboards.WIDGET_TYPES
            ],
            sources=[
                PpmWidgetSourceOut(
                    source=k,
                    measures=list(v.get('measure', ())),
                    metrics=list(v.get('metric', ())),
                    group_by=list(v.get('group_by', ())),
                )
                for k, v in widgets.SOURCES.items()
            ],
            filters=list(widgets.FILTERS),
            max_widgets=dashboards.MAX_WIDGETS,
            columns=dashboards.COLUMNS,
        )

    @post(
        '/widget-data',
        summary='Data of an unsaved widget (editor preview)',
        status_code=status.HTTP_200_OK,
    )
    @db_context_session
    async def preview(
        self, data: PpmWidgetPreviewIn, session: DBAsyncScopedSession
    ) -> PpmDataOut:
        scope = await _scope(session)
        forced = {}
        if data.project_id:
            project = await access.load_project(session, scope, data.project_id)
            forced = {'project_ids': [str(project.id)]}
        return _data(
            await widgets.run(session, scope, data.query, data.filters or {}, forced)
        )


class PpmDashboardController(BaseController):
    """Dashboards: list, create, read, change, delete, copy, shares, widget data and export."""

    api_prefix = '/api/v1/ppm/dashboards'
    tags = ('PPM dashboards',)

    @get(
        '/',
        summary='System dashboards + the dashboards the caller may open (optionally of one scope)',
    )
    @db_context_session
    async def list_dashboards(
        self,
        session: DBAsyncScopedSession,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> list[PpmDashboardItemOut]:
        scope = await _scope(session)
        sid = access.parse_uuid(scope_id, 'scope') if scope_id else None
        keys, rows = await dashboards.list_for(session, scope, scope_type, sid)
        system = [
            PpmDashboardItemOut(
                id=f'{dashboards.SYSTEM_PREFIX}{k}',
                name=k,
                scope_type=dashboards.SYSTEM[k]['scope_type'],
                system_key=k,
                visibility='scope',
            )
            for k in keys
        ]
        return [*system, *(_item(r, can_edit) for r, can_edit in rows)]

    @post('/', summary='Create a dashboard', status_code=status.HTTP_201_CREATED)
    @db_context_session(auto_commit=True)
    async def create(
        self, data: PpmDashboardIn, session: DBAsyncScopedSession
    ) -> PpmDashboardOut:
        scope = await _scope(session)
        row = await dashboards.create(
            session,
            scope,
            name=data.name,
            scope_type=data.scope_type,
            scope_id=access.parse_uuid(data.scope_id, 'project')
            if data.scope_id
            else None,
            layout=data.layout,
            filters=data.filters,
            visibility=data.visibility,
            description=data.description,
        )
        return _out(await dashboards.view_of(session, scope, str(row.id)))

    @get(
        '/{dashboard_id}',
        summary='A dashboard (``system:<key>``: a system dashboard; ``project_id`` for project ones)',
    )
    @db_context_session
    async def get_dashboard(
        self,
        dashboard_id: str,
        session: DBAsyncScopedSession,
        project_id: Optional[str] = None,
    ) -> PpmDashboardOut:
        _, view = await _view(session, dashboard_id, project_id)
        return _out(view)

    @patch(
        '/{dashboard_id}',
        summary='Rename, change layout / filters / visibility (version)',
    )
    @db_context_session(auto_commit=True)
    async def update(
        self, dashboard_id: str, data: PpmDashboardPatch, session: DBAsyncScopedSession
    ) -> PpmDashboardOut:
        scope, view = await _view(session, dashboard_id, None)
        # omitted / null = unchanged; an empty description or ``{}`` filters clear them
        patch_ = {
            k: v for k, v in data.as_dict().items() if k != 'version' and v is not None
        }
        await dashboards.update(
            session, scope, view, version=data.version, patch=patch_
        )
        return _out(await dashboards.view_of(session, scope, dashboard_id))

    @delete(
        '/{dashboard_id}',
        summary='Delete a dashboard',
        status_code=status.HTTP_204_NO_CONTENT,
    )
    @db_context_session(auto_commit=True)
    async def delete_dashboard(
        self, dashboard_id: str, session: DBAsyncScopedSession
    ) -> None:
        scope, view = await _view(session, dashboard_id, None)
        await dashboards.delete(session, scope, view)

    @post(
        '/{dashboard_id}/copy',
        summary='Copy (a system dashboard: copy to customize)',
        status_code=201,
    )
    @db_context_session(auto_commit=True)
    async def copy(
        self,
        dashboard_id: str,
        data: PpmDashboardCopyIn,
        session: DBAsyncScopedSession,
        project_id: Optional[str] = None,
    ) -> PpmDashboardOut:
        scope, view = await _view(session, dashboard_id, project_id)
        row = await dashboards.copy_of(
            session,
            scope,
            view,
            name=data.name,
            scope_type=data.scope_type,
            scope_id=access.parse_uuid(data.scope_id, 'project')
            if data.scope_id
            else None,
        )
        return _out(await dashboards.view_of(session, scope, str(row.id)))

    @get('/{dashboard_id}/shares', summary='Who the dashboard is shared with')
    @db_context_session
    async def shares(
        self, dashboard_id: str, session: DBAsyncScopedSession
    ) -> list[PpmDashboardShareOut]:
        _, view = await _view(session, dashboard_id, None)
        if view.row is None:
            return []
        rows = await dashboards.shares_of(session, view.row.id)
        return [
            PpmDashboardShareOut(principal_id=r.principal_id, can_edit=r.can_edit)
            for r in rows
        ]

    @put('/{dashboard_id}/shares', summary='Replace the shares (owner)')
    @db_context_session(auto_commit=True)
    async def replace_shares(
        self,
        dashboard_id: str,
        data: PpmDashboardSharesIn,
        session: DBAsyncScopedSession,
    ) -> list[PpmDashboardShareOut]:
        scope, view = await _view(session, dashboard_id, None)
        rows = await dashboards.replace_shares(
            session, scope, view, [s.as_dict() for s in data.shares]
        )
        return [
            PpmDashboardShareOut(principal_id=r.principal_id, can_edit=r.can_edit)
            for r in rows
        ]

    @get(
        '/{dashboard_id}/widgets/{widget_id}/data',
        summary='Data of one widget (viewer permissions)',
    )
    @db_context_session(auto_commit=True)
    async def widget_data(
        self,
        dashboard_id: str,
        widget_id: str,
        session: DBAsyncScopedSession,
        filters: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> PpmDataOut:
        scope, view = await _view(session, dashboard_id, project_id)
        return _data(
            await _widget_result(session, scope, view, widget_id, _filters(filters))
        )

    @post(
        '/{dashboard_id}/widgets/{widget_id}/export',
        summary='CSV / XLSX of one widget',
        status_code=200,
    )
    @db_context_session(auto_commit=True)
    async def widget_export(
        self,
        dashboard_id: str,
        widget_id: str,
        data: PpmExportIn,
        session: DBAsyncScopedSession,
    ) -> Any:
        scope, view = await _view(session, dashboard_id, data.project_id)
        await _settings.require_capability(session, scope, 'dashboards')
        result = await _widget_result(
            session, scope, view, widget_id, widgets.clean_filters(data.filters or {})
        )
        return file_response(
            *reports.render(
                result, data.format, labels=data.labels, title=data.title or widget_id
            )
        )


class PpmReportController(BaseController):
    """Standard reports: catalog, run, export."""

    api_prefix = '/api/v1/ppm/reports'
    tags = ('PPM reports',)

    @get('/', summary='Report catalog (labels in the web)')
    @db_context_session
    async def catalog(self, session: DBAsyncScopedSession) -> list[PpmReportOut]:
        await _scope(session)
        return [
            PpmReportOut(key=k, params=list(v['params']))
            for k, v in reports.REPORTS.items()
        ]

    @post(
        '/{report_key}/run',
        summary='Run a report (≤ 10 000 rows)',
        status_code=status.HTTP_200_OK,
    )
    @db_context_session
    async def run(
        self, report_key: str, data: PpmReportRunIn, session: DBAsyncScopedSession
    ) -> PpmDataOut:
        scope = await _scope(session)
        return _data(await reports.run(session, scope, report_key, data.params or {}))

    @post(
        '/{report_key}/export',
        summary='CSV / XLSX of a report',
        status_code=status.HTTP_200_OK,
    )
    @db_context_session
    async def export(
        self, report_key: str, data: PpmExportIn, session: DBAsyncScopedSession
    ) -> Any:
        scope = await _scope(session)
        result = await reports.run(session, scope, report_key, data.params or {})
        return file_response(
            *reports.render(
                result, data.format, labels=data.labels, title=data.title or report_key
            )
        )


class ProjectSeriesController(BaseController):
    """Burnup, burndown and throughput of a project from the daily statistics."""

    api_prefix = '/api/v1/projects'
    tags = ('Projects',)

    @get(
        '/{project_id}/metrics/series',
        summary='Series from the daily statistics (burnup · burndown · throughput)',
    )
    @db_context_session(auto_commit=True)
    async def series(
        self,
        project_id: str,
        session: DBAsyncScopedSession,
        series: str = 'burnup',
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        iteration_id: Optional[str] = None,
    ) -> PpmDataOut:
        scope = await current_scope()
        project: ews_models.Project = await access.load_project(
            session, scope, project_id, access.TASK, 'read'
        )
        filters = widgets.clean_filters({'date_from': date_from, 'date_to': date_to})
        data = await stats.series(
            session,
            project,
            series,
            start=date.fromisoformat(filters['date_from'])
            if filters.get('date_from')
            else None,
            end=date.fromisoformat(filters['date_to'])
            if filters.get('date_to')
            else None,
            iteration_id=UUID(iteration_id) if iteration_id else None,
        )
        points = data['points']
        keys = [k for k in (points[0] if points else {}) if k != 'date']
        return PpmDataOut(
            columns=[
                {'key': 'date', 'type': 'date'},
                *({'key': k, 'type': data['unit']} for k in keys),
            ],
            rows=[[p['date'].isoformat(), *(p.get(k) for k in keys)] for p in points],
            total=len(points),
            as_of=data['as_of'],
        )
