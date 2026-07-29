"""
Database-backed scheduler service (durable timers / schedules / cron).

Application-facing entry point for :mod:`foundation.resiliant.schedule`. Callers
create jobs inside their own business transaction so the timer commits
atomically with the domain write that requested it (e.g. "start a subscription"
and "schedule its first billing run" in one commit).

Example::

    schedule = ResiliantServiceFactory().get_schedule_service()

    async with session.begin():
        await subscription_repo.create(session, sub)
        await schedule.schedule_after(
            session,
            job_name="charge_subscription",
            delay_seconds=30 * 24 * 3600,          # 30 days — a durable sleep
            channel="billing.charge",
            payload={"subscription_id": sub.id},
        )
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from db.models.resiliant import ScheduledJobTable
from foundation import BaseService
from foundation.resiliant.schedule import (
    IScheduleService,
    ScheduleConfig,
    ScheduleJobKind,
    ScheduleJobStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ._recurrence import cron_next, utcnow_naive
from .schedule_repository import ScheduleRepository


class ScheduleService(IScheduleService, BaseService):
    """High-level API for creating and cancelling durable timers."""

    def __init__(
        self,
        config: ScheduleConfig,
        repository: ScheduleRepository | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.repository = repository or ScheduleRepository(config)

    async def schedule_once(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        run_at: datetime,
        channel: Optional[str] = None,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        ordering_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> ScheduledJobTable:
        """Fire ``job_name`` exactly once at ``run_at`` (a durable sleep)."""
        return await self._create(
            session,
            job_name=job_name,
            kind=ScheduleJobKind.ONCE,
            next_run_at=_as_naive_utc(run_at),
            channel=channel,
            event_type=event_type,
            payload=payload,
            ordering_key=ordering_key,
            headers=headers,
            max_retries=max_retries,
        )

    async def schedule_after(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        delay_seconds: float,
        **kwargs: Any,
    ) -> ScheduledJobTable:
        """Convenience: :meth:`schedule_once` at ``now + delay_seconds``."""
        run_at = utcnow_naive() + timedelta(seconds=delay_seconds)
        return await self.schedule_once(
            session, job_name=job_name, run_at=run_at, **kwargs
        )

    async def schedule_interval(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        interval_seconds: int,
        start_at: Optional[datetime] = None,
        max_runs: Optional[int] = None,
        channel: Optional[str] = None,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        ordering_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> ScheduledJobTable:
        """Fire every ``interval_seconds`` (recurring timer)."""
        if interval_seconds <= 0:
            raise ValueError('interval_seconds must be positive')
        first = _as_naive_utc(start_at) if start_at else (
            utcnow_naive() + timedelta(seconds=interval_seconds)
        )
        return await self._create(
            session,
            job_name=job_name,
            kind=ScheduleJobKind.INTERVAL,
            next_run_at=first,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            channel=channel,
            event_type=event_type,
            payload=payload,
            ordering_key=ordering_key,
            headers=headers,
            max_retries=max_retries,
        )

    async def schedule_cron(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        cron_expr: str,
        max_runs: Optional[int] = None,
        channel: Optional[str] = None,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        ordering_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> ScheduledJobTable:
        """Fire on a cron expression (needs the ``croniter`` dependency)."""
        # Validates the expression eagerly and computes the first fire time.
        first = cron_next(cron_expr, utcnow_naive())
        return await self._create(
            session,
            job_name=job_name,
            kind=ScheduleJobKind.CRON,
            next_run_at=first,
            cron_expr=cron_expr,
            max_runs=max_runs,
            channel=channel,
            event_type=event_type,
            payload=payload,
            ordering_key=ordering_key,
            headers=headers,
            max_retries=max_retries,
        )

    async def cancel(self, session: AsyncSession, job_id: str) -> None:
        """Cancel a pending job."""
        await self.repository.cancel(session, job_id)

    async def exists_active(self, session: AsyncSession, job_name: str) -> bool:
        """Return ``True`` if a non-terminal job with ``job_name`` exists.

        Lets callers define a recurring job once (idempotent across restarts).
        """
        return await self.repository.get_active_by_name(session, job_name) is not None

    async def get_stats(self, session: AsyncSession) -> dict:
        """Return counters describing the scheduler backlog."""
        return await self.repository.get_stats(session)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _create(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        kind: ScheduleJobKind,
        next_run_at: datetime,
        interval_seconds: Optional[int] = None,
        cron_expr: Optional[str] = None,
        max_runs: Optional[int] = None,
        channel: Optional[str] = None,
        event_type: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        ordering_key: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None,
    ) -> ScheduledJobTable:
        job = ScheduledJobTable(
            job_name=job_name,
            kind=kind,
            cron_expr=cron_expr,
            interval_seconds=interval_seconds,
            channel=channel,
            event_type=event_type,
            ordering_key=ordering_key,
            payload=payload or {},
            headers=headers or {},
            next_run_at=next_run_at,
            status=ScheduleJobStatus.SCHEDULED,
            run_count=0,
            max_runs=max_runs,
            attempts=0,
            max_retries=max_retries if max_retries is not None else self.config.max_retries,
        )
        saved = await self.repository.save(session, job)
        self.logger.debug(
            'Scheduled job %s (kind=%s) at %s (id=%s)',
            job_name,
            kind,
            next_run_at,
            saved.id,
        )
        return saved


def _as_naive_utc(dt: datetime) -> datetime:
    """Normalise an aware/naive datetime to naive UTC for storage."""
    if dt.tzinfo is not None:
        from datetime import UTC

        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt
