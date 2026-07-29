"""Tests for `ResilienceVisibilityService` using a fake session.

The service only issues grouped ``SELECT status, count(*)`` queries, so a fake
session that returns queued ``(status, count)`` rows exercises the aggregation
and the ``healthy`` heuristic without a database.
"""

from __future__ import annotations

from typing import Any

from foundation.resiliant.dlq import DLQStatus
from foundation.resiliant.outbox import OutboxStatus
from foundation.resiliant.saga import SagaStatus
from foundation.resiliant.schedule import ScheduleJobStatus
from resiliant.visibility import ResilienceVisibilityService


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, int]]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    """Returns queued results in call order (outbox, dlq, saga, schedule)."""

    def __init__(self, results: list[list[tuple[Any, int]]]) -> None:
        self._queue = list(results)

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        return _FakeResult(self._queue.pop(0))


async def test_snapshot_reports_all_statuses_and_healthy() -> None:
    session = FakeSession(
        [
            [(OutboxStatus.PUBLISHED, 100), (OutboxStatus.PENDING, 2)],  # outbox
            [],  # dlq — empty
            [(SagaStatus.RUNNING, 3), (SagaStatus.COMPLETED, 40)],  # saga
            [(ScheduleJobStatus.SCHEDULED, 5)],  # schedule
        ]
    )

    snap = await ResilienceVisibilityService().snapshot(session)  # type: ignore[arg-type]

    assert snap['healthy'] is True
    # Every status is present (zero-filled), not just the ones with rows.
    assert snap['outbox'][OutboxStatus.PENDING.value] == 2
    assert snap['outbox'][OutboxStatus.DEAD_LETTER.value] == 0
    assert snap['dlq'][DLQStatus.PENDING.value] == 0
    assert snap['saga'][SagaStatus.RUNNING.value] == 3
    assert snap['schedule'][ScheduleJobStatus.SCHEDULED.value] == 5


async def test_snapshot_unhealthy_when_dlq_pending() -> None:
    session = FakeSession(
        [
            [],  # outbox
            [(DLQStatus.PENDING, 1)],  # dlq has a poison message
            [],  # saga
            [],  # schedule
        ]
    )

    snap = await ResilienceVisibilityService().snapshot(session)  # type: ignore[arg-type]
    assert snap['healthy'] is False
    assert snap['dlq'][DLQStatus.PENDING.value] == 1


async def test_snapshot_unhealthy_when_saga_failed() -> None:
    session = FakeSession(
        [
            [],
            [],
            [(SagaStatus.FAILED, 1)],  # compensation itself failed
            [],
        ]
    )

    snap = await ResilienceVisibilityService().snapshot(session)  # type: ignore[arg-type]
    assert snap['healthy'] is False
