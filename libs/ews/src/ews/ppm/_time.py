"""Time tracking (taas-specs/ppm/time-expense/time-tracking-spec.md): effort of items (actual, remaining, roll-ups,
variance alerts), time entries with their rules (validation, locks, corrections), the timer, weekly timesheets
(lazy, grid cells, copy last week, submit) approved per project section through the generic approvals (subject
``timesheet``, ADR-40), project time lists. Settings ``time.*`` live in the organization's PPM settings
(``_time_settings``); entries are ``taas_timelogs`` rows (``user_id`` = e-mail or id of the person).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from db.models.ppm import PpmApproval, PpmSettings, PpmTimeCategory, PpmTimesheet
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import (
    ClientException,
    NotFoundException,
    PermissionDeniedException,
)
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ews.authz import EwsResources, grants_in
from ews.notifications import Kind, notify, register_job, register_kinds
from ews.security import RequestScope, is_allowed
from ews.shared import ConflictException, parse_uuid

from . import _access as access
from . import _approvals as approvals
from . import _effort as effort
from . import _events as events
from . import _time_settings as time_settings
from . import _work_items as items

Timelog = ews_models.Timelog
Task = ews_models.Task
TIME_ENTRY = EwsResources.TIME_ENTRY.value
TIMESHEET = EwsResources.TIMESHEET.value
SUBJECT = 'timesheet'
INTERNAL = 'internal'
"""Section key of entries without a project."""
EDITABLE = ('draft', 'rejected')
LOCKED_SHEET = ('submitted', 'partially_approved', 'approved')
SOURCES = ('manual', 'timer', 'timesheet', 'import', 'mobile')
SEED_CATEGORIES = (
    ('project', 'Project work', 'project', True),
    ('internal', 'Internal', 'internal', False),
    ('training', 'Training', 'internal', False),
    ('pre_sales', 'Pre-sales', 'internal', False),
)

register_kinds(
    Kind('ppm:effort_variance', 'ppm', email='digest'),
    Kind('ppm:timer_auto_stopped', 'ppm', email='instant'),
    Kind('ppm:timesheet_approval', 'ppm', email='instant', mandatory=True),
    Kind('ppm:timesheet_decided', 'ppm', email='instant'),
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def today() -> date:
    return datetime.now(UTC).date()


def latest_day() -> date:
    """The calendar date in the earliest time zone (UTC+14): a person's own *today* is never after it, so time logged
    for it is not refused as future (no per-person time zone yet)."""
    return (datetime.now(UTC) + timedelta(hours=14)).date()


def _error(detail: str, code: str, **extra: Any) -> ClientException:
    return ClientException(detail=detail, extra={'code': code, **extra})


def _conflict(detail: str, code: str, **extra: Any) -> ConflictException:
    return ConflictException(detail=detail, extra={'code': code, **extra})


# --- settings + categories ------------------------------------------------------------------------


async def settings_for(
    session: DBAsyncScopedSession, organization_id: UUID | None
) -> dict[str, Any]:
    raw = await session.scalar(
        select(PpmSettings.settings).where(
            PpmSettings.organization_id == organization_id
        )
    )
    return time_settings.of(raw if isinstance(raw, dict) else None)


async def categories(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[PpmTimeCategory]:
    """The organization's time categories (seeded on first use, race-safe)."""
    c = PpmTimeCategory
    rows = list(
        (
            await session.scalars(
                select(c)
                .where(c.organization_id == scope.organization_id)
                .order_by(c.position, c.name)
            )
        ).all()
    )
    if rows:
        return rows
    await session.execute(
        pg_insert(c).on_conflict_do_nothing(),
        [
            {
                'tenant_id': scope.tenant_id,
                'organization_id': scope.organization_id,
                'key': key,
                'name': name,
                'kind': kind,
                'billable_allowed': billable,
                'position': float(i),
            }
            for i, (key, name, kind, billable) in enumerate(SEED_CATEGORIES)
        ],
    )
    return list(
        (
            await session.scalars(
                select(c)
                .where(c.organization_id == scope.organization_id)
                .order_by(c.position, c.name)
            )
        ).all()
    )


async def category(
    session: DBAsyncScopedSession, scope: RequestScope, key: str | None
) -> PpmTimeCategory:
    wanted = key or 'project'
    for row in await categories(session, scope):
        if row.key == wanted and row.active:
            return row
    raise _error(f'unknown time category {wanted!r}', 'invalid_category')


# --- effort (Ppm-1202 … 1205) ---------------------------------------------------------------------


def own_effort(t: Task) -> effort.Effort:
    return effort.own(
        t.estimated_minutes,
        t.actual_minutes,
        remaining_typed=t.remaining_minutes,
        remaining_base=t.remaining_base_minutes,
        done=items.is_done(t),
    )


def rollup_effort(t: Task) -> effort.Effort:
    own_value = own_effort(t)
    if t.rollup_estimated_minutes is None:
        return own_value
    return effort.Effort(
        t.rollup_estimated_minutes or 0,
        t.rollup_actual_minutes or 0,
        t.rollup_remaining_minutes or 0,
        own_value.manual,
    )


def effort_out(t: Task) -> dict[str, Any]:
    """Own + roll-up E, A, R, F, V, V% of an item (wire)."""
    mine, total = own_effort(t), rollup_effort(t)
    return {
        'estimated_minutes': mine.estimate,
        'actual_minutes': mine.actual,
        'remaining_minutes': mine.remaining,
        'remaining_manual': mine.manual,
        'forecast_minutes': mine.forecast,
        'variance_minutes': mine.variance,
        'variance_pct': mine.variance_pct,
        'rollup_estimated_minutes': total.estimate,
        'rollup_actual_minutes': total.actual,
        'rollup_remaining_minutes': total.remaining,
        'rollup_forecast_minutes': total.forecast,
        'rollup_variance_pct': total.variance_pct,
        'variance_alert_level': t.variance_alert_level or 'none',
    }


async def _actual(session: DBAsyncScopedSession, task_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(Timelog.log_minutes), 0)).where(
                Timelog.task_id == task_id,
                Timelog.deleted_at.is_(None),
                or_(Timelog.status.is_(None), Timelog.status != 'rejected'),
                or_(Timelog.is_recording.is_(None), Timelog.is_recording.is_(False)),
            )
        )
        or 0
    )


