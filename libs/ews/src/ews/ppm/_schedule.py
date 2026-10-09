"""Project schedule (taas-specs/ppm/schedule/schedule-spec.md): settings (mode, thresholds), phases, dependency links
with the cycle check, item schedule fields, the schedule read model and the recalculation of auto items.

The engine is pure (``_schedule_engine``); this module loads a project's items and links, maps them, writes the plan
of **auto** items back (``start_date`` / ``due_date``, ``schedule_version + 1``, one ``ppm.schedule.recalculated``
event) and keeps the schedule current through an event subscriber (Ppm-1060): item dates, duration, mode, constraint,
parent, done / reopen, create, delete, links and project schedule settings recalculate the project in the same
transaction. Manual projects write nothing — the engine only reports violations.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import DEPENDENCY_TYPES, LINK_TYPES, PpmPhase, PpmWorkItemLink
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException, NotFoundException
from sqlalchemy import exists, func, or_, select, update

from ews.security import RequestScope
from ews.shared import ConflictException, parse_uuid, utcnow

from . import _access as access
from . import _events as events
from . import _schedule_engine as engine
from . import _work_items as items
from . import workflow_catalog as catalog

Task = ews_models.Task
MODES = ('manual', 'auto')
CONSTRAINTS = ('asap', 'snet', 'mso', 'fnlt')
DEFAULTS: dict[str, Any] = {
    'mode': 'manual',
    'critical_float_days': 0,
    'default_duration_days': 1,
}
STARTED_BANDS = ('active', 'review', 'done')
"""First stage of these bands = the item's actual start (``started_at``)."""
TRIGGERS = (
    'start_date',
    'due_date',
    'duration_days',
    'schedule_mode',
    'constraint_type',
    'constraint_date',
    'parent_id',
    'completed_at',
    'stage_type',
    'behaviour',
)
"""Changed fields of ``ppm.task.updated`` that recalculate the project."""


def _error(detail: str, code: str, **extra: Any) -> ClientException:
    return ClientException(detail=detail, extra={'code': code, **extra})


def _when(value: datetime | date | str | None) -> datetime | date | None:
    """A request value (``as_dict`` gives ISO strings) as a ``datetime`` / ``date``."""
    if isinstance(value, str):
        return (
            datetime.fromisoformat(value)
            if len(value) > 10
            else date.fromisoformat(value)
        )
    return value


def _day(value: datetime | date | str | None) -> date | None:
    value = _when(value)
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


def _midnight(value: date) -> datetime:
    return datetime.combine(value, time())


# --- settings -------------------------------------------------------------------------------------


def settings_of(project: ews_models.Project) -> dict[str, Any]:
    """The project's schedule settings (``settings.schedule``) over the defaults."""
    raw = (
        project.settings.get('schedule') if isinstance(project.settings, dict) else None
    )
    return {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}


