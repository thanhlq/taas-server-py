"""Widget queries of the PPM dashboards (taas-specs/ppm/reporting/dashboards-reports-spec.md §5, ADR-45): a small,
validated query model run **with the viewer's scope** (readable projects only, templates never counted) and one
result shape ``{columns, rows, total, as_of}`` for every widget, report and export. Engine numbers (health, schedule,
statistics) are read, never recomputed here (ADR-16).

Query: ``{source, measure, group_by, stack_by, metric, columns, limit, filters}``; filters (dashboard bar + the
widget's own): ``project_ids``, ``owner``, ``status`` (project status), ``item_type``, ``labels``, ``date_from`` /
``date_to`` (items: due date · time: entry date · trend: day), ``open``, ``overdue``, ``mine``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmAuditEvent, PpmHealthSnapshot, PpmProjectDailyStats
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import Select, and_, case, func, literal, or_, select
from sqlalchemy.sql.elements import ColumnElement

from ews.security import RequestScope

from . import _access as access
from . import _behaviours as behaviours
from . import workflow_catalog as catalog

Project = ews_models.Project
Task = ews_models.Task
Timelog = ews_models.Timelog
Health = PpmHealthSnapshot
Stats = PpmProjectDailyStats

MAX_ROWS = 10_000
LIST_ROWS = 50

SOURCES: dict[str, dict[str, tuple[str, ...]]] = {
    'items': {
        'measure': ('count', 'estimate', 'remaining', 'logged'),
        'group_by': (
            'band',
            'status',
            'assignee',
            'type',
            'priority',
            'project',
            'due_week',
        ),
    },
    'projects': {'measure': ('count',), 'group_by': ('status', 'health', 'owner')},
    'time': {
        'measure': ('minutes', 'billable_minutes'),
        'group_by': ('person', 'project', 'week', 'billable'),
    },
    'trend': {
        'measure': (
            'items_added',
            'items_completed',
            'items_open',
            'items_overdue',
            'items_done',
            'logged_minutes',
        ),
        'group_by': ('day', 'week'),
    },
    'kpi': {
        'metric': (
            'open',
            'overdue',
            'due_soon',
            'done_7d',
            'projects',
            'at_risk',
            'logged_7d',
        ),
        'group_by': (),
    },
    'item_list': {'group_by': ()},
    'project_list': {'group_by': ()},
    'milestones': {'group_by': ()},
    'health_matrix': {'group_by': ()},
    'activity': {'group_by': ()},
    'approvals': {'group_by': ()},
    'health': {'group_by': ()},
    'series': {'metric': ('burnup', 'burndown', 'throughput'), 'group_by': ()},
}
SINGLE_PROJECT = ('health', 'series')
"""Sources of one project: ``filters.project_ids`` holds exactly one id (a project dashboard sets it)."""
FILTERS = (
    'project_ids',
    'owner',
    'status',
    'item_type',
    'labels',
    'date_from',
    'date_to',
    'open',
    'overdue',
    'mine',
)
GROUP_TYPES = {
    'band': 'band',
    'status': 'stage_type',
    'assignee': 'user',
    'type': 'item_type',
    'priority': 'priority',
    'project': 'project',
    'due_week': 'date',
    'health': 'rating',
    'owner': 'user',
    'person': 'user',
    'week': 'date',
    'day': 'date',
    'billable': 'boolean',
}


@dataclass(slots=True)
class Result:
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    total: int
    as_of: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            'columns': self.columns,
            'rows': self.rows,
            'total': self.total,
            'as_of': self.as_of,
        }


def _error(detail: str) -> ClientException:
    return ClientException(detail=detail, extra={'code': 'invalid_query'})


def today() -> date:
    return datetime.now(UTC).date()


def clean_query(query: Any) -> dict[str, Any]:
    """A widget query with known keys and values only (400 ``invalid_query``)."""
    if not isinstance(query, dict):
        raise _error('query must be an object')
    source = query.get('source')
    spec = SOURCES.get(source or '')
    if spec is None:
        raise _error(f'source must be one of {", ".join(SOURCES)}')
    out: dict[str, Any] = {'source': source}
    for key in ('measure', 'metric'):
        if key in spec:
            value = query.get(key) or spec[key][0]
            if value not in spec[key]:
                raise _error(f'{key} must be one of {", ".join(spec[key])}')
            out[key] = value
    for key in ('group_by', 'stack_by'):
        value = query.get(key)
        if value in (None, ''):
            continue
        if value not in spec['group_by']:
            raise _error(
                f'{key} must be one of {", ".join(spec["group_by"]) or "nothing"}'
            )
        out[key] = value
    if 'stack_by' in out and 'group_by' not in out:
        raise _error('stack_by needs group_by')
    limit = query.get('limit')
    if limit is not None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= LIST_ROWS
        ):
            raise _error(f'limit must be 1 to {LIST_ROWS}')
        out['limit'] = limit
    out['filters'] = clean_filters(query.get('filters') or {})
    return out


def clean_filters(filters: Any) -> dict[str, Any]:
    if not isinstance(filters, dict):
        raise _error('filters must be an object')
    out: dict[str, Any] = {}
    for key, value in filters.items():
        if key not in FILTERS:
            raise _error(f'unknown filter {key!r}')
        if value in (None, '', []):
            continue
        if key in ('project_ids', 'labels', 'item_type', 'status'):
            values = value if isinstance(value, list) else [value]
            if not all(isinstance(v, str) for v in values):
                raise _error(f'{key} must be text values')
            if key == 'project_ids':
                try:
                    values = [str(UUID(v)) for v in values]
                except ValueError as exc:
                    raise _error('project_ids must be ids') from exc
            out[key] = values[:100]
        elif key in ('date_from', 'date_to'):
            try:
                out[key] = date.fromisoformat(str(value)[:10]).isoformat()
            except ValueError as exc:
                raise _error(f'{key} must be a date') from exc
        elif key in ('open', 'overdue', 'mine'):
            out[key] = bool(value)
        else:
            out[key] = str(value)
    return out


def merge_filters(*layers: dict[str, Any] | None) -> dict[str, Any]:
    """Dashboard filters, then the widget's own, then the request's: later layers win key by key."""
    out: dict[str, Any] = {}
    for layer in layers:
        out.update({k: v for k, v in (layer or {}).items() if v not in (None, '', [])})
    return out


# --- shared conditions ----------------------------------------------------------------------------


def counted_condition() -> ColumnElement[bool]:
    return and_(
        or_(
            Task.stage_type.is_(None),
            Task.stage_type.not_in(catalog.excluded_stage_types()),
        ),
        or_(
            Task.behaviour.is_(None), Task.behaviour.not_in(behaviours.NOT_IN_PROGRESS)
        ),
    )


def done_condition() -> ColumnElement[bool]:
    return or_(
        Task.stage_type.in_(catalog.done_stage_types()), Task.completed_at.is_not(None)
    )


def _band() -> Any:
    bands = {s.key: s.band for s in catalog.stage_types()}
    whens = [
        (Task.stage_type == k, literal(v)) for k, v in bands.items() if v != 'done'
    ]
    return case((done_condition(), literal('done')), *whens, else_=literal('initial'))


def me_refs(scope: RequestScope) -> list[str]:
    """The viewer as stored on items and time (user id or e-mail, lower case — like My Work)."""
    return sorted({r.lower() for r in (str(scope.user_id), scope.email or '') if r})


def _day(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


async def project_conditions(
    scope: RequestScope, f: dict[str, Any]
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [
        await access.readable_projects(scope),
        Project.kind == 'project',
        Project.deleted_at.is_(None),
    ]
    if f.get('project_ids'):
        conds.append(Project.id.in_([UUID(v) for v in f['project_ids']]))
    if f.get('status'):
        conds.append(Project.status.in_(f['status']))
    if f.get('labels'):
        # labels live in ``tags = {'labels': [...]}``: any of the wanted labels
        conds.append(Project.tags['labels'].op('?|')(f['labels']))
    return conds


def item_conditions(
    scope: RequestScope, f: dict[str, Any]
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [Task.deleted_at.is_(None), counted_condition()]
    if f.get('owner'):
        conds.append(
            Task.user_id.is_(None)
            if f['owner'] == 'none'
            else Task.user_id == f['owner']
        )
    if f.get('mine'):
        conds.append(func.lower(Task.user_id).in_(me_refs(scope)))
    if f.get('item_type'):
        conds.append(Task.work_item_type.in_(f['item_type']))
    if f.get('open') or f.get('overdue'):
        conds.append(~done_condition())
    if f.get('overdue'):
        conds.append(Task.due_date < datetime.combine(today(), datetime.min.time()))
    if f.get('date_from'):
        conds.append(Task.due_date >= _day(f['date_from']))
    if f.get('date_to'):
        conds.append(Task.due_date < _day(f['date_to']) + timedelta(days=1))
    return conds


async def project_names(
    session: DBAsyncScopedSession, ids: set[UUID]
) -> dict[str, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Project.id, Project.name).where(Project.id.in_(ids))
    )
    return {str(i): n or '' for i, n in rows.all()}


# --- sources --------------------------------------------------------------------------------------


async def _items(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    f = q['filters']
    measure = {
        'count': func.count(Task.id),
        'estimate': func.coalesce(func.sum(Task.estimated_minutes), 0),
        'logged': func.coalesce(func.sum(Task.actual_minutes), 0),
        'remaining': func.coalesce(
            func.sum(
                case(
                    (done_condition(), 0),
                    else_=func.coalesce(
                        Task.remaining_minutes,
                        func.greatest(
                            func.coalesce(Task.estimated_minutes, 0)
                            - func.coalesce(Task.actual_minutes, 0),
                            0,
                        ),
                    ),
                )
            ),
            0,
        ),
    }[q['measure']]
    groups = {
        'band': _band(),
        'status': Task.stage_type,
        'assignee': Task.user_id,
        'type': Task.work_item_type,
        'priority': Task.priority,
        'project': Task.project_id,
        'due_week': func.date_trunc('week', Task.due_date),
    }
    keys = [k for k in (q.get('group_by'), q.get('stack_by')) if k]
    exprs = [groups[k].label(k) for k in keys]
    stmt: Select[Any] = (
        select(*exprs, measure.label('value'))
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(*(await project_conditions(scope, f)), *item_conditions(scope, f))
    )
    if exprs:
        stmt = (
            stmt.group_by(*[e.element for e in exprs])
            .order_by(measure.desc())
            .limit(MAX_ROWS)
        )
    rows = [list(r) for r in (await session.execute(stmt)).all()]
    return await _grouped(session, keys, q['measure'], rows)


async def _grouped(
    session: DBAsyncScopedSession, keys: list[str], measure: str, rows: list[list[Any]]
) -> Result:
    """Group keys as text (ids → project names in a label column), dates as ISO days, ``None`` kept (= none)."""
    columns = [{'key': k, 'type': GROUP_TYPES[k]} for k in keys] + [
        {'key': measure, 'type': 'number'}
    ]
    projects = {
        r[keys.index('project')]
        for r in rows
        if 'project' in keys and r[keys.index('project')]
    }
    names = await project_names(session, {UUID(str(p)) for p in projects})
    out: list[list[Any]] = []
    for r in rows:
        line: list[Any] = []
        for i in range(len(keys)):
            v = r[i]
            if isinstance(v, datetime):
                v = v.date().isoformat()
            elif isinstance(v, date):
                v = v.isoformat()
            elif isinstance(v, UUID):
                v = str(v)
            line.append(v)
        line.append(int(r[len(keys)] or 0))
        out.append(line)
    if 'project' in keys:
        columns.insert(
            keys.index('project') + 1, {'key': 'project_name', 'type': 'string'}
        )
        i = keys.index('project')
        out = [
            [*line[: i + 1], names.get(str(line[i]), ''), *line[i + 1 :]]
            for line in out
        ]
    if keys and keys[0] in ('due_week', 'week', 'day'):
        out.sort(key=lambda line: (line[0] is None, line[0] or ''))
    return Result(columns, out, len(out))


async def latest_health(
    session: DBAsyncScopedSession, project_ids: list[UUID]
) -> dict[UUID, PpmHealthSnapshot]:
    if not project_ids:
        return {}
    rows = await session.scalars(
        select(Health)
        .where(Health.project_id.in_(project_ids))
        .distinct(Health.project_id)
        .order_by(Health.project_id, Health.snapshot_date.desc())
    )
    return {r.project_id: r for r in rows}


async def project_rows(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    f: dict[str, Any],
    limit: int = MAX_ROWS,
) -> list[ews_models.Project]:
    q = select(Project).where(*(await project_conditions(scope, f)))
    if f.get('owner'):
        q = q.where(Project.user_id == f['owner'])
    if f.get('mine'):
        q = q.where(func.lower(Project.user_id).in_(me_refs(scope)))
    return list((await session.scalars(q.order_by(Project.name).limit(limit))).all())


async def _projects_source(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    projects = await project_rows(session, scope, q['filters'])
    health = (
        await latest_health(session, [p.id for p in projects])
        if q.get('group_by') == 'health'
        else {}
    )
    key = q.get('group_by')
    counts: dict[Any, int] = defaultdict(int)
    for p in projects:
        value = (
            p.status
            if key == 'status'
            else p.user_id
            if key == 'owner'
            else (health[p.id].overall_effective if p.id in health else 'none')
            if key == 'health'
            else None
        )
        counts[value] += 1
    if not key:
        return Result([{'key': 'count', 'type': 'number'}], [[len(projects)]], 1)
    rows = sorted(([k, n] for k, n in counts.items()), key=lambda r: -r[1])
    return Result(
        [{'key': key, 'type': GROUP_TYPES[key]}, {'key': 'count', 'type': 'number'}],
        rows,
        len(rows),
    )


async def _time(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    f = q['filters']
    measure = (
        func.coalesce(func.sum(Timelog.log_minutes), 0)
        if q['measure'] == 'minutes'
        else func.coalesce(
            func.sum(Timelog.log_minutes).filter(Timelog.is_billable.is_(True)), 0
        )
    )
    groups = {
        'person': Timelog.user_id,
        'project': Timelog.project_id,
        'week': func.date_trunc('week', Timelog.entry_date),
        'billable': func.coalesce(Timelog.is_billable, False),
    }
    keys = [k for k in (q.get('group_by'), q.get('stack_by')) if k]
    exprs = [groups[k].label(k) for k in keys]
    conds: list[ColumnElement[bool]] = [Timelog.deleted_at.is_(None)]
    if f.get('date_from'):
        conds.append(Timelog.entry_date >= date.fromisoformat(f['date_from']))
    if f.get('date_to'):
        conds.append(Timelog.entry_date <= date.fromisoformat(f['date_to']))
    if f.get('owner'):
        conds.append(Timelog.user_id == f['owner'])
    if f.get('mine'):
        conds.append(func.lower(Timelog.user_id).in_(me_refs(scope)))
    stmt = (
        select(*exprs, measure.label('value'))
        .select_from(Timelog)
        .join(Project, Project.id == Timelog.project_id)
        .where(*(await project_conditions(scope, f)), *conds)
    )
    if exprs:
        stmt = (
            stmt.group_by(*[e.element for e in exprs])
            .order_by(measure.desc())
            .limit(MAX_ROWS)
        )
    rows = [list(r) for r in (await session.execute(stmt)).all()]
    return await _grouped(session, keys, q['measure'], rows)


async def _trend(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    """Daily statistics summed over the readable projects (``group_by`` day | week); default the last 30 days."""
    f = q['filters']
    end = date.fromisoformat(f['date_to']) if f.get('date_to') else today()
    start = (
        date.fromisoformat(f['date_from'])
        if f.get('date_from')
        else end - timedelta(days=29)
    )
    measure = getattr(Stats, q['measure'])
    key = q.get('group_by') or 'day'
    bucket = (
        Stats.stats_date if key == 'day' else func.date_trunc('week', Stats.stats_date)
    )
    # counts of a state (open, overdue, done) are taken on the last day of a week; flows (added, completed, logged) summed
    stmt = (
        select(bucket.label(key), Stats.stats_date, func.sum(measure))
        .select_from(Stats)
        .join(Project, Project.id == Stats.project_id)
        .where(
            *(await project_conditions(scope, f)),
            Stats.iteration_id.is_(None),
            Stats.stats_date >= start,
            Stats.stats_date <= end,
        )
        .group_by(bucket, Stats.stats_date)
        .order_by(Stats.stats_date)
    )
    flows = q['measure'] in ('items_added', 'items_completed', 'logged_minutes')
    out: dict[str, int] = {}
    for b, _day_value, value in (await session.execute(stmt)).all():
        k = (b.date() if isinstance(b, datetime) else b).isoformat()
        out[k] = out.get(k, 0) + int(value or 0) if flows else int(value or 0)
    as_of = await session.scalar(
        select(func.max(Stats.computed_at)).where(
            Stats.stats_date == end, Stats.iteration_id.is_(None)
        )
    )
    rows = [[k, v] for k, v in sorted(out.items())]
    return Result(
        [{'key': key, 'type': 'date'}, {'key': q['measure'], 'type': 'number'}],
        rows,
        len(rows),
        as_of,
    )


async def _kpi(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    """One value; item metrics come with a 14-day sparkline from the daily statistics (``rows`` = ``[day, value]``,
    the last row is today)."""
    f = q['filters']
    metric = q['metric']
    day = today()
    if metric in ('projects', 'at_risk'):
        projects = await project_rows(session, scope, f)
        if metric == 'projects':
            value = len(projects)
        else:
            health = await latest_health(session, [p.id for p in projects])
            value = sum(1 for h in health.values() if h.overall_effective == 'red')
        return Result(
            [{'key': 'date', 'type': 'date'}, {'key': metric, 'type': 'number'}],
            [[day.isoformat(), value]],
            1,
        )
    conds = [*(await project_conditions(scope, f)), *item_conditions(scope, f)]
    midnight = datetime.combine(day, datetime.min.time())
    if metric == 'logged_7d':
        tf = {
            **f,
            'date_from': (day - timedelta(days=6)).isoformat(),
            'date_to': day.isoformat(),
        }
        res = await _time(session, scope, {'measure': 'minutes', 'filters': tf})
        value = int(res.rows[0][0]) if res.rows else 0
        return Result(
            [{'key': 'date', 'type': 'date'}, {'key': metric, 'type': 'number'}],
            [[day.isoformat(), value]],
            1,
        )
    cond = {
        'open': ~done_condition(),
        'overdue': and_(~done_condition(), Task.due_date < midnight),
        'due_soon': and_(
            ~done_condition(),
            Task.due_date >= midnight,
            Task.due_date < midnight + timedelta(days=8),
        ),
        'done_7d': and_(
            done_condition(), Task.completed_at >= midnight - timedelta(days=6)
        ),
    }[metric]
    value = await session.scalar(
        select(func.count(Task.id))
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(*conds, cond)
    )
    rows: list[list[Any]] = []
    stat = {'open': 'items_open', 'overdue': 'items_overdue'}.get(metric)
    if stat and not any(
        f.get(k) for k in ('owner', 'mine', 'item_type', 'date_from', 'date_to')
    ):
        trend = await _trend(
            session,
            scope,
            {
                'measure': stat,
                'group_by': 'day',
                'filters': {**f, 'date_from': (day - timedelta(days=13)).isoformat()},
            },
        )
        rows = [r for r in trend.rows if r[0] != day.isoformat()]
    rows.append([day.isoformat(), int(value or 0)])
    return Result(
        [{'key': 'date', 'type': 'date'}, {'key': metric, 'type': 'number'}],
        rows,
        len(rows),
    )


async def _item_list(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    f = q['filters']
    limit = q.get('limit') or LIST_ROWS
    base = (
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .where(*(await project_conditions(scope, f)), *item_conditions(scope, f))
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    tasks = (
        await session.scalars(
            base.order_by(Task.due_date.asc().nulls_last(), Task.id).limit(limit)
        )
    ).all()
    names = await project_names(session, {t.project_id for t in tasks if t.project_id})
    done = catalog.done_stage_types()
    columns = [
        {'key': k, 'type': t}
        for k, t in (
            ('id', 'id'),
            ('code', 'string'),
            ('name', 'string'),
            ('project', 'project'),
            ('project_name', 'string'),
            ('assignee', 'user'),
            ('status', 'stage_type'),
            ('priority', 'priority'),
            ('due', 'date'),
            ('done', 'boolean'),
        )
    ]
    rows = [
        [
            str(t.id),
            t.code,
            t.name,
            str(t.project_id),
            names.get(str(t.project_id), ''),
            t.user_id,
            t.stage_type,
            t.priority,
            t.due_date.date().isoformat() if t.due_date else None,
            t.stage_type in done or t.completed_at is not None,
        ]
        for t in tasks
    ]
    return Result(columns, rows, int(total or 0))


async def _project_list(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    projects = await project_rows(session, scope, q['filters'])
    health = await latest_health(session, [p.id for p in projects])
    limit = q.get('limit') or LIST_ROWS
    columns = [
        {'key': k, 'type': t}
        for k, t in (
            ('id', 'project'),
            ('name', 'string'),
            ('status', 'project_status'),
            ('health', 'rating'),
            ('owner', 'user'),
            ('due', 'date'),
        )
    ]
    rows = [
        [
            str(p.id),
            p.name,
            p.status,
            health[p.id].overall_effective if p.id in health else None,
            p.user_id,
            p.due_date.date().isoformat() if p.due_date else None,
        ]
        for p in projects[:limit]
    ]
    return Result(columns, rows, len(projects))


async def _milestones(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    """Open milestones due in the next 30 days (or the filter's period), overdue ones first."""
    f = q['filters']
    day = today()
    end = (
        date.fromisoformat(f['date_to'])
        if f.get('date_to')
        else day + timedelta(days=30)
    )
    base = (
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            *(await project_conditions(scope, f)),
            Task.deleted_at.is_(None),
            Task.behaviour == 'milestone',
            ~done_condition(),
            Task.due_date.is_not(None),
            Task.due_date
            < datetime.combine(end + timedelta(days=1), datetime.min.time()),
        )
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    tasks = (
        await session.scalars(
            base.order_by(Task.due_date).limit(q.get('limit') or LIST_ROWS)
        )
    ).all()
    names = await project_names(session, {t.project_id for t in tasks if t.project_id})
    columns = [
        {'key': k, 'type': t}
        for k, t in (
            ('id', 'id'),
            ('name', 'string'),
            ('project', 'project'),
            ('project_name', 'string'),
            ('due', 'date'),
            ('late', 'boolean'),
        )
    ]
    rows = [
        [
            str(t.id),
            t.name,
            str(t.project_id),
            names.get(str(t.project_id), ''),
            t.due_date.date().isoformat(),
            t.due_date.date() < day,
        ]
        for t in tasks
    ]
    return Result(columns, rows, int(total or 0))


async def _health_matrix(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    projects = await project_rows(session, scope, q['filters'])
    health = await latest_health(session, [p.id for p in projects])
    dims = ('schedule', 'budget', 'resources', 'scope', 'quality', 'risk')
    columns = [
        {'key': 'id', 'type': 'project'},
        {'key': 'name', 'type': 'string'},
        *({'key': d, 'type': 'rating'} for d in dims),
        {'key': 'overall', 'type': 'rating'},
    ]
    rows = []
    for p in projects[: q.get('limit') or LIST_ROWS]:
        h = health.get(p.id)
        rows.append(
            [
                str(p.id),
                p.name,
                *(getattr(h, d) if h else None for d in dims),
                h.overall_effective if h else None,
            ]
        )
    as_of = max((h.computed_at for h in health.values()), default=None)
    return Result(columns, rows, len(projects), as_of)


async def _activity(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    f = q['filters']
    a = PpmAuditEvent
    readable = select(Project.id).where(*(await project_conditions(scope, f)))
    rows = (
        await session.execute(
            select(a)
            .where(a.project_id.in_(readable), ~a.event.like('ppm.project.health%'))
            .order_by(a.occurred_at.desc())
            .limit(q.get('limit') or 20)
        )
    ).scalars()
    events = list(rows)
    names = await project_names(session, {e.project_id for e in events if e.project_id})
    columns = [
        {'key': k, 'type': t}
        for k, t in (
            ('occurred_at', 'datetime'),
            ('event', 'string'),
            ('actor', 'user'),
            ('subject_type', 'string'),
            ('subject_id', 'id'),
            ('project', 'project'),
            ('project_name', 'string'),
            ('title', 'string'),
            ('data', 'json'),
        )
    ]
    out = [
        [
            e.occurred_at.isoformat(),
            e.event,
            e.actor_name or e.actor_ref,
            e.subject_type,
            e.subject_id,
            str(e.project_id) if e.project_id else None,
            names.get(str(e.project_id), ''),
            (e.data or {}).get('name') or (e.data or {}).get('title'),
            e.data or {},
        ]
        for e in events
    ]
    return Result(columns, out, len(out))


async def _approvals(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    """Approvals whose current step waits for the viewer (My dashboard)."""
    from . import _approvals as approvals  # approvals import work items: late import

    rows = await approvals.waiting_for(session, scope)
    names = await project_names(
        session, {a.project_id for a, _ in rows if a.project_id}
    )
    columns = [
        {'key': k, 'type': t}
        for k, t in (
            ('id', 'id'),
            ('title', 'string'),
            ('subject_type', 'string'),
            ('subject_id', 'id'),
            ('project', 'project'),
            ('project_name', 'string'),
            ('requested_by', 'user'),
            ('due', 'date'),
        )
    ]
    out = [
        [
            str(a.id),
            a.title,
            a.subject_type,
            a.subject_id,
            str(a.project_id) if a.project_id else None,
            names.get(str(a.project_id), '') if a.project_id else '',
            a.requested_by,
            a.due_at.date().isoformat() if a.due_at else None,
        ]
        for a, _ in rows[: q.get('limit') or LIST_ROWS]
    ]
    return Result(columns, out, len(rows))


async def _one_project(
    session: DBAsyncScopedSession, scope: RequestScope, f: dict[str, Any]
) -> ews_models.Project:
    ids = f.get('project_ids') or []
    if len(ids) != 1:
        raise _error('this widget needs exactly one project (filters.project_ids)')
    return await access.load_project(session, scope, ids[0])


async def _health_card(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    """The project's health: overall (effective, computed) then each dimension with its main reason."""
    from . import (
        _health as health,
    )  # health imports the controllers' helpers: late import

    project = await _one_project(session, scope, q['filters'])
    row = await health.current(session, project)
    columns = [
        {'key': 'dimension', 'type': 'string'},
        {'key': 'rating', 'type': 'rating'},
        {'key': 'computed', 'type': 'rating'},
        {'key': 'reason', 'type': 'reason'},
    ]
    reasons = row.reasons or {}
    rows: list[list[Any]] = [['overall', row.overall_effective, row.overall, None]]
    for d in ('schedule', 'budget', 'resources', 'scope', 'quality', 'risk'):
        main = (reasons.get(d) or [None])[0]
        rows.append([d, getattr(row, d), getattr(row, d), main])
    return Result(columns, rows, len(rows), row.computed_at)


async def _series(
    session: DBAsyncScopedSession, scope: RequestScope, q: dict[str, Any]
) -> Result:
    from . import _stats as stats  # statistics read time / effort helpers: late import

    f = q['filters']
    project = await _one_project(session, scope, f)
    data = await stats.series(
        session,
        project,
        q['metric'],
        start=date.fromisoformat(f['date_from']) if f.get('date_from') else None,
        end=date.fromisoformat(f['date_to']) if f.get('date_to') else None,
    )
    points = data['points']
    keys = [k for k in (points[0] if points else {'date': None}) if k != 'date']
    if not points:
        keys = {
            'burnup': ['total', 'done'],
            'burndown': ['remaining', 'ideal'],
            'throughput': ['completed'],
        }[q['metric']]
    columns = [
        {'key': 'date', 'type': 'date'},
        *({'key': k, 'type': data['unit']} for k in keys),
    ]
    rows = [[p['date'].isoformat(), *(p.get(k) for k in keys)] for p in points]
    return Result(columns, rows, len(rows), data['as_of'])


RUNNERS = {
    'items': _items,
    'projects': _projects_source,
    'time': _time,
    'trend': _trend,
    'kpi': _kpi,
    'item_list': _item_list,
    'project_list': _project_list,
    'milestones': _milestones,
    'health_matrix': _health_matrix,
    'activity': _activity,
    'approvals': _approvals,
    'health': _health_card,
    'series': _series,
}


async def run(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    query: dict[str, Any],
    *extra_filters: dict[str, Any] | None,
) -> Result:
    """Run a (cleaned) query with the viewer's scope; ``extra_filters`` = dashboard bar then request (later wins)."""
    q = clean_query(query)
    q['filters'] = clean_filters(
        merge_filters(*extra_filters, q['filters']) if extra_filters else q['filters']
    )
    result = await RUNNERS[q['source']](session, scope, q)
    if result.as_of is None:
        result.as_of = datetime.now(UTC)
    return result
