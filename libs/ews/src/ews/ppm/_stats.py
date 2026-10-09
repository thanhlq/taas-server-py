"""Daily project statistics (taas-specs/ppm/reporting/dashboards-reports-spec.md §3, §5, ADR-45): one row per project
(and per running iteration) and UTC day — item counts, estimates, remaining and logged minutes — and the series read
by charts (burnup, burndown, throughput). Today's row is rewritten until the day ends (on read when stale, and by the
job ``ppm.daily_stats``), earlier rows are frozen; days without a row are simply missing in a series."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmAuditEvent, PpmProjectDailyStats
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from ews.notifications import register_job

from . import _time as time
from . import _work_items as items

Project = ews_models.Project
Task = ews_models.Task
Timelog = ews_models.Timelog
Iteration = ews_models.ProjectIteration
Stats = PpmProjectDailyStats

SERIES = ('burnup', 'burndown', 'throughput')
CLOSED = ('Completed', 'Cancelled', 'Archived', 'Template')
DEBOUNCE = timedelta(seconds=60)
BATCH = 200
MAX_DAYS = 731
OWN_EVENTS = (
    'ppm.project.health%',
    'ppm.health_policy.%',
    'ppm.dashboard.%',
    'ppm.export.%',
)
"""Events that never change the statistics."""


def today() -> date:
    return datetime.now(UTC).date()


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class Counts:
    items_total: int = 0
    items_done: int = 0
    items_open: int = 0
    items_overdue: int = 0
    items_added: int = 0
    items_completed: int = 0
    estimate_minutes: int = 0
    remaining_minutes: int = 0
    logged_minutes: int = 0
    billable_minutes: int = 0

    def as_dict(self) -> dict[str, int]:
        return {k: getattr(self, k) for k in self.__slots__}


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


def count_items(tasks: list[ews_models.Task], day: date) -> Counts:
    """Counts of the counted items (Ppm-0004: cancelled / rejected and RAID / requests left out)."""
    c = Counts()
    for t in tasks:
        if not items.counts_in_progress(t.stage_type, t.behaviour):
            continue
        c.items_total += 1
        effort = time.own_effort(t)
        c.estimate_minutes += effort.estimate
        if items.is_done(t):
            c.items_done += 1
            continue
        c.items_open += 1
        c.remaining_minutes += effort.remaining
        due = _day(t.due_date)
        if due and due < day:
            c.items_overdue += 1
    return c


async def _events_on(
    session: DBAsyncScopedSession,
    project_id: UUID,
    day: date,
    subjects: set[str] | None,
) -> tuple[int, int]:
    """Items created / completed on ``day`` (distinct subjects; ``subjects`` limits to an iteration's items)."""
    a = PpmAuditEvent
    start = datetime.combine(day, datetime.min.time(), UTC)
    rows = (
        await session.execute(
            select(a.event, a.subject_id).where(
                a.project_id == project_id,
                a.event.in_(('ppm.task.created', 'ppm.task.completed')),
                a.occurred_at >= start,
                a.occurred_at < start + timedelta(days=1),
            )
        )
    ).all()
    added, completed = set(), set()
    for event, subject in rows:
        if subjects is not None and subject not in subjects:
            continue
        (added if event == 'ppm.task.created' else completed).add(subject)
    return len(added), len(completed)


async def _logged_on(
    session: DBAsyncScopedSession,
    project_id: UUID,
    day: date,
    task_ids: set[UUID] | None,
) -> tuple[int, int]:
    q = select(
        func.coalesce(func.sum(Timelog.log_minutes), 0),
        func.coalesce(
            func.sum(Timelog.log_minutes).filter(Timelog.is_billable.is_(True)), 0
        ),
    ).where(
        Timelog.project_id == project_id,
        Timelog.entry_date == day,
        Timelog.deleted_at.is_(None),
    )
    if task_ids is not None:
        if not task_ids:
            return 0, 0
        q = q.where(Timelog.task_id.in_(task_ids))
    logged, billable = (await session.execute(q)).one()
    return int(logged or 0), int(billable or 0)


def _running(iteration: ews_models.ProjectIteration, day: date) -> bool:
    start, due = _day(iteration.start_date), _day(iteration.due_date)
    if iteration.status == 'completed':
        return False
    if start and due:
        return start <= day <= due
    return iteration.status == 'active'


async def refresh(
    session: DBAsyncScopedSession, project: ews_models.Project, day: date | None = None
) -> PpmProjectDailyStats:
    """Rewrite ``day``'s rows (project + running iterations) from the current items; returns the project row."""
    day = day or today()
    tasks = list(
        (
            await session.scalars(
                select(Task).where(
                    Task.project_id == project.id, Task.deleted_at.is_(None)
                )
            )
        ).all()
    )
    rows: list[tuple[UUID | None, Counts]] = []
    whole = count_items(tasks, day)
    whole.items_added, whole.items_completed = await _events_on(
        session, project.id, day, None
    )
    whole.logged_minutes, whole.billable_minutes = await _logged_on(
        session, project.id, day, None
    )
    rows.append((None, whole))
    iterations = (
        await session.scalars(
            select(Iteration).where(Iteration.project_id == project.id)
        )
    ).all()
    for it in iterations:
        if not _running(it, day):
            continue
        mine = [t for t in tasks if t.iteration_id == it.id]
        c = count_items(mine, day)
        c.items_added, c.items_completed = await _events_on(
            session, project.id, day, {str(t.id) for t in mine}
        )
        c.logged_minutes, c.billable_minutes = await _logged_on(
            session, project.id, day, {t.id for t in mine}
        )
        rows.append((it.id, c))
    now = _now()
    for iteration_id, c in rows:
        values = {**c.as_dict(), 'computed_at': now}
        where = (
            text('iteration_id is null')
            if iteration_id is None
            else text('iteration_id is not null')
        )
        await session.execute(
            pg_insert(Stats)
            .values(
                tenant_id=project.tenant_id,
                organization_id=project.organization_id,
                project_id=project.id,
                iteration_id=iteration_id,
                stats_date=day,
                **values,
            )
            .on_conflict_do_update(
                index_elements=[
                    Stats.project_id if iteration_id is None else Stats.iteration_id,
                    Stats.stats_date,
                ],
                index_where=where,
                set_={**values, 'updated_at': now},
            )
        )
    row = await session.scalar(
        select(Stats)
        .where(
            Stats.project_id == project.id,
            Stats.iteration_id.is_(None),
            Stats.stats_date == day,
        )
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def _last_event(
    session: DBAsyncScopedSession, project_id: UUID
) -> datetime | None:
    a = PpmAuditEvent
    return await session.scalar(
        select(func.max(a.occurred_at)).where(
            a.project_id == project_id, *(~a.event.like(p) for p in OWN_EVENTS)
        )
    )


async def current(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> PpmProjectDailyStats:
    """Today's project row, refreshed first when missing or older than the project's last event."""
    day = today()
    row = await session.scalar(
        select(Stats).where(
            Stats.project_id == project.id,
            Stats.iteration_id.is_(None),
            Stats.stats_date == day,
        )
    )
    if row is not None:
        last = await _last_event(session, project.id)
        if last is None or last <= row.computed_at:
            return row
    return await refresh(session, project, day)


# --- series ---------------------------------------------------------------------------------------


def _week(day: date) -> date:
    return day - timedelta(days=day.weekday())


async def series(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    kind: str,
    *,
    start: date | None = None,
    end: date | None = None,
    iteration_id: UUID | None = None,
) -> dict[str, Any]:
    """``burnup`` (scope vs done per day), ``burndown`` (remaining minutes — open items when nothing is estimated —
    vs an ideal straight line to the end), ``throughput`` (items completed per ISO week). Default: the project's
    start (else the last 30 days) to today."""
    if kind not in SERIES:
        raise ClientException(
            detail=f'series must be one of {", ".join(SERIES)}',
            extra={'code': 'invalid_series'},
        )
    await current(session, project)
    iteration = None
    if iteration_id is not None:
        iteration = await session.get(Iteration, iteration_id)
        if iteration is None or iteration.project_id != project.id:
            raise ClientException(
                detail='unknown iteration', extra={'code': 'invalid_iteration'}
            )
    planned_start = _day(iteration.start_date if iteration else project.start_date)
    planned_end = _day(iteration.due_date if iteration else project.due_date)
    end = end or today()
    start = start or (
        planned_start
        if planned_start and planned_start <= end
        else end - timedelta(days=29)
    )
    if start > end or (end - start).days > MAX_DAYS:
        raise ClientException(
            detail=f'the period must be 1 to {MAX_DAYS} days',
            extra={'code': 'invalid_period'},
        )
    q = select(Stats).where(
        Stats.project_id == project.id,
        Stats.stats_date >= start,
        Stats.stats_date <= end,
    )
    q = (
        q.where(Stats.iteration_id == iteration_id)
        if iteration_id
        else q.where(Stats.iteration_id.is_(None))
    )
    rows = list((await session.scalars(q.order_by(Stats.stats_date))).all())
    as_of = max((r.computed_at for r in rows), default=None)
    if kind == 'burnup':
        points = [
            {'date': r.stats_date, 'total': r.items_total, 'done': r.items_done}
            for r in rows
        ]
        return {'series': kind, 'unit': 'items', 'points': points, 'as_of': as_of}
    if kind == 'throughput':
        weeks: dict[date, int] = defaultdict(int)
        for r in rows:
            weeks[_week(r.stats_date)] += r.items_completed
        points = [{'date': w, 'completed': n} for w, n in sorted(weeks.items())]
        return {'series': kind, 'unit': 'items', 'points': points, 'as_of': as_of}
    estimated = any(r.estimate_minutes for r in rows)
    value = (lambda r: r.remaining_minutes) if estimated else (lambda r: r.items_open)
    points = [{'date': r.stats_date, 'remaining': value(r)} for r in rows]
    if rows:
        first, finish = (
            rows[0],
            planned_end if planned_end and planned_end > rows[0].stats_date else end,
        )
        span = max(1, (finish - first.stats_date).days)
        top = value(first)
        for p in points:
            p['ideal'] = max(
                0, round(top * (1 - (p['date'] - first.stats_date).days / span))
            )
    return {
        'series': kind,
        'unit': 'minutes' if estimated else 'items',
        'points': points,
        'as_of': as_of,
    }


# --- job ------------------------------------------------------------------------------------------


async def refresh_job(
    session: DBAsyncScopedSession,
    now: datetime | None = None,
    *,
    organization_id: UUID | None = None,
) -> int:
    """Job: today's rows of projects changed more than 60 s ago or without a row today (≤ ``BATCH`` per run, each in a
    savepoint); rows older than 2 years are dropped."""
    now = now or _now()
    day = now.date()
    s = aliased(Stats)
    a = PpmAuditEvent
    last = (
        select(func.max(a.occurred_at))
        .where(a.project_id == Project.id, *(~a.event.like(p) for p in OWN_EVENTS))
        .scalar_subquery()
    )
    ids = (
        await session.scalars(
            select(Project.id)
            .outerjoin(
                s,
                and_(
                    s.project_id == Project.id,
                    s.iteration_id.is_(None),
                    s.stats_date == day,
                ),
            )
            .where(
                Project.kind == 'project',
                Project.deleted_at.is_(None),
                or_(Project.status.is_(None), Project.status.not_in(CLOSED)),
                *(
                    [Project.organization_id == organization_id]
                    if organization_id
                    else []
                ),
                or_(s.id.is_(None), and_(last > s.computed_at, last < now - DEBOUNCE)),
            )
            .order_by(Project.id)
            .limit(BATCH)
        )
    ).all()
    for project_id in ids:
        project = await session.get(Project, project_id)
        if project is None:
            continue
        async with session.begin_nested():
            await refresh(session, project, day)
    await session.execute(
        delete(Stats).where(Stats.stats_date < day - timedelta(days=MAX_DAYS))
    )
    return len(ids)


register_job('ppm.daily_stats', 300, refresh_job)
