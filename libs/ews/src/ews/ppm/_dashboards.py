"""PPM dashboards (taas-specs/ppm/reporting/dashboards-reports-spec.md §2–§4, ADR-45): the widget catalog, system
dashboards (code, read-only, *Copy to customize*), personal / project / organization dashboards with a 12-column
layout (≤ 24 widgets), sharing (private · shared with users · whole scope) and widget data run with the **viewer's**
permissions (sharing never elevates). Queries: ``_widgets``."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmDashboard, PpmDashboardShare
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import or_, select

from ews.authz import EwsResources
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException

from . import _access as access
from . import _events as events
from . import _widgets as widgets

DASHBOARD = EwsResources.DASHBOARD.value
MAX_WIDGETS = 24
COLUMNS = 12
SYSTEM_PREFIX = 'system:'

WIDGET_TYPES: tuple[dict[str, Any], ...] = (
    {'type': 'kpi', 'sources': ('kpi',), 'w': 3, 'h': 2},
    {'type': 'bar', 'sources': ('items', 'projects', 'time'), 'w': 6, 'h': 4},
    {'type': 'stacked_bar', 'sources': ('items', 'time'), 'w': 6, 'h': 4},
    {'type': 'line', 'sources': ('trend', 'series'), 'w': 6, 'h': 4},
    {
        'type': 'list',
        'sources': ('item_list', 'project_list', 'approvals'),
        'w': 6,
        'h': 5,
    },
    {'type': 'milestones', 'sources': ('milestones',), 'w': 4, 'h': 4},
    {'type': 'health', 'sources': ('health',), 'w': 6, 'h': 4},
    {'type': 'health_matrix', 'sources': ('health_matrix',), 'w': 12, 'h': 5},
    {'type': 'activity', 'sources': ('activity',), 'w': 4, 'h': 5},
    {'type': 'text', 'sources': (), 'w': 4, 'h': 2},
)
TYPES = {w['type']: w for w in WIDGET_TYPES}


def _w(
    wid: str,
    type_: str,
    x: int,
    y: int,
    w: int,
    h: int,
    query: dict[str, Any] | None = None,
    **viz: Any,
):
    return {
        'id': wid,
        'type': type_,
        'x': x,
        'y': y,
        'w': w,
        'h': h,
        'query': query,
        'viz': viz or None,
    }


SYSTEM: dict[str, dict[str, Any]] = {
    # PPM overview panels (Ppm-1902): projects by health, my overdue / due soon, milestones, activity
    'ppm_overview': {
        'scope_type': 'organization',
        'widgets': [
            _w(
                'by_health',
                'bar',
                0,
                0,
                6,
                4,
                {'source': 'projects', 'group_by': 'health'},
            ),
            _w(
                'milestones',
                'milestones',
                6,
                0,
                6,
                4,
                {'source': 'milestones', 'filters': {}, 'limit': 8},
            ),
            _w(
                'mine',
                'list',
                0,
                4,
                6,
                5,
                {
                    'source': 'item_list',
                    'filters': {'mine': True, 'open': True},
                    'limit': 10,
                },
            ),
            _w('activity', 'activity', 6, 4, 6, 5, {'source': 'activity', 'limit': 10}),
        ],
    },
    # My dashboard (Ppm-1903)
    'my_dashboard': {
        'scope_type': 'personal',
        'widgets': [
            _w(
                'open',
                'kpi',
                0,
                0,
                3,
                2,
                {'source': 'kpi', 'metric': 'open', 'filters': {'mine': True}},
            ),
            _w(
                'overdue',
                'kpi',
                3,
                0,
                3,
                2,
                {'source': 'kpi', 'metric': 'overdue', 'filters': {'mine': True}},
            ),
            _w(
                'soon',
                'kpi',
                6,
                0,
                3,
                2,
                {'source': 'kpi', 'metric': 'due_soon', 'filters': {'mine': True}},
            ),
            _w(
                'logged',
                'kpi',
                9,
                0,
                3,
                2,
                {'source': 'kpi', 'metric': 'logged_7d', 'filters': {'mine': True}},
            ),
            _w(
                'by_project',
                'bar',
                0,
                2,
                6,
                4,
                {
                    'source': 'items',
                    'group_by': 'project',
                    'filters': {'mine': True, 'open': True},
                },
            ),
            _w('approvals', 'list', 6, 2, 6, 4, {'source': 'approvals', 'limit': 10}),
            _w(
                'items',
                'list',
                0,
                6,
                12,
                5,
                {'source': 'item_list', 'filters': {'mine': True, 'open': True}},
            ),
        ],
    },
    # Project dashboard Overview tab (Ppm-1910…1912): the project filter is the dashboard's scope
    'project_overview': {
        'scope_type': 'project',
        'widgets': [
            _w('health', 'health', 0, 0, 6, 4, {'source': 'health'}),
            _w('open', 'kpi', 6, 0, 3, 2, {'source': 'kpi', 'metric': 'open'}),
            _w('overdue', 'kpi', 9, 0, 3, 2, {'source': 'kpi', 'metric': 'overdue'}),
            _w('soon', 'kpi', 6, 2, 3, 2, {'source': 'kpi', 'metric': 'due_soon'}),
            _w('done', 'kpi', 9, 2, 3, 2, {'source': 'kpi', 'metric': 'done_7d'}),
            _w('burnup', 'line', 0, 4, 6, 4, {'source': 'series', 'metric': 'burnup'}),
            _w('milestones', 'milestones', 6, 4, 6, 4, {'source': 'milestones'}),
            _w(
                'workload',
                'bar',
                0,
                8,
                6,
                4,
                {'source': 'items', 'group_by': 'assignee', 'filters': {'open': True}},
                orientation='horizontal',
            ),
            _w('activity', 'activity', 6, 8, 6, 4, {'source': 'activity', 'limit': 10}),
        ],
    },
}
WIDGET_CAPABILITY = {'health': 'health', 'health_matrix': 'health'}
"""Widget types shown only while their capability is on (the web hides them; their data answers 403 otherwise)."""


def _error(detail: str, code: str = 'invalid_dashboard') -> ClientException:
    return ClientException(detail=detail, extra={'code': code})


def clean_layout(layout: Any) -> dict[str, Any]:
    """``{schema_version: 1, widgets: [...]}``: ≤ 24 widgets on 12 columns, known types, valid queries."""
    raw = layout.get('widgets') if isinstance(layout, dict) else layout
    if not isinstance(raw, list):
        raise _error('layout.widgets must be a list')
    if len(raw) > MAX_WIDGETS:
        raise _error(f'a dashboard holds at most {MAX_WIDGETS} widgets')
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for w in raw:
        if not isinstance(w, dict):
            raise _error('a widget must be an object')
        wid, kind = str(w.get('id') or '')[:40], w.get('type')
        if not wid or wid in seen:
            raise _error('widget ids must be unique and not empty')
        seen.add(wid)
        spec = TYPES.get(kind or '')
        if spec is None:
            raise _error(f'unknown widget type {kind!r}')
        box = {k: w.get(k, spec.get(k, 0)) for k in ('x', 'y', 'w', 'h')}
        if not all(
            isinstance(v, int) and not isinstance(v, bool) for v in box.values()
        ):
            raise _error('x, y, w, h must be whole numbers')
        if not (
            0 <= box['x'] < COLUMNS
            and 1 <= box['w'] <= COLUMNS
            and box['x'] + box['w'] <= COLUMNS
        ):
            raise _error(f'a widget must fit the {COLUMNS} columns')
        if not (0 <= box['y'] <= 500 and 1 <= box['h'] <= 20):
            raise _error('y must be 0 to 500 and h 1 to 20')
        item: dict[str, Any] = {'id': wid, 'type': kind, **box}
        title = w.get('title')
        if title:
            item['title'] = str(title)[:120]
        if kind == 'text':
            item['text'] = str(w.get('text') or '')[:5000]
        else:
            query = widgets.clean_query(
                w.get('query') or {'source': spec['sources'][0]}
            )
            if query['source'] not in spec['sources']:
                raise _error(f'a {kind} widget reads {", ".join(spec["sources"])}')
            item['query'] = query
        viz = w.get('viz')
        if isinstance(viz, dict) and viz:
            item['viz'] = {
                str(k)[:40]: v
                for k, v in list(viz.items())[:20]
                if isinstance(v, (str, int, float, bool))
            }
        out.append(item)
    return {'schema_version': 1, 'widgets': out}


def system_layout(key: str) -> dict[str, Any]:
    return clean_layout(copy.deepcopy(SYSTEM[key]['widgets']))


# --- access ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class View:
    """A dashboard as the viewer sees it (system dashboards are not rows)."""

    row: PpmDashboard | None
    system_key: str | None
    scope_type: str
    scope_id: UUID | None
    name: str
    layout: dict[str, Any]
    filters: dict[str, Any]
    can_edit: bool
    is_owner: bool


async def _can_manage_scope(
    scope: RequestScope, scope_type: str, scope_id: UUID | None
) -> bool:
    if scope_type == 'project' and scope_id is not None:
        return await is_allowed(
            scope, DASHBOARD, 'update', access.project_domains(scope, scope_id)
        )
    if scope_type == 'organization':
        return await is_allowed(scope, DASHBOARD, 'update', scope.org_domains())
    return False


async def _reads_scope(
    session: DBAsyncScopedSession, scope: RequestScope, row: PpmDashboard
) -> bool:
    if row.scope_type == 'project' and row.scope_id is not None:
        try:
            await access.load_project(session, scope, row.scope_id)
        except NotFoundException, PermissionDeniedException:
            return False
        return True
    return row.scope_type == 'organization'


async def _share_of(
    session: DBAsyncScopedSession, scope: RequestScope, row: PpmDashboard
) -> PpmDashboardShare | None:
    s = PpmDashboardShare
    refs = [access.author(scope), str(scope.user_id)]
    return await session.scalar(
        select(s).where(
            s.dashboard_id == row.id,
            s.principal_type == 'user',
            s.principal_id.in_(refs),
        )
    )


async def view_of(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    dashboard_id: str,
    *,
    project: ews_models.Project | None = None,
) -> View:
    """The dashboard the viewer may open (404 otherwise); ``system:<key>`` = a system dashboard (``project`` = the
    project of ``project_overview``)."""
    if dashboard_id.startswith(SYSTEM_PREFIX):
        key = dashboard_id.removeprefix(SYSTEM_PREFIX)
        if key not in SYSTEM:
            raise NotFoundException(detail='dashboard not found')
        scope_type = SYSTEM[key]['scope_type']
        return View(
            None,
            key,
            scope_type,
            project.id if project and scope_type == 'project' else None,
            key,
            system_layout(key),
            {},
            False,
            False,
        )
    row = await session.scalar(
        select(PpmDashboard).where(
            PpmDashboard.id == access.parse_uuid(dashboard_id, 'dashboard'),
            PpmDashboard.organization_id == scope.organization_id,
            PpmDashboard.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFoundException(detail='dashboard not found')
    owner = row.owner == access.author(scope)
    share = None if owner else await _share_of(session, scope, row)
    manager = await _can_manage_scope(scope, row.scope_type, row.scope_id)
    visible = (
        owner
        or manager
        or (row.visibility in ('shared', 'scope') and share is not None)
        or (row.visibility == 'scope' and await _reads_scope(session, scope, row))
    )
    if not visible:
        raise NotFoundException(detail='dashboard not found')
    return View(
        row,
        None,
        row.scope_type,
        row.scope_id,
        row.name,
        row.layout or {'schema_version': 1, 'widgets': []},
        row.filters or {},
        owner or manager or bool(share and share.can_edit),
        owner,
    )


async def list_for(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    scope_type: str | None,
    scope_id: UUID | None,
) -> tuple[list[str], list[tuple[PpmDashboard, bool]]]:
    """System keys + the dashboards the viewer may open (``(row, can_edit)``), optionally of one scope."""
    d = PpmDashboard
    me = access.author(scope)
    shared_ids = select(PpmDashboardShare.dashboard_id).where(
        PpmDashboardShare.principal_type == 'user',
        PpmDashboardShare.principal_id.in_([me, str(scope.user_id)]),
    )
    q = select(d).where(
        d.organization_id == scope.organization_id,
        d.deleted_at.is_(None),
        or_(
            d.owner == me,
            d.id.in_(shared_ids),
            d.visibility == 'scope',
            d.scope_type != 'personal',
        ),
    )
    if scope_type:
        q = q.where(d.scope_type == scope_type)
    if scope_id:
        q = q.where(d.scope_id == scope_id)
    out: list[tuple[PpmDashboard, bool]] = []
    for row in (await session.scalars(q.order_by(d.name))).all():
        try:
            view = await view_of(session, scope, str(row.id))
        except NotFoundException:
            continue
        out.append((row, view.can_edit))
    keys = [
        k for k, v in SYSTEM.items() if not scope_type or v['scope_type'] == scope_type
    ]
    return keys, out


async def _require_create(
    scope: RequestScope, scope_type: str, scope_id: UUID | None
) -> None:
    if scope_type == 'personal':
        if await is_allowed(scope, DASHBOARD, 'create', scope.org_domains()):
            return
    elif scope_type == 'project' and scope_id is not None:
        if await is_allowed(
            scope, DASHBOARD, 'create', access.project_domains(scope, scope_id)
        ):
            return
    elif await is_allowed(scope, DASHBOARD, 'update', scope.org_domains()):
        return  # organization dashboards: managers (``create`` on the organization = personal ones)
    raise PermissionDeniedException(detail=f'{DASHBOARD}:create is required')


def _now() -> datetime:
    return datetime.now(UTC)


async def create(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    name: str,
    scope_type: str = 'personal',
    scope_id: UUID | None = None,
    layout: Any = None,
    filters: Any = None,
    visibility: str = 'private',
    description: str | None = None,
) -> PpmDashboard:
    if scope_type not in ('personal', 'project', 'organization'):
        raise _error('scope_type must be personal, project or organization')
    if scope_type == 'project':
        if scope_id is None:
            raise _error('a project dashboard needs scope_id')
        await access.load_project(session, scope, scope_id)
    else:
        scope_id = None
    if visibility not in ('private', 'shared', 'scope'):
        raise _error('visibility must be private, shared or scope')
    await _require_create(scope, scope_type, scope_id)
    name = (name or '').strip()[:200]
    if not name:
        raise _error('a name is required')
    row = PpmDashboard(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        scope_type=scope_type,
        scope_id=scope_id,
        owner=access.author(scope),
        name=name,
        description=(description or '').strip()[:2000] or None,
        layout=clean_layout(layout if layout is not None else []),
        filters=widgets.clean_filters(filters or {}),
        visibility=visibility,
        version=1,
    )
    session.add(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.dashboard.created',
        'dashboard',
        row.id,
        project_id=scope_id,
        data={'name': name},
    )
    return row


async def update(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    view: View,
    *,
    version: int,
    patch: dict[str, Any],
) -> PpmDashboard:
    """Name, description, layout, filters, visibility (``version`` must match: 409 ``stale_dashboard``)."""
    row = view.row
    if row is None or not view.can_edit:
        raise PermissionDeniedException(
            detail='this dashboard cannot be changed (copy it to customize)'
        )
    if row.version != version:
        raise ConflictException(
            detail='the dashboard changed meanwhile', extra={'code': 'stale_dashboard'}
        )
    before = {'name': row.name, 'visibility': row.visibility, 'filters': row.filters}
    if 'name' in patch:
        name = (patch['name'] or '').strip()[:200]
        if not name:
            raise _error('a name is required')
        row.name = name
    if 'description' in patch:
        row.description = (patch['description'] or '').strip()[:2000] or None
    if 'layout' in patch:
        row.layout = clean_layout(patch['layout'])
    if 'filters' in patch:
        row.filters = widgets.clean_filters(patch['filters'] or {})
    if 'visibility' in patch:
        if patch['visibility'] not in ('private', 'shared', 'scope'):
            raise _error('visibility must be private, shared or scope')
        if patch['visibility'] != row.visibility and not view.is_owner:
            if not await _can_manage_scope(scope, row.scope_type, row.scope_id):
                raise PermissionDeniedException(
                    detail='only the owner changes who sees the dashboard'
                )
        row.visibility = patch['visibility']
    row.version += 1
    row.updated_at = _now()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.dashboard.updated',
        'dashboard',
        row.id,
        project_id=row.scope_id if row.scope_type == 'project' else None,
        changes=events.diff(
            before,
            {'name': row.name, 'visibility': row.visibility, 'filters': row.filters},
        ),
    )
    return row


async def delete(
    session: DBAsyncScopedSession, scope: RequestScope, view: View
) -> None:
    row = view.row
    if row is None:
        raise PermissionDeniedException(detail='system dashboards cannot be deleted')
    if not (
        view.is_owner or await _can_manage_scope(scope, row.scope_type, row.scope_id)
    ):
        raise PermissionDeniedException(detail='only the owner deletes a dashboard')
    row.deleted_at = _now()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.dashboard.deleted',
        'dashboard',
        row.id,
        project_id=row.scope_id if row.scope_type == 'project' else None,
        data={'name': row.name},
    )


async def copy_of(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    view: View,
    *,
    name: str | None,
    scope_type: str | None,
    scope_id: UUID | None,
) -> PpmDashboard:
    """A copy owned by the caller (personal by default); a system dashboard copy = *Copy to customize*."""
    target_type = scope_type or (
        'project' if view.scope_type == 'project' else 'personal'
    )
    target_id = scope_id or (view.scope_id if target_type == 'project' else None)
    return await create(
        session,
        scope,
        name=name or view.name,
        scope_type=target_type,
        scope_id=target_id,
        layout=copy.deepcopy(view.layout),
        filters=copy.deepcopy(view.filters),
    )


async def shares_of(
    session: DBAsyncScopedSession, dashboard_id: UUID
) -> list[PpmDashboardShare]:
    s = PpmDashboardShare
    return list(
        (
            await session.scalars(
                select(s).where(s.dashboard_id == dashboard_id).order_by(s.principal_id)
            )
        ).all()
    )


async def replace_shares(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    view: View,
    shares: list[dict[str, Any]],
) -> list[PpmDashboardShare]:
    """Replace who the dashboard is shared with (owner or scope manager); ``visibility`` becomes ``shared`` when it was
    ``private`` and someone is added."""
    row = view.row
    if row is None:
        raise PermissionDeniedException(
            detail='system dashboards are shared with everyone already'
        )
    if not (
        view.is_owner or await _can_manage_scope(scope, row.scope_type, row.scope_id)
    ):
        raise PermissionDeniedException(detail='only the owner shares a dashboard')
    if len(shares) > 200:
        raise _error('at most 200 people per dashboard')
    wanted: dict[str, bool] = {}
    for s in shares:
        ref = str(s.get('principal_id') or '').strip().lower()[:320]
        if ref and ref != row.owner:
            wanted[ref] = bool(s.get('can_edit'))
    for old in await shares_of(session, row.id):
        await session.delete(old)
    await session.flush()
    for ref, can_edit in wanted.items():
        session.add(
            PpmDashboardShare(
                tenant_id=row.tenant_id,
                dashboard_id=row.id,
                principal_type='user',
                principal_id=ref,
                can_edit=can_edit,
            )
        )
    if wanted and row.visibility == 'private':
        row.visibility = 'shared'
        row.version += 1
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.dashboard.shared',
        'dashboard',
        row.id,
        project_id=row.scope_id if row.scope_type == 'project' else None,
        data={'shares': len(wanted)},
    )
    return await shares_of(session, row.id)


def widget_of(view: View, widget_id: str) -> dict[str, Any]:
    for w in view.layout.get('widgets') or []:
        if w.get('id') == widget_id:
            return w
    raise NotFoundException(detail='widget not found')


def scope_filters(view: View) -> dict[str, Any]:
    """The dashboard's own filters, plus its project for a project dashboard."""
    out = dict(view.filters or {})
    if view.scope_type == 'project' and view.scope_id is not None:
        out['project_ids'] = [str(view.scope_id)]
    return out
