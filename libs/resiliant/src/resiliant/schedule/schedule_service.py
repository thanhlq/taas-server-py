"""
Scheduling API (port of ``@taas/resiliant`` ``schedule/service.ts``) — durable timers
created inside the caller's transaction, so the timer commits atomically with the
change that asked for it::

    async with session.begin():
        await subscriptions.create(session, sub)
        await schedule.schedule_after(
            session, job_name='charge_subscription', delay_ms=30 * DAY_MS,
            channel='billing.charge', payload={'subscription_id': sub.id},
        )

``unique_key`` makes a definition idempotent across restarts and replicas ("ensure
the nightly job exists"): a second create returns ``None``. Nothing here commits.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from foundation import BaseService
from foundation.resiliant.schedule import (
    IScheduleService,
    ScheduleConfig,
    ScheduleError,
    ScheduleJobKind,
)
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import ScheduledJobTable

from .cron import next_cron_time, parse_cron
from .schedule_repository import ScheduleRepository
from .schedule_settings import get_schedule_config

Clock = Callable[[], datetime]
"""Returns the current time as an aware UTC datetime (seam for tests)."""


def system_clock() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Aware UTC; a naive datetime is taken as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ScheduleService(IScheduleService, BaseService):
    """Create, cancel and inspect durable timers (``IScheduleService``)."""

    def __init__(
        self,
        config: ScheduleConfig | None = None,
        repository: ScheduleRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        super().__init__()
        self.config = config or get_schedule_config()
        self.repository = repository or ScheduleRepository(self.config)
        self.clock: Clock = clock or system_clock

    def now(self) -> datetime:
        return _as_utc(self.clock())

    async def schedule_once(
        self, session: AsyncSession, *, job_name: str, run_at: datetime, **target: Any
    ) -> ScheduledJobTable | None:
        """Fire ``job_name`` once at ``run_at`` (a durable sleep)."""
        return await self._create(
            session, job_name=job_name, kind=ScheduleJobKind.ONCE, next_run_at=run_at, **target
        )

    async def schedule_after(
        self, session: AsyncSession, *, job_name: str, delay_ms: float, **target: Any
    ) -> ScheduledJobTable | None:
        """:meth:`schedule_once` at ``now + delay_ms``."""
        if isinstance(delay_ms, bool) or not isinstance(delay_ms, int | float) or not delay_ms >= 0:  # pyright: ignore[reportUnnecessaryIsInstance] - runtime validation
            raise ScheduleError(f'delay_ms must be >= 0, got {delay_ms}')
        run_at = self.now() + timedelta(milliseconds=delay_ms)
        return await self.schedule_once(session, job_name=job_name, run_at=run_at, **target)

    async def schedule_interval(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        interval_seconds: int,
        start_at: datetime | None = None,
        max_runs: int | None = None,
        **target: Any,
    ) -> ScheduledJobTable | None:
        """Fire every ``interval_seconds``; the first fire is ``start_at`` (default ``now + interval``)."""
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or interval_seconds <= 0:  # pyright: ignore[reportUnnecessaryIsInstance] - runtime validation
            raise ScheduleError(f'interval_seconds must be a positive integer, got {interval_seconds}')
        first = start_at if start_at is not None else self.now() + timedelta(seconds=interval_seconds)
        return await self._create(
            session,
            job_name=job_name,
            kind=ScheduleJobKind.INTERVAL,
            next_run_at=first,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
            **target,
        )

    async def schedule_cron(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        cron_expr: str,
        max_runs: int | None = None,
        **target: Any,
    ) -> ScheduledJobTable | None:
        """Fire on a 5-field UTC cron expression; first fire = next occurrence after now."""
        # Parse eagerly: an invalid expression fails the caller's transaction, not the poller later.
        schedule = parse_cron(cron_expr)
        return await self._create(
            session,
            job_name=job_name,
            kind=ScheduleJobKind.CRON,
            next_run_at=next_cron_time(schedule, self.now()),
            cron_expr=schedule.expression,
            max_runs=max_runs,
            **target,
        )

    async def cancel(self, session: AsyncSession, job_id: int) -> bool:
        """Cancel an active job; ``False`` when it was not active. A cancel wins over an in-flight fire."""
        return await self.repository.cancel(session, job_id)

    async def exists_active(self, session: AsyncSession, job_name: str) -> bool:
        """``True`` if a scheduled / running job with ``job_name`` exists."""
        return await self.repository.get_active_by_name(session, job_name) is not None

    async def stats(self, session: AsyncSession) -> dict[str, int]:
        """Counts per status plus ``oldest_overdue_ms``."""
        return await self.repository.stats(session)

    async def _create(
        self,
        session: AsyncSession,
        *,
        job_name: str,
        kind: ScheduleJobKind,
        next_run_at: datetime,
        max_retries: int | None = None,
        max_runs: int | None = None,
        **fields: Any,
    ) -> ScheduledJobTable | None:
        if not job_name:
            raise ScheduleError('a scheduled job needs a job_name')
        if not isinstance(next_run_at, datetime):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime validation
            raise ScheduleError(f'job {job_name}: invalid run time')
        if max_runs is not None and (
            isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 1  # pyright: ignore[reportUnnecessaryIsInstance]
        ):
            raise ScheduleError(f'job {job_name}: max_runs must be >= 1')
        job = await self.repository.insert(
            session,
            job_name=job_name,
            kind=kind,
            next_run_at=_as_utc(next_run_at),
            max_runs=max_runs,
            max_retries=self.config.max_retries if max_retries is None else max_retries,
            **fields,
        )
        if job is None:
            self.logger.debug('job %s: unique_key %s already active', job_name, fields.get('unique_key'))
        return job


__all__ = ['Clock', 'ScheduleService', 'system_clock']
