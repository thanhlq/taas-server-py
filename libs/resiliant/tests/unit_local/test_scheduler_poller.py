"""`SchedulerPoller.process_batch` decision logic with in-memory fakes (no database, no broker):
channel vs callback dispatch, reschedule on success, retry / FAILED on error, CAS outcomes,
registration, settings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from foundation.resiliant.schedule import (
    ScheduleError,
    ScheduleJobKind,
    ScheduleJobStatus,
    resolve_schedule_config,
)
from resiliant.models import ScheduledJobTable
from resiliant.schedule import SchedulePollResult, SchedulerPoller, ScheduleService, ScheduleSettings

NOW = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)


class FakeSession:
    """Async context manager whose ``begin()`` is one too; records transaction boundaries."""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def begin(self) -> FakeSession:
        self.log.append('begin')
        return self


class FakeRepository:
    def __init__(self, jobs: list[ScheduledJobTable], *, cas_ok: bool = True) -> None:
        self.jobs = jobs
        self.cas_ok = cas_ok
        self.succeeded: list[tuple[int, datetime | None]] = []
        self.failed: list[tuple[int, str, datetime]] = []

    async def claim_due(self, session: Any, limit: int) -> list[ScheduledJobTable]:
        claimed, self.jobs = self.jobs[:limit], self.jobs[limit:]
        return claimed

    async def mark_succeeded(self, session: Any, job: ScheduledJobTable, next_run_at: datetime | None) -> bool:
        self.succeeded.append((job.id, next_run_at))
        return self.cas_ok

    async def mark_failed(self, session: Any, job: ScheduledJobTable, error: str, retry_at: datetime) -> Any:
        self.failed.append((job.id, error, retry_at))
        if not self.cas_ok:
            return None
        return ScheduleJobStatus.FAILED if job.attempts + 1 >= job.max_retries else ScheduleJobStatus.SCHEDULED


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, *, channel: str, message: Any, ordering_key: Any = None, headers: Any = None) -> None:
        self.published.append({'channel': channel, 'message': message, 'ordering_key': ordering_key, 'headers': headers})


def _job(**overrides: Any) -> ScheduledJobTable:
    base: dict[str, Any] = {
        'id': 1,
        'job_name': 'charge',
        'kind': ScheduleJobKind.ONCE,
        'cron_expr': None,
        'interval_seconds': None,
        'channel': None,
        'event_type': None,
        'ordering_key': None,
        'payload': {'x': 1},
        'headers': None,
        'next_run_at': datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        'run_count': 0,
        'attempts': 0,
        'max_retries': 3,
        'max_runs': None,
    }
    base.update(overrides)
    return ScheduledJobTable(**base)


def _poller(repo: FakeRepository, publisher: FakePublisher | None = None, log: list[str] | None = None) -> SchedulerPoller:
    service = ScheduleService(
        resolve_schedule_config(retry_backoff_ms=5_000), repository=repo, clock=lambda: NOW  # type: ignore[arg-type]
    )
    session_log = log if log is not None else []
    return SchedulerPoller(lambda: FakeSession(session_log), service=service, publisher=publisher)  # type: ignore[arg-type,return-value]


async def test_once_job_publishes_to_its_channel_and_completes() -> None:
    repo, pub = FakeRepository([_job(channel='billing.charge', ordering_key='u-1')]), FakePublisher()
    log: list[str] = []
    result = await _poller(repo, pub, log).process_batch()

    assert result == SchedulePollResult(claimed=1, succeeded=1, failed=0)
    assert pub.published == [{'channel': 'billing.charge', 'message': {'x': 1}, 'ordering_key': 'u-1', 'headers': None}]
    assert repo.succeeded == [(1, None)]  # once -> no next run
    assert log == ['begin', 'begin']  # the claim commits alone, then one transaction per outcome


async def test_interval_job_reschedules_on_its_phase_from_the_clock() -> None:
    repo = FakeRepository([_job(kind=ScheduleJobKind.INTERVAL, interval_seconds=60, channel='ticks')])
    await _poller(repo, FakePublisher()).process_batch()
    assert repo.succeeded == [(1, datetime(2026, 1, 1, 12, 1, 0, tzinfo=UTC))]


async def test_callback_dispatch_when_no_channel() -> None:
    repo = FakeRepository([_job()])
    poller = _poller(repo)
    seen: list[str] = []

    async def handler(job: ScheduledJobTable) -> None:
        seen.append(job.job_name)

    poller.register('charge', handler)
    await poller.process_batch()
    assert seen == ['charge']
    assert repo.succeeded == [(1, None)]


async def test_dispatch_failure_retries_after_retry_backoff() -> None:
    repo = FakeRepository([_job()])
    poller = _poller(repo)

    async def boom(job: ScheduledJobTable) -> None:
        raise RuntimeError('provider down')

    poller.register('charge', boom)
    assert await poller.process_batch() == SchedulePollResult(claimed=1, succeeded=0, failed=1)
    assert repo.succeeded == []
    [(job_id, error, retry_at)] = repo.failed
    assert job_id == 1
    assert error == 'RuntimeError: provider down'
    assert retry_at == NOW + timedelta(milliseconds=5_000)


@pytest.mark.parametrize('publisher', [None, FakePublisher()])
async def test_missing_target_fails_the_job(publisher: FakePublisher | None) -> None:
    # No callback for a channel-less job; or a channel job with no publisher.
    job = _job() if publisher else _job(channel='c')
    repo = FakeRepository([job])
    await _poller(repo, publisher).process_batch()
    assert repo.succeeded == []
    assert 'ScheduleError' in repo.failed[0][1]


async def test_broken_recurrence_stops_the_job_instead_of_refiring_it() -> None:
    repo = FakeRepository([_job(kind=ScheduleJobKind.CRON, cron_expr=None, channel='c')])
    result = await _poller(repo, FakePublisher()).process_batch()
    assert result.succeeded == 1
    assert repo.succeeded == [(1, None)]


async def test_an_outcome_lost_to_a_concurrent_change_is_not_counted() -> None:
    repo = FakeRepository([_job(channel='c')], cas_ok=False)
    assert await _poller(repo, FakePublisher()).process_batch() == SchedulePollResult(claimed=1, succeeded=0, failed=0)


async def test_batches_are_bounded_by_batch_size() -> None:
    repo = FakeRepository([_job(id=i, channel='c') for i in range(150)])
    assert (await _poller(repo, FakePublisher()).process_batch()).claimed == 100
    assert (await _poller(repo, FakePublisher()).process_batch()).claimed == 50


def test_a_job_name_takes_one_callback() -> None:
    poller = _poller(FakeRepository([]))

    async def handler(job: ScheduledJobTable) -> None:
        return None

    assert poller.register('a', handler) is poller
    with pytest.raises(ScheduleError):
        poller.register('a', handler)


def test_health_is_down_until_started() -> None:
    assert _poller(FakeRepository([])).check_health()['status'] == 'down'


# --------------------------------------------------------------------------- #
# Settings (SCHEDULE_* variables, same names / defaults as the JS twin)
# --------------------------------------------------------------------------- #


def test_settings_map_variables_unset_or_blank_means_default() -> None:
    config = ScheduleSettings(
        {
            'SCHEDULE_POLL_STRATEGY': 'adaptive',
            'SCHEDULE_BATCH_SIZE': '40',
            'SCHEDULE_CLAIM_TIMEOUT_MS': ' 60000 ',
            'SCHEDULE_RETRY_BACKOFF_MS': '1500.5',
            'SCHEDULE_MAX_RETRIES': '',
            'SCHEDULE_ENABLED': 'no',
        }
    ).schedule_config()
    assert config.poll_strategy == 'adaptive'
    assert config.batch_size == 40
    assert config.claim_timeout_ms == 60_000
    assert config.retry_backoff_ms == 1500.5
    assert config.max_retries == 3
    assert config.enabled is False
    assert ScheduleSettings({}).schedule_config().fixed_poll_interval_ms == 30_000
    assert ScheduleSettings({'SCHEDULE_BATCH_SIZE': '40'}).schedule_config(batch_size=3).batch_size == 3


@pytest.mark.parametrize(
    'env',
    [
        {'SCHEDULE_BATCH_SIZE': 'lots'},
        {'SCHEDULE_BATCH_SIZE': '2.5'},
        {'SCHEDULE_BATCH_SIZE': '0'},
        {'SCHEDULE_RETRY_BACKOFF_MS': 'nan'},
        {'SCHEDULE_POLL_STRATEGY': 'notify'},
        {'SCHEDULE_CLAIM_TIMEOUT_MS': '500'},
        {'SCHEDULE_MIN_POLL_INTERVAL_MS': '10', 'SCHEDULE_MAX_POLL_INTERVAL_MS': '5'},
        {'SCHEDULE_ENABLED': 'sometimes'},
    ],
)
def test_settings_fail_on_a_malformed_value(env: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ScheduleSettings(env).schedule_config()