def clean_settings(patch: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Validated ``settings.schedule`` after a patch (null = default)."""
    out = {k: v for k, v in current.items() if k in DEFAULTS}
    for key, value in patch.items():
        if key not in DEFAULTS:
            raise ClientException(detail=f'unknown schedule setting {key!r}')
        if value is None:
            out.pop(key, None)
        elif key == 'mode':
            if value not in MODES:
                raise ClientException(detail=f'mode must be one of {", ".join(MODES)}')
            out[key] = value
        else:
            low = 0 if key == 'critical_float_days' else 1
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not low <= value <= 365
            ):
                raise ClientException(
                    detail=f'{key} must be an integer from {low} to 365'
                )
            out[key] = value
    return out


# --- loading + mapping ----------------------------------------------------------------------------


async def _tasks(
    session: DBAsyncScopedSession, project_id: UUID
) -> list[ews_models.Task]:
    return list(
        (
            await session.scalars(
                select(Task)
                .where(Task.project_id == project_id, Task.deleted_at.is_(None))
                .order_by(Task.id)
            )
        ).all()
    )


async def project_links(
    session: DBAsyncScopedSession, project_id: UUID
) -> list[PpmWorkItemLink]:
    lk = PpmWorkItemLink
    return list(
        (
            await session.scalars(
                select(lk)
                .where(
                    lk.deleted_at.is_(None),
                    or_(
                        lk.source_project_id == project_id,
                        lk.target_project_id == project_id,
                    ),
                )
                .order_by(lk.created_at)
            )
        ).all()
    )


def _item(t: ews_models.Task, mode: str) -> engine.Item:
    return engine.Item(
        id=str(t.id),
        start=_day(t.start_date),
        due=_day(t.due_date),
        duration=t.duration_days,
        milestone=t.behaviour == 'milestone',
        done=items.is_done(t),
        excluded=(t.stage_type or '') in catalog.excluded_stage_types(),
        manual=(t.schedule_mode or mode) == 'manual',
        constraint=t.constraint_type if t.constraint_type != 'asap' else None,
        constraint_date=_day(t.constraint_date),
        started=_day(t.started_at),
        finished=_day(t.completed_at),
        progress=t.progress or 0,
        parent_id=str(t.parent_id) if t.parent_id else None,
    )


def _link(row: PpmWorkItemLink) -> engine.Link:
    return engine.Link(
        id=str(row.id),
        source=str(row.source_task_id),
        target=str(row.target_task_id),
        type=row.type,
        lag=row.lag_days,
    )


@dataclass(slots=True)
class Computed:
    project: ews_models.Project
    settings: dict[str, Any]
    tasks: list[ews_models.Task]
    links: list[PpmWorkItemLink]
    schedule: engine.Schedule
    items: list[engine.Item]


async def compute(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    *,
    settings: dict[str, Any] | None = None,
    today: date | None = None,
) -> Computed:
    """The engine run of a project (nothing written)."""
    cfg = settings or settings_of(project)
    tasks = await _tasks(session, project.id)
    links = await project_links(session, project.id)
    mapped = [_item(t, cfg['mode']) for t in tasks]
    schedule = engine.compute(
        mapped,
        [_link(row) for row in links],
        project_start=_day(project.start_date),
        project_due=_day(project.due_date),
        today=today or utcnow().date(),
        default_duration=cfg['default_duration_days'],
        critical_float=cfg['critical_float_days'],
    )
    return Computed(project, cfg, tasks, links, schedule, mapped)


def planned_changes(run: Computed) -> list[dict[str, Any]]:
    """Auto items whose plan differs from their stored dates: ``[{task_id, start, due}]`` (the write-back)."""
    if run.schedule.cycle is not None:
        return []
    by_id = {str(t.id): t for t in run.tasks}
    out: list[dict[str, Any]] = []
    for it in run.items:
        r = run.schedule.items[it.id]
        if it.manual or it.done or it.excluded or r.summary or not r.scheduled:
            continue
        t = by_id[it.id]
        if (_day(t.start_date), _day(t.due_date)) == (r.start, r.due):
            continue
        out.append(
            {
                'task_id': it.id,
                'code': t.code,
                'start': [_day(t.start_date), r.start],
                'due': [_day(t.due_date), r.due],
            }
        )
    return out


_running: ContextVar[bool] = ContextVar('ppm_schedule_running', default=False)


@contextmanager
def batch() -> Iterator[None]:
    """Suspend the subscriber's recalculation (the caller recalculates once at the end)."""
    token = _running.set(True)
    try:
        yield
    finally:
        _running.reset(token)


async def recalculate(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    project: ews_models.Project,
    *,
    cause: str = 'schedule',
) -> list[dict[str, Any]]:
    """Write the plan of auto items back (Ppm-1060): the changed items, ``schedule_version + 1``, one event."""
    run = await compute(session, project)
    changes = planned_changes(run)
    if run.schedule.cycle is not None:
        log_data = {'cycle': run.schedule.cycle[:20]}
        await events.emit(
            session,
            scope,
            'ppm.schedule.cycle_detected',
            'project',
            project.id,
            project_id=project.id,
            data=log_data,
            cause=cause,
        )
        return []
    if not changes:
        return []
    by_id = {str(t.id): t for t in run.tasks}
    old_finish = max((_day(t.due_date) for t in run.tasks if t.due_date), default=None)
    for change in changes:
        t = by_id[change['task_id']]
        t.start_date = _midnight(change['start'][1])
        t.due_date = _midnight(change['due'][1])
    project.schedule_version = (project.schedule_version or 0) + 1
    await session.flush()
    for parent in {
        t.parent_id for t in (by_id[c['task_id']] for c in changes) if t.parent_id
    }:
        await items.refresh_rollups(session, parent)
    await events.emit(
        session,
        scope,
        'ppm.schedule.recalculated',
        'project',
        project.id,
        project_id=project.id,
        data={
            'schedule_version': project.schedule_version,
            'cause': cause,
            'finish': [old_finish, run.schedule.finish],
            'changes': changes[:500],
        },
        cause='schedule',
    )
    return changes


async def has_auto_items(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> bool:
    if settings_of(project)['mode'] == 'auto':
        return True
    return bool(
        await session.scalar(
            select(
                exists().where(
                    Task.project_id == project.id,
                    Task.deleted_at.is_(None),
                    Task.schedule_mode == 'auto',
                )
            )
        )
    )


# --- item schedule fields (task PATCH) ------------------------------------------------------------


async def check_item_fields(
    session: DBAsyncScopedSession,
    task: ews_models.Task,
    project: ews_models.Project,
    fields: dict[str, Any],
    clear: set[str],
) -> None:
    """Validate ``phase_id`` · ``duration_days`` · ``schedule_mode`` · ``constraint_*`` of a PATCH (in place)."""
    for key in ('start_date', 'due_date', 'constraint_date'):
        if isinstance(fields.get(key), str):
            when = _when(fields[key])
            fields[key] = when if isinstance(when, datetime) else _midnight(when)  # type: ignore[arg-type]
    if fields.get('phase_id') is not None:
        if task.parent_id is not None and 'parent_id' not in clear:
            raise _error("a subtask is in its parent item's phase", 'phase_on_subtask')
        fields['phase_id'] = (await load_phase(session, project, fields['phase_id'])).id
    if fields.get('duration_days') is not None:
        if task.behaviour == 'milestone':
            raise _error('a milestone has no duration', 'invalid_dates')
        if not 1 <= fields['duration_days'] <= 3650:
            raise ClientException(detail='duration_days must be from 1 to 3650')
    mode = fields.get('schedule_mode')
    if mode is not None and mode not in MODES:
        raise ClientException(detail=f'schedule_mode must be one of {", ".join(MODES)}')
    kind = fields.get('constraint_type')
    if kind is not None:
        if kind not in CONSTRAINTS:
            raise ClientException(
                detail=f'constraint_type must be one of {", ".join(CONSTRAINTS)}'
            )
        if kind == 'asap':
            fields['constraint_date'] = None
        elif fields.get('constraint_date') is None and task.constraint_date is None:
            raise ClientException(detail=f'constraint {kind} needs a constraint_date')
    start = (
        fields.get('start_date', task.start_date) if 'start_date' not in clear else None
    )
    due = fields.get('due_date', task.due_date) if 'due_date' not in clear else None
    if start and due and _day(start) > _day(due):  # type: ignore[operator]
        raise _error('the start date is after the due date', 'invalid_dates')


# --- phases (Ppm-1001…1003) -----------------------------------------------------------------------


def phase_to_out(p: PpmPhase, items_count: int = 0) -> dict[str, Any]:
    return {
        'id': str(p.id),
        'project_id': str(p.project_id),
        'name': p.name,
        'description': p.description,
        'color': p.color,
        'position': p.position,
        'planned_start': p.planned_start,
        'planned_finish': p.planned_finish,
        'item_count': items_count,
    }


async def phases_of(session: DBAsyncScopedSession, project_id: UUID) -> list[PpmPhase]:
    return list(
        (
            await session.scalars(
                select(PpmPhase)
                .where(PpmPhase.project_id == project_id, PpmPhase.deleted_at.is_(None))
                .order_by(PpmPhase.position, PpmPhase.created_at)
            )
        ).all()
    )


async def phase_counts(
    session: DBAsyncScopedSession, project_id: UUID
) -> dict[UUID, int]:
    rows = await session.execute(
        select(Task.phase_id, func.count())
        .where(
            Task.project_id == project_id,
            Task.deleted_at.is_(None),
            Task.phase_id.is_not(None),
        )
        .group_by(Task.phase_id)
    )
    return dict(rows.tuples().all())


async def load_phase(
    session: DBAsyncScopedSession, project: ews_models.Project, phase_id: object
) -> PpmPhase:
    pid = parse_uuid(phase_id, 'phase')
    row = await session.scalar(
        select(PpmPhase).where(
            PpmPhase.id == pid,
            PpmPhase.project_id == project.id,
            PpmPhase.deleted_at.is_(None),
        )
    )
    if row is None:
        raise NotFoundException(detail='phase not found')
    return row


PHASE_FIELDS = ('name', 'description', 'color', 'planned_start', 'planned_finish')


def _clean_phase(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in data.items() if k in PHASE_FIELDS}
    if 'name' in out:
        out['name'] = (out['name'] or '').strip()[:200]
        if not out['name']:
            raise ClientException(detail='a phase needs a name')
    for key in ('planned_start', 'planned_finish'):
        if isinstance(out.get(key), str):
            out[key] = date.fromisoformat(out[key][:10])
    start, finish = out.get('planned_start'), out.get('planned_finish')
    if start and finish and start > finish:
        raise _error('the planned start is after the planned finish', 'invalid_dates')
    return out


async def create_phase(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    data: dict[str, Any],
) -> PpmPhase:
    clean = _clean_phase({'name': '', **data})
    last = await session.scalar(
        select(func.max(PpmPhase.position)).where(
            PpmPhase.project_id == project.id, PpmPhase.deleted_at.is_(None)
        )
    )
    row = PpmPhase(
        tenant_id=project.tenant_id or scope.tenant_id,
        project_id=project.id,
        position=(last or 0) + 1,
        **clean,
    )
    session.add(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.phase.created',
        'phase',
        row.id,
        project_id=project.id,
        data={'name': row.name},
    )
    return row


async def update_phase(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    row: PpmPhase,
    data: dict[str, Any],
    clear: set[str],
) -> PpmPhase:
    before = events.snapshot(row, PHASE_FIELDS)
    clean = _clean_phase(data)
    for key in clear & {'description', 'color', 'planned_start', 'planned_finish'}:
        clean[key] = None
    merged = {**{k: getattr(row, k) for k in PHASE_FIELDS}, **clean}
    if (
        merged['planned_start']
        and merged['planned_finish']
        and merged['planned_start'] > merged['planned_finish']
    ):
        raise _error('the planned start is after the planned finish', 'invalid_dates')
    for key, value in clean.items():
        setattr(row, key, value)
    await session.flush()
    changes = events.diff(before, events.snapshot(row, PHASE_FIELDS))
    if changes:
        await events.emit(
            session,
            scope,
            'ppm.phase.updated',
            'phase',
            row.id,
            project_id=project.id,
            changes=changes,
            data={'name': row.name},
        )
    return row


async def delete_phase(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    row: PpmPhase,
) -> None:
    """Delete a phase; its items stay, without a phase (Ppm-1003)."""
    await session.execute(
        update(Task).where(Task.phase_id == row.id).values(phase_id=None)
    )
    row.deleted_at = utcnow()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.phase.deleted',
        'phase',
        row.id,
        project_id=project.id,
        data={'name': row.name},
    )


async def order_phases(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    phase_ids: list[str],
) -> list[PpmPhase]:
    rows = await phases_of(session, project.id)
    by_id = {str(r.id): r for r in rows}
    if sorted(phase_ids) != sorted(by_id):
        raise ClientException(
            detail='phase_ids must list every phase of the project once'
        )
    for i, pid in enumerate(phase_ids):
        by_id[pid].position = float(i + 1)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.phase.updated',
        'project',
        project.id,
        project_id=project.id,
        data={'order': phase_ids},
    )
    return sorted(rows, key=lambda r: r.position)


