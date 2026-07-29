"""Dispatch/lifecycle tests for `SchedulerPoller` using in-memory fakes.

These exercise the poller's decision logic (channel vs callback dispatch,
reschedule-on-success, mark-failed-on-error) without a database or broker.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from db.models.resiliant import ScheduledJobTable
from foundation.resiliant.schedule import ScheduleConfig, ScheduleJobKind
from resiliant.schedule import SchedulerPoller


class FakeRepository:
    """Records mark_* calls; ignores the (unused) session argument."""

    def __init__(self) -> None:
        self.succeeded: list[tuple[str, datetime | None]] = []
        self.failed: list[tuple[str, str]] = []

    async def mark_succeeded(self, session: Any, job_id: str, *, next_run_at) -> None:
        self.succeeded.append((job_id, next_run_at))

    async def mark_failed(self, session: Any, job_id: str, error: str, *, next_run_at=None) -> None:
        self.failed.append((job_id, error))


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(self, *, channel, message, headers=None, ordering_key=None) -> None:
        self.published.append(
            {
                'channel': channel,
                'message': message,
                'headers': headers,
                'ordering_key': ordering_key,
            }
        )


def _job(**overrides: Any) -> ScheduledJobTable:
    base: dict[str, Any] = {
        'id': 'job-1',
        'job_name': 'charge',
        'kind': ScheduleJobKind.ONCE,
        'cron_expr': None,
        'interval_seconds': None,
        'channel': None,
        'event_type': None,
        'ordering_key': None,
        'payload': {'x': 1},
        'headers': {},
        'next_run_at': datetime(2026, 1, 1, 12, 0, 0),
    }
    base.update(overrides)
    return ScheduledJobTable(**base)


def _poller(repo: FakeRepository, publisher: FakePublisher | None = None) -> SchedulerPoller:
    return SchedulerPoller(
        config=ScheduleConfig(),
        session_factory=lambda: None,  # never used by _fire directly
        publisher=publisher,
        repository=repo,  # type: ignore[arg-type]
    )


async def test_once_job_publishes_to_channel_and_completes() -> None:
    repo, pub = FakeRepository(), FakePublisher()
    poller = _poller(repo, pub)
    job = _job(channel='billing.charge', ordering_key='u-1')

    await poller._fire(None, job)  # type: ignore[arg-type]

    assert pub.published == [
        {
            'channel': 'billing.charge',
            'message': {'x': 1},
            'headers': {},
            'ordering_key': 'u-1',
        }
    ]
    # ONCE -> no next run.
    assert repo.succeeded == [('job-1', None)]
    assert repo.failed == []


async def test_interval_job_reschedules() -> None:
    repo, pub = FakeRepository(), FakePublisher()
    poller = _poller(repo, pub)
    job = _job(
        kind=ScheduleJobKind.INTERVAL,
        interval_seconds=60,
        channel='ticks',
    )

    await poller._fire(None, job)  # type: ignore[arg-type]

    assert len(repo.succeeded) == 1
    job_id, next_run = repo.succeeded[0]
    assert job_id == 'job-1'
    assert next_run == datetime(2026, 1, 1, 12, 0, 0) + timedelta(seconds=60)


async def test_callback_dispatch_when_no_channel() -> None:
    repo = FakeRepository()
    poller = _poller(repo)
    seen: list[str] = []

    async def handler(job: ScheduledJobTable) -> None:
        seen.append(job.job_name)

    poller.register('charge', handler)
    await poller._fire(None, _job())  # type: ignore[arg-type]

    assert seen == ['charge']
    assert repo.succeeded == [('job-1', None)]


async def test_dispatch_failure_marks_failed() -> None:
    repo = FakeRepository()
    poller = _poller(repo)

    async def boom(job: ScheduledJobTable) -> None:
        raise RuntimeError('provider down')

    poller.register('charge', boom)
    await poller._fire(None, _job())  # type: ignore[arg-type]

    assert repo.succeeded == []
    assert len(repo.failed) == 1
    assert 'provider down' in repo.failed[0][1]


async def test_missing_target_marks_failed() -> None:
    repo = FakeRepository()
    poller = _poller(repo)  # no publisher, no callback registered

    await poller._fire(None, _job())  # type: ignore[arg-type]

    assert repo.succeeded == []
    assert len(repo.failed) == 1
