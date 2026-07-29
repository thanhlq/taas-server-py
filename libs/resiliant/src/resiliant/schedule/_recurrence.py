"""Recurrence maths for scheduled jobs (interval + cron).

``croniter`` is imported lazily so the dependency is only required when a CRON
job is actually scheduled/advanced — INTERVAL and ONCE jobs work without it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from foundation.resiliant.schedule import CronSupportError, ScheduleJobKind
from foundation.utils import now_in_utc


def utcnow_naive() -> datetime:
    """Naive UTC ``now`` — matches the ``TIMESTAMP(timezone=False)`` columns."""
    return now_in_utc().replace(tzinfo=None)


def cron_next(cron_expr: str, after: datetime) -> datetime:
    """Return the next cron fire time strictly after ``after``.

    Raises:
        CronSupportError: if the optional ``croniter`` dependency is missing.
    """
    try:
        from croniter import croniter  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without croniter
        raise CronSupportError(
            'Scheduling a CRON job requires the optional "croniter" dependency. '
            'Add it to libs/resiliant and run `uv sync`, or use an INTERVAL job.'
        ) from exc

    return croniter(cron_expr, after).get_next(datetime)


def compute_next_run(
    *,
    kind: ScheduleJobKind,
    from_time: datetime,
    interval_seconds: int | None,
    cron_expr: str | None,
) -> datetime | None:
    """Compute the next fire time after a successful run.

    Returns ``None`` for a ONCE job (nothing more to schedule).
    """
    if kind is ScheduleJobKind.ONCE:
        return None
    if kind is ScheduleJobKind.INTERVAL:
        if not interval_seconds or interval_seconds <= 0:
            raise ValueError('INTERVAL job requires a positive interval_seconds')
        return from_time + timedelta(seconds=interval_seconds)
    if kind is ScheduleJobKind.CRON:
        if not cron_expr:
            raise ValueError('CRON job requires a cron_expr')
        return cron_next(cron_expr, from_time)
    raise ValueError(f'Unknown schedule kind: {kind!r}')
