"""
When a job fires next (port of ``@taas/resiliant`` ``schedule/recurrence.ts``).

Missed occurrences are skipped, not replayed: after downtime a recurring job fires
once, then continues on its schedule. A burst of catch-up runs (e.g. 48 hourly fee
sweeps at once after a two-day outage) is never what a financial job wants; a job
that must account for the gap reads its own ``last_run_at``. Interval jobs keep
their phase (``start + k x interval``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from foundation.resiliant.schedule import ScheduleError, ScheduleJobKind

from .cron import next_cron_time


def compute_next_run(
    *,
    kind: ScheduleJobKind | str,
    scheduled_at: datetime,
    now: datetime,
    interval_seconds: int | None,
    cron_expr: str | None,
) -> datetime | None:
    """Next occurrence after the one that just fired (``scheduled_at``); ``None`` for a one-shot job."""
    if kind == ScheduleJobKind.ONCE:
        return None
    if kind == ScheduleJobKind.INTERVAL:
        if not interval_seconds or interval_seconds <= 0:
            raise ScheduleError('an interval job needs a positive interval_seconds')
        step = timedelta(seconds=interval_seconds)
        periods = max(1, (now - scheduled_at) // step + 1)
        return scheduled_at + periods * step
    if kind == ScheduleJobKind.CRON:
        if not cron_expr:
            raise ScheduleError('a cron job needs a cron expression')
        return next_cron_time(cron_expr, now if now > scheduled_at else scheduled_at)
    raise ScheduleError(f'unknown schedule kind "{kind}"')


__all__ = ['compute_next_run']