async def refresh_effort(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    task: Task | None,
    *,
    actual: bool = True,
) -> None:
    """Own actual of ``task`` (``actual``), then the roll-ups and variance bands of it and its ancestors."""
    if task is None:
        return
    if actual:
        task.actual_minutes = await _actual(session, task.id)
    settings = None
    node: Task | None = task
    for _ in range(items.MAX_LEVELS + 5):
        if node is None:
            return
        children = list(
            (
                await session.scalars(
                    select(Task).where(
                        Task.parent_id == node.id, Task.deleted_at.is_(None)
                    )
                )
            ).all()
        )
        counted = [
            c for c in children if items.counts_in_progress(c.stage_type, c.behaviour)
        ]
        total = effort.rollup(own_effort(node), [rollup_effort(c) for c in counted])
        node.rollup_estimated_minutes = total.estimate
        node.rollup_actual_minutes = total.actual
        node.rollup_remaining_minutes = total.remaining
        if settings is None:
            project = (
                await session.get(ews_models.Project, node.project_id)
                if node.project_id
                else None
            )
            organization_id = project.organization_id if project else None
            settings = await settings_for(session, organization_id)
        previous = node.variance_alert_level
        level = effort.band(
            total.variance_pct,
            settings['variance_warning_pct'],
            settings['variance_critical_pct'],
            previous,
        )
        node.variance_alert_level = level
        await session.flush()
        if effort.crossed(previous, level) and node.project_id:
            await events.emit(
                session,
                scope,
                'ppm.task.effort_variance_crossed',
                'task',
                node.id,
                project_id=node.project_id,
                tenant_id=node.tenant_id,
                organization_id=organization_id,
                data={
                    'code': node.code,
                    'name': node.name,
                    'band': level,
                    'estimate': total.estimate,
                    'actual': total.actual,
                    'remaining': total.remaining,
                    'forecast': total.forecast,
                    'variance_pct': total.variance_pct,
                },
                cause='rule',
            )
        node = await session.get(Task, node.parent_id) if node.parent_id else None


async def set_remaining(
    session: DBAsyncScopedSession, scope: RequestScope, task: Task, minutes: int | None
) -> None:
    """Type the remaining (manual) or ``None`` = back to auto (Ppm-1203)."""
    if minutes is None:
        task.remaining_minutes = task.remaining_base_minutes = None
        task.remaining_set_at = task.remaining_set_by = None
    else:
        if minutes < 0:
            raise ClientException(detail='remaining_minutes must be 0 or more')
        task.remaining_minutes = int(minutes)
        task.remaining_base_minutes = task.actual_minutes or 0
        task.remaining_set_at = _now()
        task.remaining_set_by = access.author(scope)


# --- timesheets: lookup ---------------------------------------------------------------------------


async def sheet_for(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    user: str,
    day: date,
    settings: dict[str, Any],
) -> PpmTimesheet:
    """The person's timesheet of the week holding ``day`` (created on first need, race-safe)."""
    start, end = time_settings.week_of(day, settings['week_start'])
    s = PpmTimesheet
    await session.execute(
        pg_insert(s)
        .values(
            tenant_id=scope.tenant_id,
            organization_id=scope.organization_id,
            user_id=user,
            period_start=start,
            period_end=end,
            status='open',
        )
        .on_conflict_do_nothing()
    )
    sheet = await session.scalar(
        select(s).where(
            s.organization_id == scope.organization_id,
            s.user_id == user,
            s.period_start == start,
        )
    )
    assert sheet is not None
    return sheet


async def load_sheet(
    session: DBAsyncScopedSession, scope: RequestScope, sheet_id: object
) -> PpmTimesheet:
    sheet = await session.get(PpmTimesheet, parse_uuid(sheet_id, 'timesheet'))
    if sheet is None or sheet.organization_id != scope.organization_id:
        raise NotFoundException(detail='timesheet not found')
    return sheet


async def _sheet_entries(
    session: DBAsyncScopedSession, sheet: PpmTimesheet
) -> list[Timelog]:
    return list(
        (
            await session.scalars(
                select(Timelog)
                .where(
                    Timelog.deleted_at.is_(None),
                    Timelog.user_id == sheet.user_id,
                    Timelog.organization_id == sheet.organization_id,
                    Timelog.entry_date >= sheet.period_start,
                    Timelog.entry_date <= sheet.period_end,
                )
                .order_by(Timelog.entry_date, Timelog.id)
            )
        ).all()
    )


async def _refresh_totals(session: DBAsyncScopedSession, sheet: PpmTimesheet) -> None:
    rows = [e for e in await _sheet_entries(session, sheet) if not e.is_recording]
    sheet.total_minutes = sum(e.log_minutes or 0 for e in rows)
    sheet.billable_minutes = sum(e.log_minutes or 0 for e in rows if e.is_billable)
    await session.flush()


def section_of(entry: Timelog) -> str:
    return str(entry.project_id) if entry.project_id else INTERNAL


# --- entries --------------------------------------------------------------------------------------


@dataclass(slots=True)
class EntryIn:
    """A new entry: an item (``task_id``), a project, or an internal category; minutes or start / end."""

    task_id: Any = None
    project_id: Any = None
    category: str | None = None
    entry_date: date | None = None
    minutes: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    is_billable: bool | None = None
    description: str | None = None
    user: str | None = None
    source: str = 'manual'


@dataclass(slots=True)
class Target:
    task: Task | None
    project: ews_models.Project | None
    category: PpmTimeCategory


async def _require(
    scope: RequestScope, project: ews_models.Project | None, action: str
) -> None:
    domains = (
        access.project_domains(scope, project.id)
        if project is not None
        else scope.org_domains()
    )
    if not await is_allowed(scope, TIME_ENTRY, action, domains):
        raise PermissionDeniedException(
            detail=f'missing permission {TIME_ENTRY}:{action}'
        )


async def resolve_target(
    session: DBAsyncScopedSession, scope: RequestScope, data: EntryIn
) -> Target:
    task: Task | None = None
    project: ews_models.Project | None = None
    if data.task_id:
        task, project = await access.load_task(session, scope, data.task_id)
    elif data.project_id:
        project = await access.load_project(session, scope, data.project_id)
    cat = await category(
        session, scope, data.category or ('project' if project else 'internal')
    )
    if project is None and cat.kind == 'project':
        raise _error('project time needs an item or a project', 'invalid_category')
    if project is not None and cat.kind == 'internal':
        raise _error('internal time has no project', 'invalid_category')
    return Target(task, project, cat)


def _minutes(data: EntryIn) -> int:
    if data.minutes is not None:
        return int(data.minutes)
    if data.start_time and data.end_time:
        start = data.start_time.replace(tzinfo=None)
        end = data.end_time.replace(tzinfo=None)
        return int((end - start).total_seconds() // 60)
    return 0


async def _day_total(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    user: str,
    day: date,
    ignore: UUID | None = None,
) -> int:
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(Timelog.log_minutes), 0)).where(
                Timelog.deleted_at.is_(None),
                Timelog.organization_id == scope.organization_id,
                Timelog.user_id == user,
                Timelog.entry_date == day,
                Timelog.id != ignore if ignore else True,
            )
        )
        or 0
    )


async def _validate(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    settings: dict[str, Any],
    *,
    user: str,
    day: date,
    minutes: int,
    billable: bool,
    description: str | None,
    target: Target,
    ignore: UUID | None = None,
) -> None:
    """Ppm-1213: minutes > 0, daily maximum, no future dates, billable only where allowed, description rule."""
    if minutes <= 0:
        raise _error('minutes must be more than 0', 'invalid_minutes')
    if day > latest_day() and not settings['allow_future_days']:
        raise _error('time cannot be logged in the future', 'future_date')
    lock = time_settings.lock_date(settings)
    if lock is not None and day <= lock:
        raise _conflict(f'the period up to {lock.isoformat()} is locked', 'locked')
    if (
        await _day_total(session, scope, user, day, ignore) + minutes
        > settings['daily_max_minutes']
    ):
        raise _error(
            f'more than {settings["daily_max_minutes"]} minutes on {day.isoformat()}',
            'daily_max',
            max=settings['daily_max_minutes'],
        )
    if billable and not target.category.billable_allowed:
        raise _error('this time cannot be billable', 'not_billable')
    rule = settings['require_description']
    if not (description or '').strip() and (
        rule == 'always' or (rule == 'billable' and billable)
    ):
        raise _error('a description is required', 'description_required')


