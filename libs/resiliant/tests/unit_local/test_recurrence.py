"""Tests for schedule recurrence maths (`resiliant.schedule._recurrence`)."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta

import pytest
from foundation.resiliant.schedule import CronSupportError, ScheduleJobKind
from resiliant.schedule._recurrence import compute_next_run, cron_next

_HAS_CRONITER = importlib.util.find_spec('croniter') is not None


def test_once_has_no_next_run() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert (
        compute_next_run(
            kind=ScheduleJobKind.ONCE,
            from_time=now,
            interval_seconds=None,
            cron_expr=None,
        )
        is None
    )


def test_interval_advances_by_seconds() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0)
    nxt = compute_next_run(
        kind=ScheduleJobKind.INTERVAL,
        from_time=now,
        interval_seconds=90,
        cron_expr=None,
    )
    assert nxt == now + timedelta(seconds=90)


def test_interval_requires_positive_seconds() -> None:
    with pytest.raises(ValueError):
        compute_next_run(
            kind=ScheduleJobKind.INTERVAL,
            from_time=datetime(2026, 1, 1),
            interval_seconds=0,
            cron_expr=None,
        )


@pytest.mark.skipif(not _HAS_CRONITER, reason='croniter not installed')
def test_cron_next_is_strictly_after() -> None:
    now = datetime(2026, 1, 1, 12, 30, 0)
    nxt = cron_next('0 * * * *', now)  # top of every hour
    assert nxt == datetime(2026, 1, 1, 13, 0, 0)


@pytest.mark.skipif(_HAS_CRONITER, reason='croniter is installed')
def test_cron_without_dependency_raises() -> None:
    with pytest.raises(CronSupportError):
        cron_next('0 * * * *', datetime(2026, 1, 1, 12, 0, 0))