# --- links (Ppm-1020…1025) ------------------------------------------------------------------------


def link_to_out(
    row: PpmWorkItemLink, tasks: dict[UUID, ews_models.Task] | None = None
) -> dict[str, Any]:
    src = (tasks or {}).get(row.source_task_id)
    dst = (tasks or {}).get(row.target_task_id)
    return {
        'id': str(row.id),
        'source_task_id': str(row.source_task_id),
        'target_task_id': str(row.target_task_id),
        'source_project_id': str(row.source_project_id),
        'target_project_id': str(row.target_project_id),
        'type': row.type,
        'lag_days': row.lag_days,
        'source_code': src.code if src else None,
        'source_name': src.name if src else None,
        'target_code': dst.code if dst else None,
        'target_name': dst.name if dst else None,
        'created_by': row.created_by,
        'created_at': row.created_at,
    }


async def task_links(
    session: DBAsyncScopedSession, task_id: UUID
) -> tuple[list[PpmWorkItemLink], dict[UUID, ews_models.Task]]:
    """Links of an item in both directions + the items they name."""
    lk = PpmWorkItemLink
    rows = list(
        (
            await session.scalars(
                select(lk)
                .where(
                    lk.deleted_at.is_(None),
                    or_(lk.source_task_id == task_id, lk.target_task_id == task_id),
                )
                .order_by(lk.created_at)
            )
        ).all()
    )
    ids = {r.source_task_id for r in rows} | {r.target_task_id for r in rows}
    tasks = (
        {
            t.id: t
            for t in (await session.scalars(select(Task).where(Task.id.in_(ids)))).all()
        }
        if ids
        else {}
    )
    return rows, tasks