async def _check_editable_week(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    user: str,
    day: date,
    settings: dict[str, Any],
) -> PpmTimesheet:
    sheet = await sheet_for(session, scope, user, day, settings)
    if sheet.status in LOCKED_SHEET:
        raise _conflict(
            f'the timesheet of {sheet.period_start.isoformat()} is {sheet.status}',
            'locked',
        )
    return sheet


def editable(entry: Timelog, sheet_status: str | None = None) -> bool:
    return (
        (entry.status or 'draft') in EDITABLE
        and entry.locked_at is None
        and (sheet_status or 'open') not in LOCKED_SHEET
    )


async def create_entry(
    session: DBAsyncScopedSession, scope: RequestScope, data: EntryIn
) -> Timelog:
    target = await resolve_target(session, scope, data)
    me = access.author(scope)
    user = (data.user or '').strip() or me
    await _require(scope, target.project, 'manage' if user != me else 'create')
    settings = await settings_for(session, scope.organization_id)
    day = data.entry_date or today()
    minutes = _minutes(data)
    billable = (
        bool(data.is_billable)
        if data.is_billable is not None
        else target.category.billable_allowed
    )
    await _validate(
        session,
        scope,
        settings,
        user=user,
        day=day,
        minutes=minutes,
        billable=billable,
        description=data.description,
        target=target,
    )
    sheet = await _check_editable_week(session, scope, user, day, settings)
    entry = await _insert(
        session,
        scope,
        target,
        sheet,
        user=user,
        day=day,
        minutes=minutes,
        billable=billable,
        data=data,
    )
    await _after_change(
        session, scope, entry, target.task, sheet, 'ppm.time_entry.created'
    )
    return entry


async def _insert(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    target: Target,
    sheet: PpmTimesheet,
    *,
    user: str,
    day: date,
    minutes: int,
    billable: bool,
    data: EntryIn,
    **extra: Any,
) -> Timelog:
    entry = Timelog(
        tenant_id=scope.tenant_id,
        organization_id=scope.organization_id,
        task_id=target.task.id if target.task else None,
        project_id=target.project.id if target.project else None,
        user_id=user,
        email=user if '@' in user else None,
        entry_date=day,
        log_date=datetime.combine(day, datetime.min.time()),
        start_time=data.start_time.replace(tzinfo=None) if data.start_time else None,
        end_time=data.end_time.replace(tzinfo=None) if data.end_time else None,
        log_minutes=minutes,
        is_billable=billable,
        description=(data.description or '').strip() or None,
        time_category_id=target.category.id,
        source=data.source if data.source in SOURCES else 'manual',
        status='draft',
        timelog_type='regular',
        timesheet_id=sheet.id,
        created_by=access.author(scope),
        **extra,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _after_change(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    entry: Timelog,
    task: Task | None,
    sheet: PpmTimesheet | None,
    topic: str,
    data: dict[str, Any] | None = None,
) -> None:
    if task is None and entry.task_id:
        task = await session.get(Task, entry.task_id)
    await refresh_effort(session, scope, task)
    if sheet is None and entry.timesheet_id:
        sheet = await session.get(PpmTimesheet, entry.timesheet_id)
    if sheet is not None:
        await _refresh_totals(session, sheet)
    await events.emit(
        session,
        scope,
        topic,
        'task' if entry.task_id else 'time_entry',
        entry.task_id or entry.id,
        project_id=entry.project_id,
        tenant_id=entry.tenant_id,
        organization_id=entry.organization_id,
        data={
            'time_entry_id': str(entry.id),
            'user': entry.user_id,
            'date': entry.entry_date,
            'minutes': entry.log_minutes,
            'billable': bool(entry.is_billable),
            'status': entry.status,
            'code': task.code if task else None,
            **(data or {}),
        },
    )
    if entry.project_id:
        await items.touch_project(session, entry.project_id)


async def load_entry(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    entry_id: object,
    action: str = 'read',
) -> Timelog:
    entry = await session.get(Timelog, parse_uuid(entry_id, 'time entry'))
    if (
        entry is None
        or entry.deleted_at is not None
        or entry.organization_id != scope.organization_id
    ):
        raise NotFoundException(detail='time entry not found')
    project = (
        await access.load_project(session, scope, entry.project_id)
        if entry.project_id
        else None
    )
    own = entry.user_id == access.author(scope)
    if not own:
        await _require(scope, project, 'manage' if action != 'read' else 'read')
    elif action != 'read':
        await _require(scope, project, action)
    return entry


async def update_entry(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    entry: Timelog,
    patch: dict[str, Any],
) -> Timelog:
    sheet = (
        await session.get(PpmTimesheet, entry.timesheet_id)
        if entry.timesheet_id
        else None
    )
    if not editable(entry, sheet.status if sheet else None) or entry.is_recording:
        raise _conflict('this entry is locked: correct it instead', 'locked')
    settings = await settings_for(session, scope.organization_id)
    before = {
        'date': entry.entry_date,
        'minutes': entry.log_minutes,
        'billable': entry.is_billable,
        'description': entry.description,
    }
    day = patch.get('entry_date') or entry.entry_date or today()
    if isinstance(day, str):
        day = date.fromisoformat(day[:10])
    minutes = (
        int(patch['minutes'])
        if patch.get('minutes') is not None
        else int(entry.log_minutes or 0)
    )
    billable = (
        bool(patch['is_billable'])
        if patch.get('is_billable') is not None
        else bool(entry.is_billable)
    )
    description = patch['description'] if 'description' in patch else entry.description
    cat = (
        await session.get(PpmTimeCategory, entry.time_category_id)
        if entry.time_category_id
        else None
    )
    target = Target(
        None,
        None,
        cat
        or await category(
            session, scope, 'project' if entry.project_id else 'internal'
        ),
    )
    await _validate(
        session,
        scope,
        settings,
        user=entry.user_id or '',
        day=day,
        minutes=minutes,
        billable=billable,
        description=description,
        target=target,
        ignore=entry.id,
    )
    new_sheet = await _check_editable_week(
        session, scope, entry.user_id or '', day, settings
    )
    entry.entry_date = day
    entry.log_date = datetime.combine(day, datetime.min.time())
    entry.log_minutes = minutes
    entry.is_billable = billable
    entry.description = (description or '').strip() or None
    entry.timesheet_id = new_sheet.id
    if entry.status == 'rejected':
        entry.status = 'draft'
    await session.flush()
    if sheet is not None and sheet.id != new_sheet.id:
        await _refresh_totals(session, sheet)
    after = {
        'date': day,
        'minutes': minutes,
        'billable': billable,
        'description': entry.description,
    }
    await _after_change(
        session,
        scope,
        entry,
        None,
        new_sheet,
        'ppm.time_entry.updated',
        {'changes': events.diff(before, after)},
    )
    return entry


async def delete_entry(
    session: DBAsyncScopedSession, scope: RequestScope, entry: Timelog
) -> None:
    """Soft delete of an editable entry (Ppm-1214)."""
    sheet = (
        await session.get(PpmTimesheet, entry.timesheet_id)
        if entry.timesheet_id
        else None
    )
    if not editable(entry, sheet.status if sheet else None):
        raise _conflict('this entry is locked: correct it instead', 'locked')
    entry.deleted_at = datetime.now(UTC)
    entry.is_recording = False
    await session.flush()
    await _after_change(session, scope, entry, None, sheet, 'ppm.time_entry.deleted')


async def correct_entry(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    entry: Timelog,
    *,
    minutes: int,
    reason: str,
    description: str | None = None,
) -> list[Timelog]:
    """Ppm-1243 / §5.7: an approved or locked entry is reversed (−minutes, ``adjustment``) and, with ``minutes`` > 0,
    replaced by a corrected entry — both dated today, in the current week."""
    if len((reason or '').strip()) < 10:
        raise _error('give a reason (10 characters or more)', 'reason_required')
    settings = await settings_for(session, scope.organization_id)
    lock = time_settings.lock_date(settings)
    in_lock = (
        lock is not None and entry.entry_date is not None and entry.entry_date <= lock
    )
    if editable(entry) and not in_lock:
        raise _error('this entry is still editable: change it directly', 'not_locked')
    user = entry.user_id or access.author(scope)
    sheet = await _check_editable_week(session, scope, user, today(), settings)
    task = await session.get(Task, entry.task_id) if entry.task_id else None
    project = (
        await session.get(ews_models.Project, entry.project_id)
        if entry.project_id
        else None
    )
    cat = (
        await session.get(PpmTimeCategory, entry.time_category_id)
        if entry.time_category_id
        else None
    )
    target = Target(
        task,
        project,
        cat or await category(session, scope, 'project' if project else 'internal'),
    )
    base = EntryIn(description=description or entry.description, source='manual')
    reversal = await _insert(
        session,
        scope,
        target,
        sheet,
        user=user,
        day=today(),
        minutes=-int(entry.log_minutes or 0),
        billable=bool(entry.is_billable),
        data=base,
        reverses_id=entry.id,
        correction_reason=reason.strip(),
    )
    reversal.timelog_type = 'adjustment'
    out = [reversal]
    if minutes > 0:
        corrected = await _insert(
            session,
            scope,
            target,
            sheet,
            user=user,
            day=today(),
            minutes=int(minutes),
            billable=bool(entry.is_billable),
            data=base,
            correction_reason=reason.strip(),
        )
        out.append(corrected)
    await session.flush()
    await _after_change(
        session,
        scope,
        reversal,
        task,
        sheet,
        'ppm.time_entry.corrected',
        {
            'original_id': str(entry.id),
            'new_id': str(out[-1].id) if len(out) > 1 else None,
            'reason': reason.strip(),
        },
    )
    return out


# --- timer (Ppm-1211, 1212) -----------------------------------------------------------------------


async def current_timer(
    session: DBAsyncScopedSession, scope: RequestScope
) -> Timelog | None:
    return await session.scalar(
        select(Timelog).where(
            Timelog.organization_id == scope.organization_id,
            Timelog.user_id == access.author(scope),
            Timelog.is_recording.is_(True),
            Timelog.deleted_at.is_(None),
        )
    )


async def start_timer(
    session: DBAsyncScopedSession, scope: RequestScope, data: EntryIn
) -> Timelog:
    """Start a timer (another running one stops first)."""
    running = await current_timer(session, scope)
    if running is not None:
        await stop_timer(session, scope, running)
    target = await resolve_target(session, scope, data)
    await _require(scope, target.project, 'create')
    settings = await settings_for(session, scope.organization_id)
    day = data.entry_date or today()
    sheet = await _check_editable_week(
        session, scope, access.author(scope), day, settings
    )
    started = _now()
    entry = await _insert(
        session,
        scope,
        target,
        sheet,
        user=access.author(scope),
        day=day,
        minutes=0,
        billable=bool(data.is_billable)
        if data.is_billable is not None
        else target.category.billable_allowed,
        data=EntryIn(description=data.description, source='timer'),
        is_recording=True,
    )
    entry.start_time = started
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.timer.started',
        'task' if entry.task_id else 'time_entry',
        entry.task_id or entry.id,
        project_id=entry.project_id,
        data={
            'time_entry_id': str(entry.id),
            'user': entry.user_id,
            'code': target.task.code if target.task else None,
        },
    )
    return entry


