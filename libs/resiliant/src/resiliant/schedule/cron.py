"""
A small, dependency-free cron evaluator: standard 5 fields (minute hour
day-of-month month day-of-week), always in UTC — port of ``@taas/resiliant``
``schedule/cron.ts`` (same results on the same input).

Supported: ``*``, values, ranges ``a-b``, steps ``*/n`` ``a-b/n`` ``a/n``, lists,
month / weekday names (``JAN``, ``MON``), weekday 7 = Sunday, and the macros
``@yearly @annually @monthly @weekly @daily @midnight @hourly``. Day-of-month and
day-of-week follow Vixie cron exactly: when both fields are restricted (neither
starts with ``*``) a day matches either of them, otherwise both.

UTC only on purpose: a financial job must not fire twice (or never) on a
daylight-saving change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from foundation.resiliant.schedule import CronExpressionError


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    name: str
    min: int
    max: int
    names: tuple[str, ...] = ()


_FIELDS: tuple[_FieldSpec, ...] = (
    _FieldSpec('minute', 0, 59),
    _FieldSpec('hour', 0, 23),
    _FieldSpec('day-of-month', 1, 31),
    _FieldSpec(
        'month', 1, 12, ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
    ),
    _FieldSpec('day-of-week', 0, 7, ('SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT')),
)

_MACROS: dict[str, str] = {
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
    '@monthly': '0 0 1 * *',
    '@weekly': '0 0 * * 0',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@hourly': '0 * * * *',
}

# Searching more than this far ahead means the expression never fires (e.g. ``0 0 30 2 *``).
MAX_SEARCH_YEARS = 8

_DIGITS = re.compile(r'[0-9]+')
_WHITESPACE = re.compile(r'\s+')


@dataclass(frozen=True, slots=True)
class CronSchedule:
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days_of_month: frozenset[int]
    months: frozenset[int]
    days_of_week: frozenset[int]
    dom_star: bool
    """The day-of-month field starts with ``*`` (Vixie's DOM_STAR)."""
    dow_star: bool
    """The day-of-week field starts with ``*`` (Vixie's DOW_STAR)."""


def _parse_value(raw: str, spec: _FieldSpec, expression: str) -> int:
    upper = raw.upper()
    if upper in spec.names:
        return spec.names.index(upper) + (1 if spec.name == 'month' else 0)
    if not _DIGITS.fullmatch(raw):
        raise CronExpressionError(expression, f'"{raw}" is not a valid {spec.name}')
    value = int(raw)
    if value < spec.min or value > spec.max:
        raise CronExpressionError(expression, f'{spec.name} {value} is outside {spec.min}-{spec.max}')
    return value


def _parse_field(field: str, spec: _FieldSpec, expression: str) -> frozenset[int]:
    values: set[int] = set()
    for part in field.split(','):
        if part == '':
            raise CronExpressionError(expression, f'empty item in {spec.name}')
        pieces = part.split('/')
        range_, step_raw = pieces[0], (pieces[1] if len(pieces) > 1 else None)
        step = 1
        if step_raw is not None:
            if not _DIGITS.fullmatch(step_raw) or int(step_raw) < 1:
                raise CronExpressionError(
                    expression, f'step "{step_raw}" in {spec.name} must be a positive integer'
                )
            step = int(step_raw)
        if range_ == '*':
            start = spec.min
            end = 6 if spec.name == 'day-of-week' else spec.max
        elif '-' in range_:
            bounds = range_.split('-')
            start = _parse_value(bounds[0], spec, expression)
            end = _parse_value(bounds[1], spec, expression)
            if start > end:
                raise CronExpressionError(expression, f'range {range_} in {spec.name} is reversed')
        else:
            start = _parse_value(range_, spec, expression)
            # ``a/n`` means "from a to the maximum, every n" (Vixie).
            end = start if step_raw is None else spec.max
        for v in range(start, end + 1, step):
            values.add(0 if spec.name == 'day-of-week' and v == 7 else v)
    return frozenset(values)


def parse_cron(expression: str) -> CronSchedule:
    """Parse a 5-field expression or macro; raises :class:`CronExpressionError`."""
    source = expression.strip()
    expanded = _MACROS.get(source.lower(), source)
    fields = _WHITESPACE.split(expanded)
    if len(fields) != 5:
        raise CronExpressionError(expression, f'expected 5 fields, got {len(fields)}')
    parsed = [_parse_field(fields[i], _FIELDS[i], expression) for i in range(5)]
    return CronSchedule(
        expression=source,
        minutes=parsed[0],
        hours=parsed[1],
        days_of_month=parsed[2],
        months=parsed[3],
        days_of_week=parsed[4],
        dom_star=fields[2].startswith('*'),
        dow_star=fields[4].startswith('*'),
    )


def _day_matches(schedule: CronSchedule, t: datetime) -> bool:
    dom = t.day in schedule.days_of_month
    dow = (t.isoweekday() % 7) in schedule.days_of_week  # Sunday = 0
    return (dom and dow) if schedule.dom_star or schedule.dow_star else (dom or dow)


def _as_utc(value: datetime) -> datetime:
    """Aware UTC; a naive datetime is taken as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def next_cron_time(schedule_or_expression: CronSchedule | str, after: datetime) -> datetime:
    """The first fire time strictly after ``after`` (minute precision, aware UTC)."""
    schedule = (
        parse_cron(schedule_or_expression)
        if isinstance(schedule_or_expression, str)
        else schedule_or_expression
    )
    after = _as_utc(after)
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = after + timedelta(days=MAX_SEARCH_YEARS * 366)
    while t <= limit:
        if t.month not in schedule.months:
            t = (
                t.replace(year=t.year + 1, month=1, day=1)
                if t.month == 12
                else t.replace(month=t.month + 1, day=1)
            ).replace(hour=0, minute=0)
            continue
        if not _day_matches(schedule, t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in schedule.hours:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute not in schedule.minutes:
            t = t + timedelta(minutes=1)
            continue
        return t
    raise CronExpressionError(schedule.expression, f'never fires within {MAX_SEARCH_YEARS} years')


__all__ = ['MAX_SEARCH_YEARS', 'CronSchedule', 'next_cron_time', 'parse_cron']
