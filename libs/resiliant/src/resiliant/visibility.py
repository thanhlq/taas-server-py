"""
Resilience visibility — the "is anything stuck?" read surface.

This is the pattern-stack equivalent of the Temporal UI: instead of a bespoke
dashboard, one aggregation query over the resilience tables answers *"how many
sagas are running / retrying, is the outbox draining, is the DLQ empty, are any
timers overdue?"*. Expose :meth:`ResilienceVisibilityService.snapshot` behind a
``GET /health/resilience`` route (or the worker health server) and point Grafana
at the same counts.
"""

from __future__ import annotations

from typing import Any

from db.models.resiliant import (
    DLQEventTable,
    OutboxEventTable,
    SagaStateTable,
    ScheduledJobTable,
)
from foundation import BaseService
from foundation.resiliant.dlq import DLQStatus
from foundation.resiliant.outbox import OutboxStatus
from foundation.resiliant.saga import SagaStatus
from foundation.resiliant.schedule import ScheduleJobStatus
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class ResilienceVisibilityService(BaseService):
    """Aggregates per-status counts across all resilience tables."""

    async def snapshot(self, session: AsyncSession) -> dict[str, Any]:
        """Return a single health snapshot of the resilience subsystem.

        The ``healthy`` flag is a cheap alert heuristic: nothing dead-lettered
        and no saga that failed its own compensation.
        """
        outbox = await self._counts(
            session, OutboxEventTable, OutboxEventTable.status, OutboxStatus
        )
        dlq = await self._counts(
            session, DLQEventTable, DLQEventTable.status, DLQStatus
        )
        saga = await self._counts(
            session, SagaStateTable, SagaStateTable.status, SagaStatus
        )
        schedule = await self._counts(
            session, ScheduledJobTable, ScheduledJobTable.status, ScheduleJobStatus
        )

        healthy = (
            outbox.get(OutboxStatus.DEAD_LETTER.value, 0) == 0
            and dlq.get(DLQStatus.PENDING.value, 0) == 0
            and saga.get(SagaStatus.FAILED.value, 0) == 0
            and schedule.get(ScheduleJobStatus.FAILED.value, 0) == 0
        )

        return {
            'healthy': healthy,
            'outbox': outbox,
            'dlq': dlq,
            'saga': saga,
            'schedule': schedule,
        }

    @staticmethod
    async def _counts(
        session: AsyncSession,
        table: Any,
        status_col: Any,
        status_enum: Any,
    ) -> dict[str, int]:
        """Group-by-status counter that always lists every status (0 if absent)."""
        result = await session.execute(
            select(status_col, func.count()).select_from(table).group_by(status_col)
        )
        found = dict(result)
        return {status.value: found.get(status, 0) for status in status_enum}


__all__ = ['ResilienceVisibilityService']