async def load_link(
    session: DBAsyncScopedSession, task_id: UUID, link_id: object
) -> PpmWorkItemLink:
    lk = PpmWorkItemLink
    row = await session.scalar(
        select(lk).where(
            lk.id == parse_uuid(link_id, 'link'),
            lk.deleted_at.is_(None),
            or_(lk.source_task_id == task_id, lk.target_task_id == task_id),
        )
    )
    if row is None:
        raise NotFoundException(detail='link not found')
    return row


def _check_type(kind: str, lag: int) -> None:
    if kind not in LINK_TYPES:
        raise _error(f'type must be one of {", ".join(LINK_TYPES)}', 'invalid_link')
    if not -365 <= lag <= 365:
        raise _error('lag_days must be from -365 to 365', 'invalid_link')
    if lag and kind not in DEPENDENCY_TYPES:
        raise _error(f'a {kind} link has no lag', 'invalid_link')


async def check_link(
    session: DBAsyncScopedSession,
    source: ews_models.Task,
    target: ews_models.Task,
    kind: str,
    *,
    ignore: UUID | None = None,
) -> None:
    """400 ``invalid_link`` (self, other project — V4, second dependency on the pair) · ``dependency_cycle`` (§5.4)."""
    if source.id == target.id:
        raise _error('an item cannot depend on itself', 'invalid_link')
    if source.project_id != target.project_id:
        raise _error('links between projects come with V4', 'invalid_link')
    lk = PpmWorkItemLink
    if kind in DEPENDENCY_TYPES:
        pair = await session.scalar(
            select(lk.id).where(
                lk.deleted_at.is_(None),
                lk.type.in_(DEPENDENCY_TYPES),
                lk.id != ignore if ignore else True,
                or_(
                    (lk.source_task_id == source.id) & (lk.target_task_id == target.id),
                    (lk.source_task_id == target.id) & (lk.target_task_id == source.id),
                ),
            )
        )
        if pair is not None:
            raise _error('these items already have a dependency', 'invalid_link')
    if kind not in (*DEPENDENCY_TYPES, 'blocks'):
        return
    tasks = await _tasks(session, source.project_id)  # type: ignore[arg-type]
    graph = {
        str(t.id): engine.Item(
            id=str(t.id), parent_id=str(t.parent_id) if t.parent_id else None
        )
        for t in tasks
    }
    links = [
        _link(r)
        for r in await project_links(session, source.project_id)
        if r.id != ignore
    ]  # type: ignore[arg-type]
    path = engine.find_cycle(
        graph, links, engine.Link('new', str(source.id), str(target.id), kind)
    )
    if path:
        codes = {str(t.id): t.code for t in tasks}
        raise _error(
            'this link would create a dependency cycle',
            'dependency_cycle',
            path=path,
            codes=[codes.get(p) for p in path],
        )


