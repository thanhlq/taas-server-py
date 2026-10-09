"""Organization time settings ``time.*`` (taas-specs/ppm/time-expense/time-tracking-spec.md §3.3), stored in the PPM
settings of the organization (``taas_ppm_settings.settings.time``) — defaults, validation, weeks. Pure."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from foundation.exceptions import ClientException

ROUNDING_STEPS = (1, 5, 6, 10, 15)
APPROVAL_MODES = ('project_manager', 'resource_manager', 'both', 'auto')
DEFAULTS: dict[str, Any] = {
    'week_start': 'monday',
    'rounding': 'none',
    'daily_max_minutes': 1440,
    'weekly_expected_minutes': 2400,
    'submit_rule': 'warn',
    'approval_mode': 'project_manager',
    'require_description': 'never',
    'variance_warning_pct': 20,
    'variance_critical_pct': 50,
    'lock_date': None,
    'allow_future_days': False,
    'timer_auto_stop_hours': 12,
}
_CHOICES: dict[str, tuple[str, ...]] = {
    'week_start': ('monday', 'sunday'),
    'submit_rule': ('warn', 'block'),
    'approval_mode': APPROVAL_MODES,
    'require_description': ('never', 'billable', 'always'),
}
_RANGES: dict[str, tuple[int, int]] = {
    'daily_max_minutes': (60, 1440),
    'weekly_expected_minutes': (0, 10080),
    'variance_warning_pct': (1, 1000),
    'variance_critical_pct': (1, 1000),
    'timer_auto_stop_hours': (1, 72),
}


def of(settings: dict[str, Any] | None) -> dict[str, Any]:
    """``time.*`` with the defaults filled in (``settings`` = the organization's PPM settings)."""
    raw = (settings or {}).get('time')
    return {**DEFAULTS, **(raw if isinstance(raw, dict) else {})}


def clean(value: Any) -> dict[str, Any]:
    """Validated ``time`` group of a settings PATCH (unknown keys / values → 400; null = default)."""
    if not isinstance(value, dict):
        raise ClientException(detail='time must be an object')
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key not in DEFAULTS:
            raise ClientException(detail=f'unknown time setting {key!r}')
        if item is None:
            out[key] = None  # back to the default (merged by the caller)
            continue
        if key in _CHOICES:
            if item not in _CHOICES[key]:
                raise ClientException(
                    detail=f'time.{key} must be one of {", ".join(_CHOICES[key])}'
                )
        elif key in _RANGES:
            low, high = _RANGES[key]
            if (
                not isinstance(item, int)
                or isinstance(item, bool)
                or not low <= item <= high
            ):
                raise ClientException(
                    detail=f'time.{key} must be an integer from {low} to {high}'
                )
        elif key == 'rounding':
            mode, _, step = str(item).partition(':')
            if item != 'none' and (
                mode not in ('up', 'nearest')
                or not step.isdigit()
                or int(step) not in ROUNDING_STEPS
            ):
                raise ClientException(
                    detail='time.rounding must be none, up:<n> or nearest:<n> (n = 1, 5, 6, 10, 15)'
                )
        elif key == 'allow_future_days':
            if not isinstance(item, bool):
                raise ClientException(
                    detail='time.allow_future_days must be true or false'
                )
        elif key == 'lock_date':
            try:
                date.fromisoformat(str(item))
            except ValueError as error:
                raise ClientException(
                    detail='time.lock_date must be YYYY-MM-DD'
                ) from error
        out[key] = item
    if (out.get('variance_critical_pct') or DEFAULTS['variance_critical_pct']) < (
        out.get('variance_warning_pct') or DEFAULTS['variance_warning_pct']
    ):
        raise ClientException(
            detail='the critical variance must be at least the warning variance'
        )
    return out


def week_of(day: date, week_start: str = 'monday') -> tuple[date, date]:
    """First and last day of the week holding ``day``."""
    first = 0 if week_start == 'monday' else 6
    offset = (day.weekday() - first) % 7
    start = day - timedelta(days=offset)
    return start, start + timedelta(days=6)


def lock_date(settings: dict[str, Any]) -> date | None:
    value = settings.get('lock_date')
    return date.fromisoformat(str(value)) if value else None


def merge(current: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """Stored ``time`` group after a cleaned patch (``None`` removes a key)."""
    out = {**(current or {}), **patch}
    return {k: v for k, v in out.items() if v is not None}