async def stop_timer(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    entry: Timelog,
    *,
    at: datetime | None = None,
    auto: bool = False,
) -> Timelog:
    """Stop: minutes from start to now (or ``at``) with the organization rounding; ``auto`` flags it for review."""
    settings = await settings_for(session, entry.organization_id)
    end = at or _now()
    start = entry.start_time or end
    entry.end_time = end
    entry.log_minutes = effort.round_minutes(
        (end - start).total_seconds(), settings['rounding']
    )
    entry.is_recording = False
    entry.needs_review = auto or None
    await session.flush()
    await _after_change(
        session,
        scope,
        entry,
        None,
        None,
        'ppm.timer.auto_stopped' if auto else 'ppm.timer.stopped',
    )
    return entry


async def auto_stop_timers(
    session: DBAsyncScopedSession, now: datetime | None = None
) -> int:
    """Job: timers running longer than ``timer_auto_stop_hours`` stop at that limit and the person is told."""
    moment = now or _now()
    rows = (
        await session.scalars(
            select(Timelog).where(
                Timelog.is_recording.is_(True),
                Timelog.deleted_at.is_(None),
                Timelog.start_time < moment - timedelta(hours=1),
            )
        )
    ).all()
    stopped = 0
    for entry in rows:
        settings = await settings_for(session, entry.organization_id)
        limit = timedelta(hours=settings['timer_auto_stop_hours'])
        if entry.start_time is None or moment - entry.start_time < limit:
            continue
        await stop_timer(session, None, entry, at=entry.start_time + limit, auto=True)
        stopped += 1
        if entry.tenant_id and entry.user_id:
            await notify(
                session,
                tenant_id=entry.tenant_id,
                organization_id=entry.organization_id,
                kind='ppm:timer_auto_stopped',
                recipients=[entry.user_id],
                title=f'Your timer stopped after {settings["timer_auto_stop_hours"]} hours: check the entry',
                body=entry.description or '',
                link='/ppm/time',
                subject_type='time_entry',
                subject_id=str(entry.id),
                project_id=entry.project_id,
                via='automation',
                occurrence=f'auto_stop:{entry.id}',
                data={'minutes': entry.log_minutes},
            )
    return stopped


register_job('ppm.timer_auto_stop', 900, auto_stop_timers)


# --- timesheet view + cells -----------------------------------------------------------------------


def _row_key(
    e: Timelog, cats: dict[UUID, PpmTimeCategory]
) -> tuple[str, str, str, bool]:
    cat = cats.get(e.time_category_id) if e.time_category_id else None
    return (
        str(e.project_id or ''),
        str(e.task_id or ''),
        cat.key if cat else ('project' if e.project_id else 'internal'),
        bool(e.is_billable),
    )


async def _sections(
    session: DBAsyncScopedSession, sheet: PpmTimesheet
) -> dict[str, PpmApproval]:
    """Latest approval of each section (``subject_part``)."""
    out: dict[str, PpmApproval] = {}
    for a in await approvals.for_subject(session, SUBJECT, str(sheet.id)):
        out.setdefault(a.subject_part or INTERNAL, a)
    return out