async def create_link(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    source: ews_models.Task,
    target: ews_models.Task,
    kind: str,
    lag: int,
) -> PpmWorkItemLink:
    _check_type(kind, lag)
    await check_link(session, source, target, kind)
    row = PpmWorkItemLink(
        tenant_id=project.tenant_id or scope.tenant_id,
        organization_id=project.organization_id or scope.organization_id,
        source_task_id=source.id,
        target_task_id=target.id,
        source_project_id=source.project_id,
        target_project_id=target.project_id,
        type=kind,
        lag_days=lag,
        created_by=access.author(scope),
    )
    session.add(row)
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.item_link.created',
        'item_link',
        row.id,
        project_id=project.id,
        data=_link_data(row, source, target),
    )
    return row


def _link_data(
    row: PpmWorkItemLink, source: ews_models.Task, target: ews_models.Task
) -> dict[str, Any]:
    return {
        'source_task_id': str(row.source_task_id),
        'target_task_id': str(row.target_task_id),
        'source_code': source.code,
        'target_code': target.code,
        'type': row.type,
        'lag_days': row.lag_days,
    }


async def update_link(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    row: PpmWorkItemLink,
    *,
    kind: str | None,
    lag: int | None,
) -> PpmWorkItemLink:
    new_kind = kind or row.type
    new_lag = (
        lag
        if lag is not None
        else (row.lag_days if new_kind in DEPENDENCY_TYPES else 0)
    )
    _check_type(new_kind, new_lag)
    source = await session.get(Task, row.source_task_id)
    target = await session.get(Task, row.target_task_id)
    if source is None or target is None:
        raise NotFoundException(detail='link not found')
    if new_kind != row.type:
        await check_link(session, source, target, new_kind, ignore=row.id)
    before = {'type': row.type, 'lag_days': row.lag_days}
    row.type, row.lag_days = new_kind, new_lag
    await session.flush()
    changes = events.diff(before, {'type': row.type, 'lag_days': row.lag_days})
    if changes:
        await events.emit(
            session,
            scope,
            'ppm.item_link.updated',
            'item_link',
            row.id,
            project_id=project.id,
            changes=changes,
            data=_link_data(row, source, target),
        )
    return row


