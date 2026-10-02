"""Durable timers on Postgres (port of ``@taas/resiliant`` ``tests/e2e/schedule.test.ts``):
one-shot, interval and cron jobs, channel and callback delivery, retries,
cancellation, singletons, concurrent pollers, stale leases, CAS outcomes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from foundation.resiliant.schedule import (
    CronExpressionError,
    ScheduleError,
    ScheduleJobStatus,
    resolve_schedule_config,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from resiliant.models import ScheduledJobTable
from resiliant.schedule import SchedulePollResult, SchedulerPoller, ScheduleService

TABLE = ScheduledJobTable.__tablename__


class RecordingPublisher:
    def __init__(self, delay: float = 0) -> None:
        self.published: list[dict[str, Any]] = []
        self.delay = delay

    async def publish(self, *, channel: str, message: Any, ordering_key: Any = None, headers: Any = None) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        self.published.append({'channel': channel, 'message': message, 'key': ordering_key})


@pytest.fixture
async def maker(db_session: AsyncSession, db_engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory (the pool); ``db_session`` truncates the tables afterwards."""
    yield async_sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture
def schedule() -> ScheduleService:
    return ScheduleService(
        resolve_schedule_config(retry_backoff_ms=0, max_retries=2, fixed_poll_interval_ms=20, initial_poll_interval_ms=20)
    )


@pytest.fixture
def poller(maker, schedule) -> Callable[..., SchedulerPoller]:
    return lambda publisher=None: SchedulerPoller(maker, service=schedule, publisher=publisher)


def past() -> datetime:
    return datetime.now(UTC) - timedelta(seconds=1)


async def tx(maker: async_sessionmaker[AsyncSession], fn: Callable[[AsyncSession], Any]) -> Any:
    async with maker() as session, session.begin():
        return await fn(session)


async def get(maker, schedule: ScheduleService, job_id: int) -> ScheduledJobTable:
    async with maker() as session:
        job = await schedule.repository.get(session, job_id)
        assert job is not None
        return job


async def backdate(maker, column: str, job_id: int, interval: str) -> None:
    async with maker() as session, session.begin():
        await session.execute(
            text(f"update {TABLE} set {column} = now() - interval '{interval}' where id = :id"), {'id': job_id}
        )