async def week_view(
    session: DBAsyncScopedSession, scope: RequestScope, sheet: PpmTimesheet
) -> dict[str, Any]:
    settings = await settings_for(session, scope.organization_id)
    entries = await _sheet_entries(session, sheet)
    cats = {c.id: c for c in await categories(session, scope)}
    task_ids = {e.task_id for e in entries if e.task_id}
    project_ids = {e.project_id for e in entries if e.project_id}
    tasks = (
        {
            t.id: t
            for t in (
                await session.scalars(select(Task).where(Task.id.in_(task_ids)))
            ).all()
        }
        if task_ids
        else {}
    )
    projects = (
        {
            p.id: p
            for p in (
                await session.scalars(
                    select(ews_models.Project).where(
                        ews_models.Project.id.in_(project_ids)
                    )
                )
            ).all()
        }
        if project_ids
        else {}
    )
    days = [sheet.period_start + timedelta(days=i) for i in range(7)]
    rows: dict[tuple[str, str, str, bool], dict[str, Any]] = {}
    for e in entries:
        key = _row_key(e, cats)
        row = rows.get(key)
        if row is None:
            task = tasks.get(e.task_id) if e.task_id else None
            project = projects.get(e.project_id) if e.project_id else None
            row = rows[key] = {
                'project_id': key[0] or None,
                'task_id': key[1] or None,
                'category': key[2],
                'is_billable': key[3],
                'project_name': project.name if project else None,
                'task_code': task.code if task else None,
                'task_name': task.name if task else None,
                'cells': {d.isoformat(): {'minutes': 0, 'entry_ids': []} for d in days},
                'total_minutes': 0,
            }
        if e.entry_date is None or e.is_recording:
            continue
        cell = row['cells'].get(e.entry_date.isoformat())
        if cell is not None:
            cell['minutes'] += e.log_minutes or 0
            cell['entry_ids'].append(str(e.id))
            row['total_minutes'] += e.log_minutes or 0
    sections = await _sections(session, sheet)
    return {
        'id': str(sheet.id),
        'user_id': sheet.user_id,
        'period_start': sheet.period_start,
        'period_end': sheet.period_end,
        'status': sheet.status,
        'total_minutes': sheet.total_minutes,
        'billable_minutes': sheet.billable_minutes,
        'expected_minutes': settings['weekly_expected_minutes'],
        'days': days,
        'day_totals': [
            sum(
                e.log_minutes or 0
                for e in entries
                if e.entry_date == d and not e.is_recording
            )
            for d in days
        ],
        'rows': list(rows.values()),
        'sections': [
            {
                'key': part,
                'project_name': projects[UUID(part)].name
                if part != INTERNAL and UUID(part) in projects
                else None,
                'status': a.status,
                'approval_id': str(a.id),
            }
            for part, a in sections.items()
        ],
        'running_timer': any(e.is_recording for e in entries),
        'editable': sheet.status not in LOCKED_SHEET,
    }


@dataclass(slots=True)
class CellIn:
    entry_date: date
    minutes: int
    task_id: Any = None
    project_id: Any = None
    category: str | None = None
    is_billable: bool | None = None


async def write_cells(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    sheet: PpmTimesheet,
    cells: list[CellIn],
) -> None:
    """Ppm-1231: an empty cell creates an entry (``source = timesheet``), one entry is updated (0 deletes it), several
    are refused (400 ``several_entries`` — the day detail edits them)."""
    if sheet.user_id != access.author(scope):
        raise PermissionDeniedException(detail='only the person edits their timesheet')
    if sheet.status in LOCKED_SHEET:
        raise _conflict(f'the timesheet is {sheet.status}', 'locked')
    cats = {c.id: c for c in await categories(session, scope)}
    entries = [e for e in await _sheet_entries(session, sheet) if not e.is_recording]
    for cell in cells:
        if not sheet.period_start <= cell.entry_date <= sheet.period_end:
            raise _error('the cell is outside the week', 'invalid_cell')
        data = EntryIn(
            task_id=cell.task_id,
            project_id=cell.project_id,
            category=cell.category,
            entry_date=cell.entry_date,
            minutes=cell.minutes,
            is_billable=cell.is_billable,
            source='timesheet',
        )
        target = await resolve_target(session, scope, data)
        billable = (
            bool(cell.is_billable)
            if cell.is_billable is not None
            else target.category.billable_allowed
        )
        key = (
            str(target.project.id if target.project else ''),
            str(target.task.id if target.task else ''),
            target.category.key,
            billable,
        )
        same = [
            e
            for e in entries
            if e.entry_date == cell.entry_date and _row_key(e, cats) == key
        ]
        if len(same) > 1:
            raise _error(
                'this cell has several entries: edit them in the day detail',
                'several_entries',
            )
        if same:
            if cell.minutes <= 0:
                await delete_entry(session, scope, same[0])
            else:
                await update_entry(session, scope, same[0], {'minutes': cell.minutes})
        elif cell.minutes > 0:
            data.is_billable = billable
            entries.append(await create_entry(session, scope, data))


async def copy_previous(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    sheet: PpmTimesheet,
    *,
    with_hours: bool,
) -> dict[str, Any]:
    """Ppm-1232: the rows of last week (with their hours if asked); items closed since are skipped and listed."""
    settings = await settings_for(session, scope.organization_id)
    previous = await sheet_for(
        session, scope, sheet.user_id, sheet.period_start - timedelta(days=1), settings
    )
    cats = {c.id: c for c in await categories(session, scope)}
    rows: dict[tuple[str, str, str, bool], list[Timelog]] = defaultdict(list)
    for e in await _sheet_entries(session, previous):
        if (e.log_minutes or 0) > 0 and not e.is_recording:
            rows[_row_key(e, cats)].append(e)
    kept, skipped = [], []
    for key, group in rows.items():
        task = await session.get(Task, UUID(key[1])) if key[1] else None
        if task is not None and (task.deleted_at is not None or items.is_done(task)):
            skipped.append(
                {'task_id': key[1], 'task_code': task.code, 'task_name': task.name}
            )
            continue
        kept.append(
            {
                'project_id': key[0] or None,
                'task_id': key[1] or None,
                'category': key[2],
                'is_billable': key[3],
            }
        )
        if with_hours:
            cells = [
                CellIn(
                    entry_date=e.entry_date + timedelta(days=7),
                    minutes=e.log_minutes or 0,
                    task_id=key[1] or None,
                    project_id=key[0] or None,
                    category=key[2],
                    is_billable=key[3],
                )
                for e in group
                if e.entry_date is not None
            ]
            await write_cells(session, scope, sheet, cells)
    return {'rows': kept, 'skipped': skipped}


# --- submit + approval (Ppm-1233, 1240 … 1243) ----------------------------------------------------


async def _org_admins(scope: RequestScope, exclude: set[str]) -> list[str]:
    return [
        u
        for u, role, _ in await grants_in([f'org:{scope.organization_id}'])
        if role == 'org_admin' and u.lower() not in exclude
    ]


