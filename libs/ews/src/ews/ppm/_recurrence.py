"""Recurring items (taas-specs/ppm/work-model/work-model-spec.md Ppm-0890): an RFC 5545 RRULE subset —
``FREQ=DAILY|WEEKLY|MONTHLY|YEARLY``, ``INTERVAL``, ``BYDAY`` (weekly: ``MO,WE``; monthly: ``2TU`` / ``-1FR``),
``BYMONTHDAY``, ``COUNT``, ``UNTIL`` (``YYYYMMDD``). Completing an occurrence creates the next one: same fields,
checklist unchecked, dates shifted, same ``recurrence_id``. The date rules are pure (:func:`next_date`)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import db.models.ews as ews_models
from foundation.db.types import DBAsyncScopedSession
from foundation.exceptions import ClientException
from sqlalchemy import func, select

from ews.security import RequestScope

from . import _events as events

DAYS = ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')
FREQS = ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')


@dataclass(frozen=True, slots=True)
class Rule:
    freq: str
    interval: int = 1
    by_day: tuple[tuple[int, int], ...] = ()
    """``(ordinal, weekday)``: ordinal 0 = every (weekly), 1…5 / -1 = nth of the month."""
    by_month_day: int | None = None
    count: int | None = None
    until: date | None = None


def parse(text: str | None) -> Rule | None:
    """``FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH`` → :class:`Rule` (400 on anything outside the subset)."""
    if not text:
        return None
    parts: dict[str, str] = {}
    for chunk in text.strip().removeprefix('RRULE:').split(';'):
        if not chunk:
            continue
        key, _, value = chunk.partition('=')
        parts[key.strip().upper()] = value.strip().upper()
    freq = parts.get('FREQ')
    if freq not in FREQS:
        raise ClientException(
            detail='recurrence needs FREQ=DAILY|WEEKLY|MONTHLY|YEARLY',
            extra={'code': 'invalid_recurrence'},
        )
    try:
        interval = max(1, min(999, int(parts.get('INTERVAL') or 1)))
        by_day: list[tuple[int, int]] = []
        for token in filter(None, (parts.get('BYDAY') or '').split(',')):
            ordinal = int(token[:-2]) if len(token) > 2 else 0
            by_day.append((ordinal, DAYS.index(token[-2:])))
        month_day = int(parts['BYMONTHDAY']) if parts.get('BYMONTHDAY') else None
        count = int(parts['COUNT']) if parts.get('COUNT') else None
        until = (
            datetime.strptime(parts['UNTIL'][:8], '%Y%m%d').date()
            if parts.get('UNTIL')
            else None
        )
    except ValueError, IndexError:
        raise ClientException(
            detail=f'invalid recurrence {text!r}', extra={'code': 'invalid_recurrence'}
        ) from None
    if month_day is not None and not (1 <= month_day <= 31 or -31 <= month_day <= -1):
        raise ClientException(
            detail='BYMONTHDAY must be 1…31 or -1…-31',
            extra={'code': 'invalid_recurrence'},
        )
    return Rule(freq, interval, tuple(by_day), month_day, count, until)


def _add_months(day: date, months: int) -> date:
    m = day.month - 1 + months
    year, month = day.year + m // 12, m % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _nth_weekday(year: int, month: int, ordinal: int, weekday: int) -> date | None:
    days = [
        d
        for d in range(1, calendar.monthrange(year, month)[1] + 1)
        if date(year, month, d).weekday() == weekday
    ]
    if ordinal > 0:
        return date(year, month, days[ordinal - 1]) if ordinal <= len(days) else None
    return date(year, month, days[ordinal]) if -len(days) <= ordinal <= -1 else None


def _month_candidates(rule: Rule, year: int, month: int, anchor_day: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    if rule.by_day:
        out = [
            d
            for o, w in rule.by_day
            if (d := _nth_weekday(year, month, o or 1, w)) is not None
        ]
        return sorted(out)
    if rule.by_month_day is not None:
        md = (
            rule.by_month_day if rule.by_month_day > 0 else last + 1 + rule.by_month_day
        )
        return [date(year, month, md)] if 1 <= md <= last else []
    return [date(year, month, min(anchor_day, last))]


def next_date(rule: Rule, current: date, occurrence: int = 1) -> date | None:
    """The occurrence after ``current`` (the ``occurrence``-th of the series); ``None`` when the series ended."""
    if rule.count is not None and occurrence >= rule.count:
        return None
    nxt: date | None
    if rule.freq == 'DAILY':
        nxt = current + timedelta(days=rule.interval)
    elif rule.freq == 'WEEKLY':
        days = sorted({w for _, w in rule.by_day}) or [current.weekday()]
        later = [w for w in days if w > current.weekday()]
        if later:
            nxt = current + timedelta(days=later[0] - current.weekday())
        else:
            week_start = current - timedelta(days=current.weekday())
            nxt = week_start + timedelta(weeks=rule.interval, days=days[0])
    elif rule.freq == 'MONTHLY':
        nxt = None
        same = [
            d
            for d in _month_candidates(rule, current.year, current.month, current.day)
            if d > current
        ]
        if same:
            nxt = same[0]
        else:
            for k in range(1, 48):
                month = _add_months(
                    date(current.year, current.month, 1), rule.interval * k
                )
                found = _month_candidates(rule, month.year, month.month, current.day)
                if found:
                    nxt = found[0]
                    break
    else:  # YEARLY
        nxt = _add_months(current, 12 * rule.interval)
    if nxt is not None and rule.until is not None and nxt > rule.until:
        return None
    return nxt


# --- the next occurrence ---------------------------------------------------------------------------------


async def _occurrences(session: DBAsyncScopedSession, recurrence_id: str) -> int:
    t = ews_models.Task
    return int(
        await session.scalar(
            select(func.count(t.id)).where(t.recurrence_id == recurrence_id)
        )
        or 0
    )


async def create_next(
    session: DBAsyncScopedSession, scope: RequestScope | None, task: ews_models.Task
) -> ews_models.Task | None:
    """The next occurrence of a completed recurring item, or None at the end of the series."""
    from . import _checklists as checklists
    from . import _work_items as items

    rule = parse(task.recurrence_rule)
    if rule is None or task.project_id is None or scope is None:
        return None
    anchor = task.due_date or task.start_date
    if anchor is None:
        return None
    occurrence = await _occurrences(session, task.recurrence_id or str(task.id))
    day = next_date(rule, anchor.date(), occurrence)
    if day is None:
        return None
    shift = datetime.combine(day, anchor.time()) - anchor
    project = await session.get(ews_models.Project, task.project_id)
    if project is None or project.deleted_at is not None:
        return None
    steps = await checklists.listing(session, task.id)
    collabs = (await items.collaborators(session, [task.id])).get(task.id, [])
    new = items.NewItem(
        name=task.name or '',
        description=task.description,
        description_html=task.html_text,
        description_doc=task.description_doc,
        workflow_id=str(task.workflow_id) if task.workflow_id else None,
        work_item_type=task.work_item_type,
        parent_id=task.parent_id,
        requested_user_id=task.requested_user_id,
        owner=task.user_id,
        collaborators=collabs,
        task_list_id=task.task_list_id,
        labels=list((task.tags or {}).get('labels') or []),
        priority=task.priority,
        start_date=task.start_date + shift if task.start_date else None,
        due_date=task.due_date + shift if task.due_date else None,
        estimated_minutes=task.estimated_minutes,
        progress_mode=task.progress_mode,
        recurrence_rule=task.recurrence_rule,
        recurrence_id=task.recurrence_id or str(task.id),
        cause='recurrence',
    )
    with events.caused_by('recurrence'):
        nxt = await items.create_item(session, scope, project, new)
        for step in steps:
            await checklists.add(
                session,
                scope,
                nxt,
                name=step.name or '',
                assignee=step.assignee_user_id,
                due_date=step.due_date + shift if step.due_date else None,
                mandatory=bool(step.is_mandatory),
            )
    return nxt


@events.subscribe
async def on_completed(
    session: DBAsyncScopedSession, scope: RequestScope | None, event: events.Event
) -> None:
    if event.topic != 'ppm.task.completed' or event.subject_type != 'task':
        return
    task = await session.get(ews_models.Task, UUID(event.subject_id))
    if task is None or not task.recurrence_rule:
        return
    t = ews_models.Task
    # one next occurrence per completion: none when a later open occurrence already exists
    later = await session.scalar(
        select(t.id).where(
            t.recurrence_id == (task.recurrence_id or str(task.id)),
            t.id != task.id,
            t.completed_at.is_(None),
            t.deleted_at.is_(None),
        )
    )
    if later is None:
        await create_next(session, scope, task)


def describe(rule: Rule) -> dict[str, Any]:
    """Wire form of a parsed rule (UI summaries)."""
    return {
        'freq': rule.freq,
        'interval': rule.interval,
        'by_day': [f'{o or ""}{DAYS[w]}' for o, w in rule.by_day],
        'by_month_day': rule.by_month_day,
        'count': rule.count,
        'until': rule.until.isoformat() if rule.until else None,
    }