async def delete_link(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    project_id: UUID,
    row: PpmWorkItemLink,
) -> None:
    row.deleted_at = utcnow()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.item_link.deleted',
        'item_link',
        row.id,
        project_id=project_id,
        data={
            'source_task_id': str(row.source_task_id),
            'target_task_id': str(row.target_task_id),
            'type': row.type,
        },
    )


async def _drop_links(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    project_id: UUID,
    task_ids: list[UUID],
) -> None:
    """Ppm-1025: a deleted item loses its links; an item moved to another project loses its dependency links."""
    lk = PpmWorkItemLink
    rows = (
        await session.scalars(
            select(lk).where(
                lk.deleted_at.is_(None),
                or_(lk.source_task_id.in_(task_ids), lk.target_task_id.in_(task_ids)),
            )
        )
    ).all()
    for row in rows:
        await delete_link(session, scope, project_id, row)


# --- read model -----------------------------------------------------------------------------------


def _phase_rollup(
    phase: PpmPhase,
    members: list[ews_models.Task],
    results: dict[str, engine.Result],
    tasks_by_id: dict[str, engine.Item],
) -> dict[str, Any]:
    scheduled = [results[str(t.id)] for t in members if results[str(t.id)].scheduled]
    leaves = [tasks_by_id[str(t.id)] for t in members]
    start = min((r.start for r in scheduled if r.start), default=None)
    due = max((r.due for r in scheduled if r.due), default=None)
    done = [t for t in leaves if t.done or t.excluded]
    status = 'not_started'
    if leaves and len(done) == len(leaves):
        status = 'done'
    elif any(t.done or t.started or t.progress for t in leaves):
        status = 'in_progress'
    outside = bool(
        (phase.planned_start and start and start < phase.planned_start)
        or (phase.planned_finish and due and due > phase.planned_finish)
    )
    return {
        'start': start or phase.planned_start,
        'due': due or phase.planned_finish,
        'progress': engine.schedule_progress(leaves, results),
        'status': status,
        'outside_window': outside,
    }