async def _section_approvers(
    session: DBAsyncScopedSession, scope: RequestScope, part: str, mode: str
) -> list[str]:
    """§5.6: project admins of the section (``project_manager`` / ``both``), else the organization admins — never the
    submitter (Ppm-1241)."""
    exclude = approvals.me_refs(scope)
    refs: list[str] = []
    if part != INTERNAL and mode in ('project_manager', 'both'):
        project = await session.get(ews_models.Project, UUID(part))
        if project is not None:
            from ._members import members  # late: members → access

            refs = [
                (m.email or m.user_id).lower()
                for m in await members(session, scope, project)
                if m.role == 'project_admin'
                and (m.email or m.user_id).lower() not in exclude
                and str(m.user_id).lower() not in exclude
            ]
    return refs or await _org_admins(scope, exclude)


async def submit(
    session: DBAsyncScopedSession, scope: RequestScope, sheet: PpmTimesheet
) -> PpmTimesheet:
    if sheet.user_id != access.author(scope):
        raise PermissionDeniedException(
            detail='only the person submits their timesheet'
        )
    if sheet.status in LOCKED_SHEET:
        raise _conflict(f'the timesheet is already {sheet.status}', 'locked')
    settings = await settings_for(session, scope.organization_id)
    entries = await _sheet_entries(session, sheet)
    if any(e.is_recording for e in entries):
        raise _conflict('stop the running timer first', 'timer_running')
    open_entries = [
        e
        for e in entries
        if (e.status or 'draft') in EDITABLE and (e.log_minutes or 0) != 0
    ]
    rule = settings['require_description']
    missing = [
        str(e.id)
        for e in open_entries
        if not (e.description or '').strip()
        and (rule == 'always' or (rule == 'billable' and e.is_billable))
    ]
    if missing:
        raise _error(
            'some entries need a description', 'description_required', entry_ids=missing
        )
    total = sum(e.log_minutes or 0 for e in entries)
    if (
        settings['submit_rule'] == 'block'
        and total < settings['weekly_expected_minutes']
    ):
        raise _conflict(
            'the week is under the expected hours',
            'under_expected',
            expected=settings['weekly_expected_minutes'],
        )
    sheet.status = 'submitted'
    sheet.submitted_at = datetime.now(UTC)
    sheet.reopen_reason = None
    for e in open_entries:
        e.status = 'submitted'
    await _refresh_totals(session, sheet)
    week = f'{sheet.period_start.isoformat()} – {sheet.period_end.isoformat()}'
    await events.emit(
        session,
        scope,
        'ppm.timesheet.submitted',
        'timesheet',
        sheet.id,
        data={
            'user': sheet.user_id,
            'week': week,
            'total': sheet.total_minutes,
            'billable': sheet.billable_minutes,
        },
    )
    parts = sorted({section_of(e) for e in open_entries})
    for part in parts:
        if settings['approval_mode'] == 'auto':
            await _decide_section(session, None, sheet, part, 'approved', None)
            continue
        refs = await _section_approvers(session, scope, part, settings['approval_mode'])
        if not refs:
            raise _error(
                'nobody can approve this timesheet', 'no_approver', section=part
            )
        await approvals.request(
            session,
            scope,
            subject_key=SUBJECT,
            subject_id=str(sheet.id),
            subject_part=part,
            steps=[
                approvals.StepIn(
                    rule='any', approvers=[{'type': 'user', 'ref': r} for r in refs]
                )
            ],
        )
    await _recompute_status(session, sheet)
    return sheet


async def _decide_section(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    sheet: PpmTimesheet,
    part: str,
    decision: str,
    note: str | None,
    decider: str | None = None,
) -> None:
    """Entries of a section follow its decision: approved → locked; rejected / changes requested → editable."""
    for e in await _sheet_entries(session, sheet):
        if section_of(e) != part or (e.status or 'draft') != 'submitted':
            continue
        if decision == 'approved':
            e.status = 'approved'
            e.locked_at = _now()
        else:
            e.status = 'rejected'
        e.approved_user_id = decider
        e.approved_time = _now()
        e.approved_notes = note
    await session.flush()
    touched = {
        e.task_id
        for e in await _sheet_entries(session, sheet)
        if section_of(e) == part and e.task_id
    }
    for task_id in touched:
        await refresh_effort(session, scope, await session.get(Task, task_id))


async def _recompute_status(session: DBAsyncScopedSession, sheet: PpmTimesheet) -> None:
    """§5.5 from the entries: any rejected → rejected; all approved → approved; some → partially approved."""
    statuses = [
        e.status or 'draft'
        for e in await _sheet_entries(session, sheet)
        if (e.log_minutes or 0) != 0
    ]
    if not statuses or (
        sheet.status in ('open', 'reopened') and 'submitted' not in statuses
    ):
        return
    if 'rejected' in statuses:
        sheet.status = 'rejected'
    elif all(s == 'approved' for s in statuses):
        sheet.status = 'approved'
        sheet.approved_at = datetime.now(UTC)
    elif 'approved' in statuses:
        sheet.status = 'partially_approved'
    else:
        sheet.status = 'submitted'
    await session.flush()


async def reopen(
    session: DBAsyncScopedSession, scope: RequestScope, sheet: PpmTimesheet, reason: str
) -> PpmTimesheet:
    """§5.7: an approver (or an organization admin) reopens an approved timesheet; its entries become editable."""
    if len((reason or '').strip()) < 10:
        raise _error('give a reason (10 characters or more)', 'reason_required')
    if sheet.status not in ('approved', 'partially_approved', 'submitted'):
        raise _conflict(f'the timesheet is {sheet.status}', 'not_submitted')
    entries = await _sheet_entries(session, sheet)
    parts = {section_of(e) for e in entries}
    allowed = await is_allowed(scope, TIMESHEET, 'approve', scope.org_domains())
    for part in parts:
        if allowed:
            break
        if part != INTERNAL:
            allowed = await is_allowed(
                scope, TIMESHEET, 'approve', access.project_domains(scope, part)
            )
    if not allowed:
        raise PermissionDeniedException(
            detail=f'missing permission {TIMESHEET}:approve'
        )
    for a in (await _sections(session, sheet)).values():
        if a.status == 'pending':
            try:
                await approvals.cancel(session, scope, a, reason.strip())
            except PermissionDeniedException:
                a.status = 'cancelled'  # an approver reopening: the pending sections close with the week
    for e in entries:
        if (e.status or 'draft') in ('submitted', 'approved'):
            e.status = 'draft'
            e.locked_at = None
    sheet.status = 'reopened'
    sheet.reopen_reason = reason.strip()
    await session.flush()
    await events.emit(
        session,
        scope,
        'ppm.timesheet.reopened',
        'timesheet',
        sheet.id,
        data={'user': sheet.user_id, 'reason': sheet.reopen_reason},
    )
    return sheet


async def _subject(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    subject_id: str,
    action: str,
) -> approvals.Subject:
    sheet = await session.get(PpmTimesheet, parse_uuid(subject_id, 'timesheet'))
    if sheet is None or (
        scope is not None and sheet.organization_id != scope.organization_id
    ):
        raise NotFoundException(detail='timesheet not found')
    if (
        scope is not None
        and action == 'request'
        and sheet.user_id != access.author(scope)
    ):
        raise PermissionDeniedException(
            detail='only the person submits their timesheet'
        )
    return approvals.Subject(
        title=f'Timesheet {sheet.user_id} · {sheet.period_start.isoformat()}',
        project=None,
        snapshot={
            'user': sheet.user_id,
            'week': sheet.period_start.isoformat(),
            'total': sheet.total_minutes,
            'billable': sheet.billable_minutes,
        },
        record=sheet,
        owner=sheet.user_id,
    )


