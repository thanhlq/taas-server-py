"""
Resilience visibility — one snapshot over every resiliant table (twin of
``ResilienceVisibilityService`` of ``@taas/resiliant``): is each outbox draining,
is anything dead-lettered, did a saga fail its own compensation, are timers
overdue. Serve it from ``/health/resilience`` and alert on ``healthy: false``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from foundation.resiliant.saga import SagaStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import SagaStateTable
from resiliant.outbox.outbox_repository import OutboxRepository
from resiliant.outbox.outbox_settings import get_outbox_config
from resiliant.outbox.registry import outbox_definitions


@dataclass(frozen=True, slots=True)
class ResilienceThresholds:
    max_outbox_lag_ms: int = 60_000
    """An outbox whose oldest claimable record is older than this is stuck."""
    max_schedule_overdue_ms: int = 300_000
    """A timer overdue by more than this is stuck."""


class ResilienceVisibilityService:
    def __init__(
        self,
        *,
        dlq: Any = None,
        schedule: Any = None,
        thresholds: ResilienceThresholds | None = None,
    ) -> None:
        self._dlq = dlq
        self._schedule = schedule
        self.thresholds = thresholds or ResilienceThresholds()

    def _services(self) -> tuple[Any, Any]:
        if self._dlq is None or self._schedule is None:
            from resiliant import ResiliantServiceFactory

            factory = ResiliantServiceFactory()
            self._dlq = self._dlq or factory.get_dlq_service()
            self._schedule = self._schedule or factory.get_schedule_service()
        return self._dlq, self._schedule

    @staticmethod
    async def _saga_stats(session: AsyncSession) -> dict[str, int]:
        rows = await session.execute(
            select(SagaStateTable.status, func.count()).group_by(SagaStateTable.status)
        )
        found = {
            str(getattr(status, 'value', status)): int(count) for status, count in rows
        }
        return {status.value: found.get(status.value, 0) for status in SagaStatus}

    async def snapshot(self, session: AsyncSession) -> dict[str, Any]:
        dlq_service, schedule_service = self._services()
        outboxes: list[dict[str, Any]] = []
        for definition in outbox_definitions():
            repository = OutboxRepository(
                definition.model, definition.config or get_outbox_config()
            )
            stats = await repository.stats(session)
            outboxes.append(
                {'outbox': definition.name, 'table': repository.table_name, **stats}
            )
        dlq = await dlq_service.stats(session)
        saga = await self._saga_stats(session)
        schedule = await schedule_service.stats(session)

        t = self.thresholds
        problems: list[str] = []
        for o in outboxes:
            dead = o['counts'].get('dead_letter', 0)
            if dead > 0:
                problems.append(f'outbox {o["outbox"]}: {dead} dead-lettered')
            lag = o['oldest_pending_age_ms']
            if lag is not None and lag > t.max_outbox_lag_ms:
                problems.append(
                    f'outbox {o["outbox"]}: oldest record waiting {round(lag / 1000)}s'
                )
        waiting = dlq.get('pending', 0) + dlq.get('approved', 0)
        if waiting > 0:
            problems.append(f'dlq: {waiting} awaiting retry')
        if dlq.get('abandoned', 0) > 0:
            problems.append(f'dlq: {dlq["abandoned"]} abandoned')
        if saga.get('failed', 0) > 0:
            problems.append(f'saga: {saga["failed"]} failed compensation')
        if schedule.get('failed', 0) > 0:
            problems.append(f'schedule: {schedule["failed"]} failed jobs')
        overdue = schedule.get('oldest_overdue_ms', 0) or 0
        if overdue > t.max_schedule_overdue_ms:
            problems.append(f'schedule: a job is overdue by {round(overdue / 1000)}s')
        return {
            'healthy': not problems,
            'problems': problems,
            'outboxes': outboxes,
            'dlq': dlq,
            'saga': saga,
            'schedule': schedule,
            'taken_at': datetime.now(UTC).isoformat(),
        }


__all__ = ['ResilienceThresholds', 'ResilienceVisibilityService']