async def read(
    session: DBAsyncScopedSession, project: ews_models.Project
) -> dict[str, Any]:
    """The Gantt payload (§7): settings, phases with roll-ups, items with plan / forecast / float, links."""
    run = await compute(session, project)
    results = run.schedule.items
    by_id = {str(t.id): t for t in run.tasks}
    mapped = {i.id: i for i in run.items}

    def top(t: ews_models.Task) -> ews_models.Task:
        seen: set[UUID] = set()
        while t.parent_id and str(t.parent_id) in by_id and t.id not in seen:
            seen.add(t.id)
            t = by_id[str(t.parent_id)]
        return t

    phases = await phases_of(session, project.id)
    members: dict[UUID, list[ews_models.Task]] = {p.id: [] for p in phases}
    out_items: list[dict[str, Any]] = []
    for t in run.tasks:
        r = results[str(t.id)]
        phase_id = top(t).phase_id
        if phase_id in members and not r.summary:
            members[phase_id].append(t)
        it = mapped[str(t.id)]
        out_items.append(
            {
                'id': str(t.id),
                'code': t.code,
                'name': t.name,
                'parent_id': str(t.parent_id) if t.parent_id else None,
                'phase_id': str(phase_id) if phase_id in members else None,
                'behaviour': t.behaviour,
                'work_item_type': t.work_item_type,
                'stage_type': t.stage_type,
                'user_id': t.user_id,
                'progress': 100 if it.done else (t.progress or 0),
                'milestone': it.milestone,
                'done': it.done,
                'excluded': it.excluded,
                'mode': 'manual' if it.manual else 'auto',
                'schedule_mode': t.schedule_mode,
                'constraint_type': t.constraint_type,
                'constraint_date': _day(t.constraint_date),
                'started_at': _day(t.started_at),
                'scheduled': r.scheduled,
                'summary': r.summary,
                'start': r.start,
                'due': r.due,
                'duration': r.duration,
                'forecast_start': r.forecast_start,
                'forecast_due': r.forecast_due,
                'total_float': r.total_float,
                'critical': r.critical,
                'driving_link_id': r.driving_link,
                'why': r.why,
                'violations': r.violations,
            }
        )
    counts = {
        p.id: len([t for t in run.tasks if top(t).phase_id == p.id]) for p in phases
    }
    return {
        'project_id': str(project.id),
        'schedule_version': project.schedule_version or 0,
        'settings': run.settings,
        'project_start': run.schedule.project_start,
        'finish': run.schedule.finish,
        'forecast_finish': run.schedule.forecast_finish,
        'progress': engine.schedule_progress(run.items, results),
        'critical_path': run.schedule.critical_path,
        'cycle': run.schedule.cycle,
        'phases': [
            {
                **phase_to_out(p, counts[p.id]),
                **_phase_rollup(p, members[p.id], results, mapped),
            }
            for p in phases
        ],
        'items': out_items,
        'links': [link_to_out(row) for row in run.links],
    }


async def preview_settings(
    session: DBAsyncScopedSession, project: ews_models.Project, patch: dict[str, Any]
) -> dict[str, Any]:
    """What a settings change would do (Ppm-1050: switching to auto previews every date change and the finish)."""
    cfg = clean_settings(patch, settings_of(project))
    run = await compute(session, project, settings={**DEFAULTS, **cfg})
    return {
        'changes': planned_changes(run),
        'finish': run.schedule.finish,
        'forecast_finish': run.schedule.forecast_finish,
        'cycle': run.schedule.cycle,
    }