async def _on_outcome(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    approval: PpmApproval,
    subject: approvals.Subject,
) -> None:
    sheet: PpmTimesheet = subject.record
    if approval.status not in ('approved', 'rejected', 'changes_requested'):
        return
    await _decide_section(
        session,
        scope,
        sheet,
        approval.subject_part or INTERNAL,
        'approved' if approval.status == 'approved' else 'rejected',
        None,
        access.author(scope) if scope else 'system',
    )
    await _recompute_status(session, sheet)
    await events.emit(
        session,
        scope,
        'ppm.timesheet.approved'
        if approval.status == 'approved'
        else 'ppm.timesheet.rejected',
        'timesheet',
        sheet.id,
        tenant_id=sheet.tenant_id,
        organization_id=sheet.organization_id,
        data={
            'user': sheet.user_id,
            'section': approval.subject_part,
            'status': sheet.status,
        },
    )


approvals.register_subject(
    approvals.SubjectType(SUBJECT, _subject, _on_outcome, allow_self_approval=False)
)


async def decide(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    sheet: PpmTimesheet,
    *,
    decision: str,
    note: str | None,
    section: str | None = None,
) -> PpmTimesheet:
    """Approve / reject the sections the caller can decide (one ``section`` or every pending one)."""
    pending = [
        a
        for part, a in (await _sections(session, sheet)).items()
        if a.status == 'pending' and (section is None or part == section)
    ]
    if not pending:
        raise _conflict('nothing waits for a decision', 'approval_closed')
    decided = 0
    mine = approvals.me_refs(scope)
    for a in pending:
        waiting = {
            r.user_ref
            for r in await approvals.approvers_of(session, a.id)
            if r.step == a.current_step and r.decision == 'pending'
        }
        if not waiting & mine:
            continue
        await approvals.decide(session, scope, a, decision, note)
        decided += 1
    if not decided:
        raise PermissionDeniedException(
            detail='you are not an approver of this timesheet',
            extra={'code': 'not_approver'},
        )
    return sheet


async def approval_queue(
    session: DBAsyncScopedSession, scope: RequestScope
) -> list[dict[str, Any]]:
    """Timesheets waiting for the caller (Approvals tab)."""
    out: dict[str, dict[str, Any]] = {}
    for approval, _ in await approvals.waiting_for(session, scope):
        if approval.subject_type != SUBJECT:
            continue
        sheet = await session.get(PpmTimesheet, UUID(approval.subject_id))
        if sheet is None:
            continue
        item = out.setdefault(
            str(sheet.id),
            {
                'id': str(sheet.id),
                'user_id': sheet.user_id,
                'period_start': sheet.period_start,
                'period_end': sheet.period_end,
                'status': sheet.status,
                'total_minutes': sheet.total_minutes,
                'billable_minutes': sheet.billable_minutes,
                'sections': [],
            },
        )
        item['sections'].append(approval.subject_part or INTERNAL)
    return list(out.values())


# --- project time (Ppm-1250) ----------------------------------------------------------------------


async def project_entries(
    session: DBAsyncScopedSession,
    project: ews_models.Project,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    billable: bool | None = None,
    user: str | None = None,
) -> list[tuple[Timelog, Task | None]]:
    q = (
        select(Timelog, Task)
        .outerjoin(Task, Task.id == Timelog.task_id)
        .where(
            Timelog.project_id == project.id,
            Timelog.deleted_at.is_(None),
            or_(Timelog.is_recording.is_(None), Timelog.is_recording.is_(False)),
        )
        .order_by(Timelog.entry_date.desc().nulls_last(), Timelog.id.desc())
    )
    if date_from:
        q = q.where(Timelog.entry_date >= date_from)
    if date_to:
        q = q.where(Timelog.entry_date <= date_to)
    if status:
        q = q.where(Timelog.status == status)
    if billable is not None:
        q = q.where(Timelog.is_billable.is_(billable))
    if user:
        q = q.where(Timelog.user_id == user)
    return [(e, t) for e, t in (await session.execute(q.limit(5000))).all()]


def totals(rows: list[tuple[Timelog, Task | None]]) -> dict[str, Any]:
    by_person: dict[str, int] = defaultdict(int)
    by_item: dict[str, int] = defaultdict(int)
    for e, t in rows:
        by_person[e.user_id or ''] += e.log_minutes or 0
        by_item[t.code if t else ''] += e.log_minutes or 0
    return {
        'minutes': sum(e.log_minutes or 0 for e, _ in rows),
        'billable_minutes': sum(e.log_minutes or 0 for e, _ in rows if e.is_billable),
        'by_person': [
            {'key': k, 'minutes': v}
            for k, v in sorted(by_person.items(), key=lambda x: -x[1])
        ],
        'by_item': [
            {'key': k, 'minutes': v}
            for k, v in sorted(by_item.items(), key=lambda x: -x[1])
        ],
    }


def _cell(value: object) -> str:
    text = '' if value is None else str(value)
    return (
        f"'{text}"
        if text[:1] in ('=', '+', '-', '@') and not text.lstrip('-').isdigit()
        else text
    )


