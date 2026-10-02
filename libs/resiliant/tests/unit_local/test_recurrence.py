"""UTC cron evaluator and recurrence (port of ``@taas/resiliant`` ``tests/unit/cron.test.ts``)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from foundation.resiliant.schedule import CronExpressionError, ScheduleError, ScheduleJobKind
from resiliant.schedule import compute_next_run, next_cron_time, parse_cron


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace('Z', '+00:00'))


def nxt(expr: str, start: str) -> str:
    return next_cron_time(expr, at(start)).isoformat()


def test_fires_strictly_after_the_reference_time_at_minute_precision() -> None:
    assert nxt('* * * * *', '2026-01-01T10:00:00.000Z') == '2026-01-01T10:01:00+00:00'
    assert nxt('* * * * *', '2026-01-01T10:00:59.999Z') == '2026-01-01T10:01:00+00:00'
    assert nxt('0 2 * * *', '2026-01-01T02:00:00.000Z') == '2026-01-02T02:00:00+00:00'


def test_supports_steps_ranges_lists_and_a_slash_n() -> None:
    assert nxt('*/15 * * * *', '2026-01-01T10:07:00Z') == '2026-01-01T10:15:00+00:00'
    assert nxt('0 9-17/4 * * *', '2026-01-01T10:00:00Z') == '2026-01-01T13:00:00+00:00'
    assert nxt('5,35 * * * *', '2026-01-01T10:06:00Z') == '2026-01-01T10:35:00+00:00'
    assert nxt('10/20 * * * *', '2026-01-01T10:31:00Z') == '2026-01-01T10:50:00+00:00'


def test_knows_month_and_weekday_names_and_7_as_sunday() -> None:
    assert nxt('0 0 1 FEB *', '2026-01-15T00:00:00Z') == '2026-02-01T00:00:00+00:00'
    # 2026-01-01 is a Thursday.
    assert nxt('0 12 * * MON', '2026-01-01T00:00:00Z') == '2026-01-05T12:00:00+00:00'
    assert nxt('0 0 * * 7', '2026-01-01T00:00:00Z') == '2026-01-04T00:00:00+00:00'
    assert nxt('0 0 * * mon-fri', '2026-01-03T00:00:00Z') == '2026-01-05T00:00:00+00:00'


def test_ors_day_of_month_and_day_of_week_only_when_both_are_restricted() -> None:
    # The 13th OR any Friday: Friday 2026-01-02 comes first.
    assert nxt('0 0 13 * FRI', '2026-01-01T00:00:00Z') == '2026-01-02T00:00:00+00:00'
    # ``*`` in day-of-week: only the 13th.
    assert nxt('0 0 13 * *', '2026-01-01T00:00:00Z') == '2026-01-13T00:00:00+00:00'
    # ``*/2`` starts with ``*``: both must match (odd days that are Fridays).
    assert nxt('0 0 */2 * FRI', '2026-01-01T00:00:00Z') == '2026-01-09T00:00:00+00:00'


def test_expands_macros_and_rolls_over_years_leap_days_included() -> None:
    assert nxt('@daily', '2026-12-31T23:59:00Z') == '2027-01-01T00:00:00+00:00'
    assert nxt('@hourly', '2026-01-01T10:30:00Z') == '2026-01-01T11:00:00+00:00'
    assert nxt('0 0 29 2 *', '2026-03-01T00:00:00Z') == '2028-02-29T00:00:00+00:00'


def test_naive_and_non_utc_references_are_evaluated_in_utc() -> None:
    assert next_cron_time('0 2 * * *', datetime(2026, 1, 1, 1, 0)) == datetime(2026, 1, 1, 2, 0, tzinfo=UTC)
    assert nxt('0 2 * * *', '2026-01-01T03:30:00+02:00') == '2026-01-01T02:00:00+00:00'  # 01:30Z


@pytest.mark.parametrize(
    'bad', ['* * * *', '60 * * * *', '* * 0 * *', '*/0 * * * *', '5-1 * * * *', 'x * * * *', '1,,2 * * * *', '']
)
def test_rejects_malformed_expressions_loudly(bad: str) -> None:
    with pytest.raises(CronExpressionError):
        parse_cron(bad)


def test_rejects_an_expression_that_never_fires() -> None:
    with pytest.raises(CronExpressionError, match='never fires'):
        next_cron_time('0 0 30 2 *', at('2026-01-01T00:00:00Z'))


def test_parse_keeps_the_trimmed_expression_and_vixie_star_flags() -> None:
    schedule = parse_cron('  0 0 */2 * FRI ')
    assert schedule.expression == '0 0 */2 * FRI'
    assert (schedule.dom_star, schedule.dow_star) == (True, False)
    assert schedule.days_of_week == frozenset({5})


# --------------------------------------------------------------------------- #
# Recurrence
# --------------------------------------------------------------------------- #

NOW = at('2026-01-01T12:00:00Z')


def test_a_one_shot_job_has_no_next_run() -> None:
    assert (
        compute_next_run(kind=ScheduleJobKind.ONCE, scheduled_at=NOW, now=NOW, interval_seconds=None, cron_expr=None)
        is None
    )


def test_an_interval_job_keeps_its_phase_and_skips_missed_occurrences() -> None:
    scheduled_at = at('2026-01-01T11:00:00Z')
    late = compute_next_run(
        kind=ScheduleJobKind.INTERVAL,
        scheduled_at=scheduled_at,
        now=at('2026-01-01T11:59:30Z'),
        interval_seconds=600,
        cron_expr=None,
    )
    # 11:00 + k x 10 min, first one after 11:59:30 - not 11:10 (no catch-up burst).
    assert late == at('2026-01-01T12:00:00Z')
    on_time = compute_next_run(
        kind=ScheduleJobKind.INTERVAL, scheduled_at=scheduled_at, now=scheduled_at, interval_seconds=600, cron_expr=None
    )
    assert on_time == at('2026-01-01T11:10:00Z')


def test_a_cron_job_continues_from_now_after_downtime() -> None:
    nxt_run = compute_next_run(
        kind=ScheduleJobKind.CRON,
        scheduled_at=at('2025-12-30T02:00:00Z'),
        now=NOW,
        interval_seconds=None,
        cron_expr='0 2 * * *',
    )
    assert nxt_run == at('2026-01-02T02:00:00Z')


def test_refuses_a_recurring_job_without_its_recurrence() -> None:
    with pytest.raises(ScheduleError):
        compute_next_run(kind=ScheduleJobKind.INTERVAL, scheduled_at=NOW, now=NOW, interval_seconds=0, cron_expr=None)
    with pytest.raises(ScheduleError):
        compute_next_run(kind=ScheduleJobKind.CRON, scheduled_at=NOW, now=NOW, interval_seconds=None, cron_expr=None)