async def eventually(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError('condition not met in time')
        await asyncio.sleep(0.02)


# --------------------------------------------------------------------------- #
# Firing jobs
# --------------------------------------------------------------------------- #


async def test_one_shot_job_publishes_and_is_done_future_waits(maker, schedule, poller) -> None:
    broker = RecordingPublisher()
    p = poller(broker)
    job = await tx(
        maker,
        lambda s: schedule.schedule_once(
            s,
            job_name='charge_subscription',
            run_at=past(),
            channel='billing.charge',
            payload={'subscription_id': 'sub-1'},
            ordering_key='sub-1',
        ),
    )
    assert isinstance(job.id, int)
    await tx(maker, lambda s: schedule.schedule_after(s, job_name='later', delay_ms=3_600_000, channel='billing.charge'))

    assert await p.process_batch() == SchedulePollResult(claimed=1, succeeded=1, failed=0)
    assert broker.published == [{'channel': 'billing.charge', 'message': {'subscription_id': 'sub-1'}, 'key': 'sub-1'}]
    stored = await get(maker, schedule, job.id)
    assert (stored.status, stored.run_count, stored.claimed_at) == (ScheduleJobStatus.DONE, 1, None)
    assert stored.last_run_at is not None
    assert (await p.process_batch()).claimed == 0


async def test_create_commits_with_the_business_transaction_or_not_at_all(maker, schedule) -> None:
    with pytest.raises(RuntimeError):
        async with maker() as session, session.begin():
            await schedule.schedule_once(session, job_name='x', run_at=past(), channel='c')
            raise RuntimeError('rollback')
    async with maker() as session:
        assert (await schedule.stats(session))['scheduled'] == 0


async def test_create_never_commits_the_callers_session(maker, schedule) -> None:
    async with maker() as session:
        await schedule.schedule_once(session, job_name='x', run_at=past(), channel='c')
        await session.rollback()
    async with maker() as session:
        assert (await schedule.stats(session))['scheduled'] == 0


async def test_interval_job_reschedules_itself_and_stops_at_max_runs(maker, schedule, poller) -> None:
    fired: list[int] = []

    async def sweep(job: ScheduledJobTable) -> None:
        fired.append(job.id)

    p = poller().register('sweep', sweep)
    job = await tx(
        maker, lambda s: schedule.schedule_interval(s, job_name='sweep', interval_seconds=60, start_at=past(), max_runs=2)
    )
    await p.process_batch()
    after1 = await get(maker, schedule, job.id)
    assert (after1.status, after1.run_count) == (ScheduleJobStatus.SCHEDULED, 1)
    assert (after1.next_run_at - datetime.now(UTC)).total_seconds() > 50
    # Phase kept: start + 1 x interval.
    assert after1.next_run_at == job.next_run_at + timedelta(seconds=60)

    await backdate(maker, 'next_run_at', job.id, '2 minutes')
    await p.process_batch()
    after2 = await get(maker, schedule, job.id)
    assert (after2.status, after2.run_count) == (ScheduleJobStatus.DONE, 2)
    assert fired == [job.id, job.id]


async def test_cron_job_is_created_on_its_next_utc_occurrence_and_rejects_a_bad_expression(maker, schedule) -> None:
    job = await tx(maker, lambda s: schedule.schedule_cron(s, job_name='nightly', cron_expr=' 0 2 * * * '))
    at = job.next_run_at.astimezone(UTC)
    assert (at.hour, at.minute, at.second) == (2, 0, 0)
    assert at > datetime.now(UTC)
    assert job.cron_expr == '0 2 * * *'  # stored trimmed
    with pytest.raises(CronExpressionError):
        await tx(maker, lambda s: schedule.schedule_cron(s, job_name='bad', cron_expr='61 * * * *'))


async def test_cron_job_moves_to_the_next_occurrence_after_firing(maker, schedule, poller) -> None:
    async def noop(job: ScheduledJobTable) -> None:
        return None

    p = poller().register('every_minute', noop)
    job = await tx(maker, lambda s: schedule.schedule_cron(s, job_name='every_minute', cron_expr='* * * * *'))
    await backdate(maker, 'next_run_at', job.id, '3 hours')
    await p.process_batch()
    stored = await get(maker, schedule, job.id)
    # Missed occurrences are skipped: the next one is after now, not 3 hours ago + 1 minute.
    assert stored.status == ScheduleJobStatus.SCHEDULED
    assert stored.next_run_at > datetime.now(UTC)
    assert stored.next_run_at.second == 0


async def test_retries_a_failing_job_then_marks_it_failed(maker, schedule, poller) -> None:
    async def flaky(job: ScheduledJobTable) -> None:
        raise RuntimeError('downstream 503')

    p = poller().register('flaky', flaky)
    job = await tx(maker, lambda s: schedule.schedule_once(s, job_name='flaky', run_at=past()))
    assert job.max_retries == 2  # the configured default
    assert (await p.process_batch()).failed == 1
    retried = await get(maker, schedule, job.id)
    assert (retried.status, retried.attempts, retried.claimed_at) == (ScheduleJobStatus.SCHEDULED, 1, None)
    await p.process_batch()
    failed = await get(maker, schedule, job.id)
    assert (failed.status, failed.attempts) == (ScheduleJobStatus.FAILED, 2)
    assert '503' in (failed.last_error or '')
    assert failed.next_run_at == retried.next_run_at  # the exhausted occurrence is kept


async def test_retry_waits_for_retry_backoff_and_success_resets_attempts(maker, poller) -> None:
    schedule = ScheduleService(resolve_schedule_config(retry_backoff_ms=60_000))
    calls: list[int] = []

    async def once_failing(job: ScheduledJobTable) -> None:
        calls.append(job.attempts)
        if len(calls) == 1:
            raise RuntimeError('boom')

    p = SchedulerPoller(maker, service=schedule).register('j', once_failing)
    job = await tx(maker, lambda s: schedule.schedule_interval(s, job_name='j', interval_seconds=3600, start_at=past()))
    await p.process_batch()
    retried = await get(maker, schedule, job.id)
    assert (retried.next_run_at - datetime.now(UTC)).total_seconds() > 50
    assert (await p.process_batch()).claimed == 0  # not due before the backoff
    await backdate(maker, 'next_run_at', job.id, '1 second')
    assert (await p.process_batch()).succeeded == 1
    ok = await get(maker, schedule, job.id)
    assert (ok.status, ok.attempts, ok.last_error, ok.run_count) == (ScheduleJobStatus.SCHEDULED, 0, None, 1)
    assert calls == [0, 1]


async def test_a_job_with_neither_channel_nor_callback_fails_loudly(maker, schedule, poller) -> None:
    await tx(maker, lambda s: schedule.schedule_once(s, job_name='orphan', run_at=past(), max_retries=1))
    await poller().process_batch()
    async with maker() as session:
        assert (await schedule.stats(session))['failed'] == 1


async def test_a_channel_job_without_publisher_fails(maker, schedule, poller) -> None:
    job = await tx(maker, lambda s: schedule.schedule_once(s, job_name='x', run_at=past(), channel='c', max_retries=1))
    assert (await poller().process_batch()).failed == 1
    assert 'no publisher' in ((await get(maker, schedule, job.id)).last_error or '')


async def test_invalid_definitions_are_refused(maker, schedule) -> None:
    async with maker() as session:
        with pytest.raises(ScheduleError):
            await schedule.schedule_after(session, job_name='x', delay_ms=-1)
        with pytest.raises(ScheduleError):
            await schedule.schedule_interval(session, job_name='x', interval_seconds=0)
        with pytest.raises(ScheduleError):
            await schedule.schedule_interval(session, job_name='x', interval_seconds=1.5)  # type: ignore[arg-type]
        with pytest.raises(ScheduleError):
            await schedule.schedule_once(session, job_name='', run_at=past())
        with pytest.raises(ScheduleError):
            await schedule.schedule_interval(session, job_name='x', interval_seconds=5, max_runs=0)


# --------------------------------------------------------------------------- #
# Coordination
# --------------------------------------------------------------------------- #


async def test_cancel_stops_a_job_and_unique_key_keeps_one_active_job_per_key(maker, schedule, poller) -> None:
    job = await tx(maker, lambda s: schedule.schedule_once(s, job_name='x', run_at=past(), channel='c'))
    assert await tx(maker, lambda s: schedule.cancel(s, job.id)) is True
    assert await tx(maker, lambda s: schedule.cancel(s, job.id)) is False
    assert (await poller(RecordingPublisher()).process_batch()).claimed == 0

    def nightly(s: AsyncSession) -> Any:
        return schedule.schedule_cron(s, job_name='nightly', unique_key='nightly', cron_expr='@daily')

    first = await tx(maker, nightly)
    second = await tx(maker, nightly)
    assert first is not None
    assert second is None
    async with maker() as session:
        assert await schedule.exists_active(session, 'nightly') is True
        active = await schedule.repository.get_active_by_unique_key(session, 'nightly')
        assert active is not None and active.id == first.id
    # Once cancelled, the key is free again.
    await tx(maker, lambda s: schedule.cancel(s, first.id))
    assert await tx(maker, nightly) is not None


async def test_concurrent_pollers_fire_each_occurrence_exactly_once(maker, schedule, poller) -> None:
    async def create(s: AsyncSession) -> None:
        for i in range(40):
            await schedule.schedule_once(s, job_name='tick', run_at=past(), channel='ticks', payload={'i': i})

    await tx(maker, create)
    broker = RecordingPublisher(delay=0.001)
    pollers = [poller(broker) for _ in range(3)]
    await asyncio.gather(*(p.process_batch() for p in pollers))
    assert len(broker.published) == 40
    assert len({m['message']['i'] for m in broker.published}) == 40


async def test_reschedules_a_job_left_running_by_a_crashed_poller(maker, schedule) -> None:
    job = await tx(maker, lambda s: schedule.schedule_once(s, job_name='x', run_at=past(), channel='c'))
    claimed = await tx(maker, lambda s: schedule.repository.claim_due(s, 10))
    assert [j.id for j in claimed] == [job.id]
    running = await get(maker, schedule, job.id)
    assert running.status == ScheduleJobStatus.RUNNING and running.claimed_at is not None
    assert await tx(maker, lambda s: schedule.repository.reset_stale(s, 60_000)) == 0
    await backdate(maker, 'claimed_at', job.id, '10 minutes')
    assert await tx(maker, lambda s: schedule.repository.reset_stale(s, 60_000)) == 1
    reset = await get(maker, schedule, job.id)
    assert (reset.status, reset.claimed_at) == (ScheduleJobStatus.SCHEDULED, None)


async def test_a_claimed_job_is_invisible_to_other_claims(maker, schedule) -> None:
    await tx(maker, lambda s: schedule.schedule_once(s, job_name='x', run_at=past(), channel='c'))
    async with maker() as holder, holder.begin():
        first = await schedule.repository.claim_due(holder, 10)
        # The row is locked (SKIP LOCKED) and, once committed, RUNNING: never claimed twice.
        assert await tx(maker, lambda s: schedule.repository.claim_due(s, 10)) == []
    assert len(first) == 1
    assert await tx(maker, lambda s: schedule.repository.claim_due(s, 10)) == []


async def test_a_cancel_wins_over_an_in_flight_fire(maker, schedule, poller) -> None:
    holder: dict[str, int] = {}

    async def cancel_myself(job: ScheduledJobTable) -> None:
        await tx(maker, lambda s: schedule.cancel(s, holder['id']))

    p = poller().register('self_cancel', cancel_myself)
    job = await tx(maker, lambda s: schedule.schedule_interval(s, job_name='self_cancel', interval_seconds=60, start_at=past()))
    holder['id'] = job.id
    result = await p.process_batch()
    assert result == SchedulePollResult(claimed=1, succeeded=0, failed=0)
    stored = await get(maker, schedule, job.id)
    assert (stored.status, stored.run_count) == (ScheduleJobStatus.CANCELLED, 0)


async def test_stats_count_statuses_and_the_oldest_overdue_job(maker, schedule) -> None:
    job = await tx(maker, lambda s: schedule.schedule_once(s, job_name='x', run_at=past(), channel='c'))
    await backdate(maker, 'next_run_at', job.id, '1 minute')
    await tx(maker, lambda s: schedule.schedule_after(s, job_name='y', delay_ms=60_000, channel='c'))
    async with maker() as session:
        stats = await schedule.stats(session)
    assert stats['scheduled'] == 2
    assert stats['running'] == stats['done'] == stats['failed'] == stats['cancelled'] == 0
    assert 59_000 <= stats['oldest_overdue_ms'] < 120_000


async def test_the_poller_loop_fires_due_jobs_until_stopped(maker, schedule, poller) -> None:
    broker = RecordingPublisher()
    p = poller(broker)
    await p.start()
    try:
        await tx(maker, lambda s: schedule.schedule_once(s, job_name='loop', run_at=past(), channel='c', payload={'n': 1}))
        p.wake()
        await eventually(lambda: len(broker.published) == 1)
        assert p.check_health()['status'] == 'up'
    finally:
        await p.stop()
    assert p.check_health()['status'] == 'down'