def entries_csv(rows: list[tuple[Timelog, Task | None]]) -> str:
    """CSV of a project's time (formula-safe, Ppm-0014)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            'date',
            'person',
            'item',
            'item name',
            'minutes',
            'hours',
            'billable',
            'status',
            'description',
        ]
    )
    for e, t in rows:
        writer.writerow(
            [
                _cell(e.entry_date.isoformat() if e.entry_date else ''),
                _cell(e.user_id),
                _cell(t.code if t else ''),
                _cell(t.name if t else ''),
                e.log_minutes or 0,
                f'{(e.log_minutes or 0) / 60:.2f}',
                'yes' if e.is_billable else 'no',
                _cell(e.status or 'draft'),
                _cell(e.description),
            ]
        )
    return out.getvalue()


# --- subscribers: effort follows item changes, alerts, timesheet notifications ---------------------

EFFORT_FIELDS = (
    'estimated_minutes',
    'completed_at',
    'stage_type',
    'parent_id',
    'remaining_minutes',
    'behaviour',
)


@events.subscribe
async def on_event(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    if event.topic == 'ppm.task.updated' and set(event.changes or {}) & set(
        EFFORT_FIELDS
    ):
        task = await session.get(Task, UUID(event.subject_id))
        await refresh_effort(session, scope, task, actual=False)
        old_parent = ((event.changes or {}).get('parent_id') or {}).get('from')
        if old_parent:
            await refresh_effort(
                session,
                scope,
                await session.get(Task, UUID(str(old_parent))),
                actual=False,
            )
    elif event.topic in ('ppm.task.created', 'ppm.task.deleted'):
        task = await session.get(Task, UUID(event.subject_id))
        if task is not None and task.parent_id:
            await refresh_effort(
                session, scope, await session.get(Task, task.parent_id), actual=False
            )
    elif event.topic == 'ppm.task.effort_variance_crossed' and event.project_id:
        await _variance_alert(session, scope, event)
    elif (
        event.subject_type == 'approval'
        and (event.data or {}).get('subject_type') == SUBJECT
    ):
        await _approval_notice(session, scope, event)


async def _variance_alert(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    """§5.8: warning → assignee + project managers; critical → project managers."""
    task = await session.get(Task, UUID(event.subject_id))
    project = await session.get(ews_models.Project, event.project_id)
    if task is None or project is None:
        return
    data = event.data or {}
    admins = [
        u
        for u, r, _ in await grants_in([access.project_domain(project.id)])
        if r == 'project_admin'
    ]
    recipients = admins + (
        [task.user_id] if data.get('band') == 'warning' and task.user_id else []
    )
    if project.user_id:
        recipients.append(project.user_id)
    label = f'{task.code} {task.name}'.strip()
    await notify(
        session,
        tenant_id=event.tenant_id,
        organization_id=event.organization_id,
        kind='ppm:effort_variance',
        recipients=list(dict.fromkeys(r for r in recipients if r)),
        title=f'{label} is trending {data.get("variance_pct")}% over estimate',
        body=project.name,
        link=f'/{scope.organization.slug}/ppm/projects/{project.id}?task={task.id}'
        if scope
        else f'/ppm/projects/{project.id}',
        subject_type='task',
        subject_id=str(task.id),
        project_id=project.id,
        via='automation',
        occurrence=f'variance:{data.get("band")}:{event.event_id}',
        data={
            k: data.get(k)
            for k in ('band', 'estimate', 'forecast', 'variance_pct', 'code', 'name')
        },
    )


async def _approval_notice(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    data = event.data or {}
    base = f'/{scope.organization.slug}/ppm/time' if scope else '/ppm/time'
    if event.topic == 'ppm.approval.requested':
        recipients, kind, title, link = (
            [str(r) for r in data.get('approvers') or []],
            'ppm:timesheet_approval',
            f'{event.actor.name or event.actor.ref or "Someone"} submitted a timesheet: {data.get("title") or ""}',
            f'{base}?tab=approvals',
        )
    elif event.topic in (
        'ppm.approval.approved',
        'ppm.approval.rejected',
        'ppm.approval.changes_requested',
    ):
        decision = event.topic.rsplit('.', 1)[1]
        recipients, kind, title, link = (
            [str(data.get('requested_by') or '')],
            'ppm:timesheet_decided',
            f'{data.get("title") or "Timesheet"}: {decision.replace("_", " ")}',
            base,
        )
    else:
        return
    await notify(
        session,
        tenant_id=event.tenant_id,
        organization_id=event.organization_id,
        kind=kind,
        recipients=[r for r in recipients if r],
        exclude=[event.actor.ref or ''],
        title=title,
        body='',
        link=link,
        subject_type='timesheet',
        subject_id=str(data.get('subject_id') or event.subject_id),
        via='user',
        occurrence=event.event_id,
        data={'approval_id': event.subject_id, 'decision': data.get('decision')},
    )


# --- wire -----------------------------------------------------------------------------------------


async def entries_out(
    session: DBAsyncScopedSession, entries: list[Timelog]
) -> list[dict[str, Any]]:
    """Entries with their item, project, category and lock state (batched)."""
    if not entries:
        return []
    task_ids = {e.task_id for e in entries if e.task_id}
    project_ids = {e.project_id for e in entries if e.project_id}
    cat_ids = {e.time_category_id for e in entries if e.time_category_id}
    sheet_ids = {e.timesheet_id for e in entries if e.timesheet_id}

    async def by_id(model: Any, ids: set[Any]) -> dict[Any, Any]:
        if not ids:
            return {}
        return {
            r.id: r
            for r in (
                await session.scalars(select(model).where(model.id.in_(ids)))
            ).all()
        }

    tasks = await by_id(Task, task_ids)
    projects = await by_id(ews_models.Project, project_ids)
    cats = await by_id(PpmTimeCategory, cat_ids)
    sheets = await by_id(PpmTimesheet, sheet_ids)
    out = []
    for e in entries:
        task, project = tasks.get(e.task_id), projects.get(e.project_id)
        sheet = sheets.get(e.timesheet_id)
        cat = cats.get(e.time_category_id)
        out.append(
            {
                'id': str(e.id),
                'user_id': e.user_id,
                'entry_date': e.entry_date
                or (e.log_date.date() if e.log_date else None),
                'minutes': e.log_minutes or 0,
                'is_billable': bool(e.is_billable),
                'description': e.description,
                'task_id': str(e.task_id) if e.task_id else None,
                'task_code': task.code if task else None,
                'task_name': task.name if task else None,
                'project_id': str(e.project_id) if e.project_id else None,
                'project_name': project.name if project else None,
                'category': cat.key if cat else None,
                'status': e.status or 'draft',
                'source': e.source,
                'kind': e.timelog_type or 'regular',
                'reverses_id': str(e.reverses_id) if e.reverses_id else None,
                'correction_reason': e.correction_reason,
                'timesheet_id': str(e.timesheet_id) if e.timesheet_id else None,
                'start_time': e.start_time,
                'end_time': e.end_time,
                'is_recording': bool(e.is_recording),
                'needs_review': bool(e.needs_review),
                'locked': e.locked_at is not None
                or bool(sheet and sheet.status in LOCKED_SHEET),
                'editable': editable(e, sheet.status if sheet else None)
                and not e.is_recording,
            }
        )
    return out


async def my_entries(
    session: DBAsyncScopedSession,
    scope: RequestScope,
    *,
    user: str,
    date_from: date | None = None,
    date_to: date | None = None,
    task_id: UUID | None = None,
    status: str | None = None,
) -> list[Timelog]:
    q = select(Timelog).where(
        Timelog.organization_id == scope.organization_id,
        Timelog.user_id == user,
        Timelog.deleted_at.is_(None),
    )
    if date_from:
        q = q.where(Timelog.entry_date >= date_from)
    if date_to:
        q = q.where(Timelog.entry_date <= date_to)
    if task_id:
        q = q.where(Timelog.task_id == task_id)
    if status:
        q = q.where(Timelog.status == status)
    return list(
        (
            await session.scalars(
                q.order_by(Timelog.entry_date.desc(), Timelog.id.desc()).limit(2000)
            )
        ).all()
    )


async def task_entries(session: DBAsyncScopedSession, task: Task) -> list[Timelog]:
    return list(
        (
            await session.scalars(
                select(Timelog)
                .where(Timelog.task_id == task.id, Timelog.deleted_at.is_(None))
                .order_by(Timelog.entry_date.desc().nulls_last(), Timelog.id.desc())
            )
        ).all()
    )


async def can_view_sheet(
    session: DBAsyncScopedSession, scope: RequestScope, sheet: PpmTimesheet
) -> bool:
    """The person, an approver of one of its sections, or a timesheet approver of the organization."""
    if sheet.user_id == access.author(scope):
        return True
    if await is_allowed(scope, TIMESHEET, 'approve', scope.org_domains()):
        return True
    mine = approvals.me_refs(scope)
    for a in (await _sections(session, sheet)).values():
        if {r.user_ref for r in await approvals.approvers_of(session, a.id)} & mine:
            return True
    return False