async def update_settings(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    project: ews_models.Project,
    patch: dict[str, Any],
    *,
    base_version: int | None,
) -> list[dict[str, Any]]:
    """Save the schedule settings, then recalculate (409 ``stale_schedule`` on an old ``base_version``)."""
    check_version(project, base_version)
    current = project.settings if isinstance(project.settings, dict) else {}
    before = settings_of(project)
    cfg = clean_settings(patch, before)
    project.settings = {**current, 'schedule': cfg}
    await session.flush()
    changes = events.diff(before, settings_of(project))
    if changes:
        await events.emit(
            session,
            scope,
            'ppm.project.updated',
            'project',
            project.id,
            project_id=project.id,
            changes={f'schedule.{k}': v for k, v in changes.items()},
            data={'name': project.name},
        )
    return await recalculate(session, scope, project, cause='settings')


def check_version(project: ews_models.Project, base_version: int | None) -> None:
    if base_version is not None and base_version != (project.schedule_version or 0):
        raise ConflictException(
            detail='the schedule changed meanwhile: reload it',
            extra={
                'code': 'stale_schedule',
                'schedule_version': project.schedule_version or 0,
            },
        )


# --- the subscriber: keep the schedule current ----------------------------------------------------


def _relevant(event: events.Event) -> bool:
    if event.topic == 'ppm.task.updated':
        return bool(set(event.changes or {}) & set(TRIGGERS))
    return event.topic in (
        'ppm.task.created',
        'ppm.task.deleted',
        'ppm.task.completed',
        'ppm.task.reopened',
        'ppm.task.moved',
        'ppm.item_link.created',
        'ppm.item_link.updated',
        'ppm.item_link.deleted',
    )


async def _item_rules(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    """Actual start on the first active / review / done stage; a new start on an auto item = SNET (§7)."""
    if event.topic != 'ppm.task.updated' or event.subject_type != 'task':
        return
    changes = event.changes or {}
    task = await session.get(Task, UUID(event.subject_id))
    if task is None:
        return
    if 'stage_type' in changes and task.started_at is None:
        info = catalog.stage_type_info(task.stage_type)
        if info is not None and info.band in STARTED_BANDS:
            task.started_at = items.now()
    if (
        'start_date' in changes
        and task.start_date
        and task.constraint_type in (None, 'asap', 'snet')
    ):
        project = (
            await session.get(ews_models.Project, task.project_id)
            if task.project_id
            else None
        )
        mode = task.schedule_mode or (
            settings_of(project)['mode'] if project else 'manual'
        )
        if mode == 'auto':
            task.constraint_type, task.constraint_date = 'snet', task.start_date


@events.subscribe
async def on_event(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    if event.topic == 'ppm.task.deleted' and event.project_id:
        ids = [
            UUID(event.subject_id),
            *(UUID(i) for i in event.data.get('subtree') or []),
        ]
        await _drop_links(session, scope, event.project_id, ids)
    if event.topic == 'ppm.task.moved' and event.data.get('from_project_id'):
        await _drop_links(
            session,
            scope,
            UUID(event.data['from_project_id']),
            [UUID(event.subject_id)],
        )
        moved = await session.get(Task, UUID(event.subject_id))
        if moved is not None:
            moved.phase_id = None  # phases belong to the old project
    if event.topic == 'ppm.task.completed':
        task = await session.get(Task, UUID(event.subject_id))
        if task is not None and task.behaviour == 'milestone':
            await events.emit(
                session,
                scope,
                'ppm.milestone.reached',
                'task',
                task.id,
                project_id=event.project_id,
                data={'code': task.code, 'name': task.name},
            )
    await _item_rules(session, scope, event)
    if _running.get() or not event.project_id or not _relevant(event):
        return
    project = await session.get(ews_models.Project, event.project_id)
    if project is None or not await has_auto_items(session, project):
        return
    with batch():
        await recalculate(session, scope, project, cause=event.topic)


__all__ = [
    'CONSTRAINTS',
    'MODES',
    'batch',
    'check_item_fields',
    'compute',
    'read',
    'recalculate',
]
