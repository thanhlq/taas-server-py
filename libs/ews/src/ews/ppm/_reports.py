"""PPM standard reports and exports (taas-specs/ppm/reporting/dashboards-reports-spec.md §5 reports, Ppm-1950 V2,
Ppm-1970…1972, ADR-45): the V2 catalog (project status, overdue items, time by person, time by project), run with the
viewer's scope (≤ 10 000 rows), and CSV (UTF-8 BOM, formula-safe) / XLSX (typed cells) files of any report or widget
result with the column labels the caller sends (texts in the user's language)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import and_, func, select

from ews.security import RequestScope
from ews.shared import to_xlsx

from . import _widgets as widgets
from ._export import to_csv
from ._widgets import Result

Project = ews_models.Project
Task = ews_models.Task
Timelog = ews_models.Timelog

REPORTS: dict[str, dict[str, Any]] = {
    'status': {'params': ('project_ids', 'status', 'owner', 'labels')},
    'overdue_items': {'params': ('project_ids', 'owner', 'item_type')},
    'time_by_person': {'params': ('date_from', 'date_to', 'project_ids', 'owner')},
    'time_by_project': {'params': ('date_from', 'date_to', 'project_ids', 'owner')},
}
FORMATS = {
    'csv': 'text/csv; charset=utf-8',
    'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}
MAX_ROWS = widgets.MAX_ROWS


def _error(detail: str, code: str = 'invalid_report') -> ClientException:
    return ClientException(detail=detail, extra={'code': code})


def clean_params(key: str, params: Any) -> dict[str, Any]:
    spec = REPORTS.get(key)
    if spec is None:
        raise NotFoundException(detail='report not found')
    filters = widgets.clean_filters(params or {})
    unknown = set(filters) - set(spec['params'])
    if unknown:
        raise _error(f'unknown parameters: {", ".join(sorted(unknown))}')
    return filters


def _hours(minutes: int | None) -> float:
    return round((minutes or 0) / 60, 2)


async def _status(
    session: DBAsyncScopedSession, scope: RequestScope, f: dict[str, Any]
) -> Result:
    """One row per project: status, health, progress, open / overdue items, next milestone, due date, owner."""
    projects = await widgets.project_rows(session, scope, f, MAX_ROWS)
    ids = [p.id for p in projects]
    health = await widgets.latest_health(session, ids)
    midnight = datetime.combine(widgets.today(), datetime.min.time())
    counts: dict[UUID, tuple[int, int, int, int]] = {}
    milestones: dict[UUID, tuple[str, datetime]] = {}
    if ids:
        done = widgets.done_condition()
        rows = await session.execute(
            select(
                Task.project_id,
                func.count(Task.id),
                func.count(Task.id).filter(done),
                func.count(Task.id).filter(~done),
                func.count(Task.id).filter(and_(~done, Task.due_date < midnight)),
            )
            .where(
                Task.project_id.in_(ids),
                Task.deleted_at.is_(None),
                widgets.counted_condition(),
            )
            .group_by(Task.project_id)
        )
        counts = {
            r[0]: (int(r[1]), int(r[2]), int(r[3]), int(r[4])) for r in rows.all()
        }
        for t in (
            await session.scalars(
                select(Task)
                .where(
                    Task.project_id.in_(ids),
                    Task.deleted_at.is_(None),
                    Task.behaviour == 'milestone',
                    ~done,
                    Task.due_date.is_not(None),
                )
                .order_by(Task.project_id, Task.due_date)
                .distinct(Task.project_id)
            )
        ).all():
            milestones[t.project_id] = (t.name or '', t.due_date)
    columns = [
        {'key': k, 'type': t}
        for k, t in (
            ('id', 'project'),
            ('name', 'string'),
            ('status', 'project_status'),
            ('health', 'rating'),
            ('progress', 'percent'),
            ('open', 'number'),
            ('overdue', 'number'),
            ('next_milestone', 'string'),
            ('next_milestone_due', 'date'),
            ('due', 'date'),
            ('owner', 'user'),
        )
    ]
    out = []
    for p in projects:
        total, done_n, open_n, overdue = counts.get(p.id, (0, 0, 0, 0))
        m = milestones.get(p.id)
        out.append(
            [
                str(p.id),
                p.name,
                p.status,
                health[p.id].overall_effective if p.id in health else None,
                round(done_n * 100 / total) if total else 0,
                open_n,
                overdue,
                m[0] if m else None,
                m[1].date().isoformat() if m else None,
                p.due_date.date().isoformat() if p.due_date else None,
                p.user_id,
            ]
        )
    return Result(columns, out, len(out))


async def _overdue(
    session: DBAsyncScopedSession, scope: RequestScope, f: dict[str, Any]
) -> Result:
    """Open overdue items, most overdue first, with the days overdue."""
    base = (
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            *(await widgets.project_conditions(scope, f)),
            *widgets.item_conditions(scope, {**f, 'overdue': True}),
        )
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    tasks = (
        await session.scalars(base.order_by(Task.due_date, Task.id).limit(MAX_ROWS))
    ).all()
    names = await widgets.project_names(
        session, {t.project_id for t in tasks if t.project_id}
    )
    day = widgets.today()
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
            ('days_overdue', 'number'),
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
            t.due_date.date().isoformat(),
            (day - t.due_date.date()).days,
        ]
        for t in tasks
    ]
    return Result(columns, rows, int(total or 0))


def _period(f: dict[str, Any]) -> tuple[date, date]:
    end = date.fromisoformat(f['date_to']) if f.get('date_to') else widgets.today()
    start = (
        date.fromisoformat(f['date_from']) if f.get('date_from') else end.replace(day=1)
    )
    if start > end or (end - start).days > 731:
        raise _error('the period must be 1 to 732 days', 'invalid_period')
    return start, end


async def _time(
    session: DBAsyncScopedSession, scope: RequestScope, f: dict[str, Any], by: str
) -> Result:
    """Hours (and billable hours) per person × project, or per project × week, in the period (default this month)."""
    start, end = _period(f)
    key = (
        Timelog.user_id
        if by == 'person'
        else func.date_trunc('week', Timelog.entry_date)
    )
    conds = [
        Timelog.deleted_at.is_(None),
        Timelog.entry_date >= start,
        Timelog.entry_date <= end,
        *([Timelog.user_id == f['owner']] if f.get('owner') else []),
    ]
    rows = (
        await session.execute(
            select(
                key.label('k'),
                Timelog.project_id,
                func.coalesce(func.sum(Timelog.log_minutes), 0),
                func.coalesce(
                    func.sum(Timelog.log_minutes).filter(Timelog.is_billable.is_(True)),
                    0,
                ),
            )
            .join(Project, Project.id == Timelog.project_id)
            .where(*(await widgets.project_conditions(scope, f)), *conds)
            .group_by(key, Timelog.project_id)
            .order_by(key, Timelog.project_id)
            .limit(MAX_ROWS)
        )
    ).all()
    names = await widgets.project_names(session, {r[1] for r in rows if r[1]})
    if by == 'person':
        columns = [
            {'key': 'person', 'type': 'user'},
            {'key': 'project', 'type': 'project'},
            {'key': 'project_name', 'type': 'string'},
            {'key': 'hours', 'type': 'hours'},
            {'key': 'billable_hours', 'type': 'hours'},
        ]
        out = [
            [r[0], str(r[1]), names.get(str(r[1]), ''), _hours(r[2]), _hours(r[3])]
            for r in rows
        ]
    else:
        columns = [
            {'key': 'project', 'type': 'project'},
            {'key': 'project_name', 'type': 'string'},
            {'key': 'week', 'type': 'date'},
            {'key': 'hours', 'type': 'hours'},
            {'key': 'billable_hours', 'type': 'hours'},
        ]
        out = [
            [
                str(r[1]),
                names.get(str(r[1]), ''),
                r[0].date().isoformat(),
                _hours(r[2]),
                _hours(r[3]),
            ]
            for r in sorted(rows, key=lambda r: (names.get(str(r[1]), ''), r[0]))
        ]
    return Result(columns, out, len(out))


async def run(
    session: DBAsyncScopedSession, scope: RequestScope, key: str, params: Any
) -> Result:
    f = clean_params(key, params)
    if key == 'status':
        result = await _status(session, scope, f)
    elif key == 'overdue_items':
        result = await _overdue(session, scope, f)
    else:
        result = await _time(
            session, scope, f, 'person' if key == 'time_by_person' else 'project'
        )
    result.as_of = result.as_of or datetime.now().astimezone()
    return result


# --- files ----------------------------------------------------------------------------------------

HIDDEN = {'id', 'project', 'subject_id', 'data'}
"""Id columns left out of files (their names are next to them)."""


def _value(value: Any, kind: str) -> Any:
    if value is None:
        return None
    if kind == 'date' and isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return value
    if kind == 'datetime' and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, dict):
        return value.get('code')
    return value


def render(
    result: Result,
    fmt: str,
    *,
    labels: dict[str, str] | None = None,
    title: str = 'export',
) -> tuple[bytes, str, str]:
    """``(body, media type, file name)`` of a result: visible columns with the caller's labels (keys otherwise)."""
    if fmt not in FORMATS:
        raise _error('format must be csv or xlsx', 'invalid_format')
    keep = [i for i, c in enumerate(result.columns) if c['key'] not in HIDDEN]
    header = [
        (labels or {}).get(result.columns[i]['key']) or result.columns[i]['key']
        for i in keep
    ]
    rows = (
        [_value(row[i], result.columns[i]['type']) for i in keep] for row in result.rows
    )
    name = f'{title}-{widgets.today().isoformat()}.{fmt}'
    if fmt == 'csv':
        return to_csv(header, rows).encode('utf-8'), FORMATS['csv'], name
    return to_xlsx(header, rows, sheet=title), FORMATS['xlsx'], name
