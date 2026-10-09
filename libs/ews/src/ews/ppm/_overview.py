"""Server-side figures (ADR-27; they used to be computed in the browser): the PPM overview (project total, the most
frequent statuses with their catalog colour, recently active projects) and a project's metrics (counts per band,
overdue / due soon, workload per assignee, schedule health). One formula for every screen and, later, dashboards
and AI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from sqlalchemy import and_, func, or_, select

from ews.security import RequestScope

from . import _access as access
from . import _behaviours as behaviours
from . import _work_items as items
from . import _workflow_service as wfs
from . import workflow_catalog as catalog
from ._project_status import PROJECT_STATUS_CATALOG, project_status_color

DUE_SOON_DAYS = 7
UPCOMING_DAYS = 14
AT_RISK_POINTS = 15
Project = ews_models.Project
Task = ews_models.Task


async def overview(
    session: DBAsyncScopedSession, scope: RequestScope, recent: int = 10
) -> dict[str, Any]:
    readable = await access.readable_projects(scope)
    base = select(Project).where(readable, Project.kind == 'project')
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        select(Project.status, func.count(Project.id))
        .where(readable, Project.kind == 'project')
        .group_by(Project.status)
    )
    groups = {s.value: g.value for s, (_, g) in PROJECT_STATUS_CATALOG.items()}
    statuses = sorted(
        (
            {
                'value': status or 'New',
                'color': project_status_color(status),
                'group': groups.get(status or '', 'other'),
                'count': int(count),
            }
            for status, count in rows.all()
        ),
        key=lambda s: (-s['count'], s['value']),
    )
    latest = list(
        (
            await session.scalars(
                base.order_by(
                    Project.last_activity_at.desc().nulls_last(), Project.id.desc()
                ).limit(max(1, min(recent, 50)))
            )
        ).all()
    )
    return {
        'total': int(total or 0),
        'statuses': statuses,
        'recent': latest,
        **await _tiles(session, scope, readable),
    }


CLOSED_STATUSES = ('Completed', 'Cancelled', 'Archived', 'Template', 'Inactive')
RISK_STATUSES = ('At Risk', 'Blocked', 'Delayed')


async def _tiles(session: DBAsyncScopedSession, scope: RequestScope, readable: Any) -> dict[str, int]:
    """Ppm-1901: open projects (status not closed), at risk (latest health 🔴 when the health capability is on, else
    the risk statuses), my overdue items, my items due within 7 days."""
    from db.models.ppm import PpmHealthSnapshot as H

    from . import _settings
    from . import _widgets as widgets

    open_projects = and_(
        readable,
        Project.kind == 'project',
        or_(Project.status.is_(None), Project.status.not_in(CLOSED_STATUSES)),
    )
    open_count = await session.scalar(select(func.count(Project.id)).where(open_projects))
    if await _settings.enabled(session, scope, 'health'):
        latest = (
            select(H.project_id, H.overall_effective)
            .distinct(H.project_id)
            .order_by(H.project_id, H.snapshot_date.desc())
            .subquery()
        )
        at_risk = await session.scalar(
            select(func.count(Project.id))
            .join(latest, latest.c.project_id == Project.id)
            .where(open_projects, latest.c.overall_effective == 'red')
        )
    else:
        at_risk = await session.scalar(
            select(func.count(Project.id)).where(open_projects, Project.status.in_(RISK_STATUSES))
        )
    day = datetime.combine(datetime.now(UTC).date(), datetime.min.time())
    mine = (
        select(func.count(Task.id))
        .join(Project, Project.id == Task.project_id)
        .where(
            readable,
            Project.kind.in_(('project', 'personal')),
            Task.deleted_at.is_(None),
            widgets.counted_condition(),
            ~widgets.done_condition(),
            func.lower(Task.user_id).in_(widgets.me_refs(scope)),
        )
    )
    my_overdue = await session.scalar(mine.where(Task.due_date < day))
    my_week = await session.scalar(mine.where(Task.due_date >= day, Task.due_date < day + timedelta(days=8)))
    return {
        'open': int(open_count or 0),
        'at_risk': int(at_risk or 0),
        'my_overdue': int(my_overdue or 0),
        'my_due_week': int(my_week or 0),
    }


def _days_until(day: date | None, today: date) -> int | None:
    return (day - today).days if day is not None else None


def schedule_health(
    start: date | None, due: date | None, progress: int, today: date
) -> dict[str, Any]:
    """Progress vs the elapsed share of start → due: behind by more than 15 points = ``atRisk``; past due and not
    finished = ``overdue`` (project quick view, health spec schedule dimension)."""
    days_left = _days_until(due, today)
    if progress >= 100:
        return {
            'health': 'completed',
            'days_left': days_left,
            'elapsed': None if days_left is None else 100,
        }
    if days_left is None:
        return {'health': 'unscheduled'}
    if days_left < 0:
        return {'health': 'overdue', 'days_left': days_left, 'elapsed': 100}
    since = _days_until(start, today)
    if since is None:
        return {'health': 'onTrack', 'days_left': days_left}
    if since > 0:
        return {'health': 'notStarted', 'days_left': days_left, 'elapsed': 0}
    span = days_left - since
    elapsed = round(-since / span * 100) if span > 0 else 100
    return {
        'health': 'atRisk' if elapsed - progress > AT_RISK_POINTS else 'onTrack',
        'days_left': days_left,
        'elapsed': elapsed,
    }


@dataclass(slots=True)
class Person:
    user: str | None
    open: int = 0
    overdue: int = 0
    done: int = 0
    total: int = 0


@dataclass(slots=True)
class Metrics:
    total: int = 0
    done: int = 0
    open: int = 0
    overdue: int = 0
    due_soon: int = 0
    bands: dict[str, int] = field(
        default_factory=lambda: {'initial': 0, 'active': 0, 'review': 0, 'done': 0}
    )
    overdue_tasks: list[Task] = field(default_factory=list)
    upcoming_tasks: list[Task] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    schedule: dict[str, Any] = field(default_factory=dict)
    progress: int = 0


async def project_metrics(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    today: date | None = None,
) -> Metrics:
    """Counts, attention lists, workload and schedule health of a project's counted items (Ppm-0004)."""
    today = today or datetime.now(UTC).date()
    stages: dict[UUID, Any] = {}
    workflows = await wfs.load_workflows(session, project.id)
    for st_list in (await wfs.load_stages(session, [w.id for w in workflows])).values():
        stages.update({s.id: s for s in st_list})
    excluded = catalog.excluded_stage_types()
    tasks = [
        t
        for t in (
            await session.scalars(
                select(Task).where(
                    Task.project_id == project.id, Task.deleted_at.is_(None)
                )
            )
        ).all()
        if t.stage_type not in excluded and behaviours.counts(t.behaviour)
    ]
    m = Metrics()
    people: dict[str, Person] = {}
    for t in tasks:
        done = items.is_done(t)
        stage_type = (
            stages[t.stage_id].stage_type if t.stage_id in stages else t.stage_type
        )
        info = catalog.stage_type_info(stage_type)
        band = 'done' if done else (info.band if info else 'initial')
        if band not in ('active', 'review', 'done'):
            band = 'initial'
        m.bands[band] += 1
        due = t.due_date.date() if t.due_date else None
        days = _days_until(due, today)
        overdue = not done and days is not None and days < 0
        if overdue:
            m.overdue_tasks.append(t)
        elif not done and days is not None and days <= UPCOMING_DAYS:
            m.upcoming_tasks.append(t)
            if days <= DUE_SOON_DAYS:
                m.due_soon += 1
        key = t.user_id or ''
        person = people.setdefault(key, Person(t.user_id))
        person.total += 1
        person.done += int(done)
        person.open += int(not done)
        person.overdue += int(overdue)
    m.total = len(tasks)
    m.done = m.bands['done']
    m.open = m.total - m.done
    m.overdue = len(m.overdue_tasks)
    m.overdue_tasks.sort(key=lambda t: t.due_date or datetime.max)
    m.upcoming_tasks.sort(key=lambda t: t.due_date or datetime.max)
    m.people = sorted(
        people.values(), key=lambda p: (p.user is None, -p.open, -p.total, p.user or '')
    )
    m.progress = round(m.done * 100 / m.total) if m.total else 0
    m.schedule = schedule_health(
        project.start_date.date() if project.start_date else None,
        project.due_date.date() if project.due_date else None,
        m.progress,
        today,
    )
    return m
