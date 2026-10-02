"""
The scheduler loop — fires due jobs (port of ``@taas/resiliant`` ``schedule/poller.ts``).

A due job goes to its ``channel`` through the publisher when it has one (the fire
becomes an ordinary broker event), otherwise to the callback registered under its
``job_name``. Several pollers (replicas) share one table safely: claims use
``SKIP LOCKED`` and a lease, outcomes are compare-and-set.

:meth:`SchedulerPoller.process_batch` is one step (tests, or an engine with its own
loop); :meth:`start` / :meth:`stop` (or :meth:`run`) run it continuously with the
configured poll strategy, plus a maintenance tick that reschedules stale RUNNING
jobs (``claim_timeout_ms``) and logs stats.

Transactions: the claim commits on its own (the lease) before any job fires; each
outcome is written in its own short transaction.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from foundation.observability.log_factory import LogFactory
from foundation.resiliant.schedule import ScheduleConfig, ScheduleError, ScheduleJobStatus
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models import ScheduledJobTable
from resiliant.sql import describe_error, next_idle_sleep_ms

from .recurrence import compute_next_run
from .schedule_repository import ScheduleRepository
from .schedule_service import Clock, ScheduleService

ScheduledJobCallback = Callable[[ScheduledJobTable], Awaitable[None]]

_UNHEALTHY_AFTER_SECONDS = 5 * 60


@dataclass(slots=True)
class SchedulePollResult:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0


class _Waker:
    """A sleep that :meth:`wake` ends early; woken with nobody sleeping, the next sleep returns at once."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    async def sleep(self, ms: float) -> None:
        if self._event.is_set():
            self._event.clear()
            return
        if ms <= 0:
            return
        try:
            await asyncio.wait_for(self._event.wait(), timeout=ms / 1000)
            self._event.clear()
        except TimeoutError:
            pass

    def wake(self) -> None:
        self._event.set()


class SchedulerPoller:
    """Fires due scheduled jobs (``SchedulePoller`` of the JS twin)."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        service: ScheduleService | None = None,
        config: ScheduleConfig | None = None,
        publisher: Any | None = None,
        clock: Clock | None = None,
    ) -> None:
        """
        Args:
            session_factory: new ``AsyncSession`` per step (the pool).
            service: the schedule service (its config, repository and clock); built from
                ``config`` / ``clock`` when omitted.
            publisher: needed for jobs with a ``channel`` (``MessagingServiceT``-like
                ``publish(channel=, message=, ordering_key=, headers=)``).
        """
        self.service = service or ScheduleService(config=config, clock=clock)
        self.session_factory = session_factory
        self.publisher = publisher
        self.logger = LogFactory().get_logger(self.__class__.__name__)
        self._callbacks: dict[str, ScheduledJobCallback] = {}
        self._wakers: list[_Waker] = []
        self._loops: list[asyncio.Task[None]] = []
        self._running = False
        self._last_error: str | None = None
        self._last_success_at = time.monotonic()

    @property
    def config(self) -> ScheduleConfig:
        return self.service.config

    @property
    def repository(self) -> ScheduleRepository:
        return self.service.repository

    def register(self, job_name: str, callback: ScheduledJobCallback) -> SchedulerPoller:
        """In-process handler for jobs without a channel. Register before :meth:`start`."""
        if job_name in self._callbacks:
            raise ScheduleError(f'a callback is already registered for job "{job_name}"')
        self._callbacks[job_name] = callback
        return self

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        c = self.config
        self.logger.info('⏰ scheduler: %s worker(s), strategy %s', c.concurrent_workers, c.poll_strategy)
        for i in range(c.concurrent_workers):
            waker = _Waker()
            self._wakers.append(waker)
            self._loops.append(asyncio.create_task(self._worker_loop(i, waker)))
        maintenance = _Waker()
        self._wakers.append(maintenance)
        self._loops.append(asyncio.create_task(self._maintenance_loop(maintenance)))

    async def run(self) -> None:
        """:meth:`start`, then block until stopped (a cancelled ``run`` stops the loops)."""
        await self.start()
        try:
            await asyncio.gather(*self._loops)
        except asyncio.CancelledError:
            for task in self._loops:
                task.cancel()
            raise

    async def stop(self) -> None:
        """Let in-flight batches finish, then return."""
        if not self._running:
            return
        self._running = False
        self.wake()
        await asyncio.gather(*self._loops, return_exceptions=True)
        self._loops = []
        self._wakers.clear()
        self.logger.info('scheduler stopped')

    def wake(self) -> None:
        """Poll now (e.g. right after scheduling a job due immediately)."""
        for waker in self._wakers:
            waker.wake()

    def check_health(self) -> dict[str, Any]:
        """``{'status': 'up' | 'down', 'reason'?, 'details'}``."""
        details = {'running': self._running, 'last_error': self._last_error, 'callbacks': list(self._callbacks)}
        if not self._running:
            return {'status': 'down', 'reason': 'scheduler not running', 'details': details}
        if self._last_error and time.monotonic() - self._last_success_at > _UNHEALTHY_AFTER_SECONDS:
            return {'status': 'down', 'reason': f'scheduler failing: {self._last_error}', 'details': details}
        return {'status': 'up', 'details': details}

    # ------------------------------------------------------------------ #
    # One step
    # ------------------------------------------------------------------ #

    async def process_batch(self) -> SchedulePollResult:
        """One step: lease due jobs (committed), fire each, record the outcome."""
        repository = self.service.repository
        async with self.session_factory() as session:
            async with session.begin():
                jobs = await repository.claim_due(session, self.config.batch_size)
            result = SchedulePollResult(claimed=len(jobs))
            for job in jobs:
                try:
                    await self._dispatch(job)
                except Exception as error:  # noqa: BLE001 - a failing job is an outcome
                    result.failed += 1
                    retry_at = self.service.now() + timedelta(milliseconds=self.config.retry_backoff_ms)
                    async with session.begin():
                        status = await repository.mark_failed(session, job, describe_error(error), retry_at)
                    how = (
                        f'FAILED after {job.attempts + 1} attempts'
                        if status == ScheduleJobStatus.FAILED
                        else f'retry at {retry_at.isoformat()}'
                    )
                    self.logger.error('job #%s %s failed (%s): %s', job.id, job.job_name, how, describe_error(error))
                    continue
                next_run: datetime | None
                try:
                    next_run = compute_next_run(
                        kind=job.kind,
                        scheduled_at=job.next_run_at,
                        now=self.service.now(),
                        interval_seconds=job.interval_seconds,
                        cron_expr=job.cron_expr,
                    )
                except Exception as error:  # noqa: BLE001
                    # The job fired; only its recurrence is broken - stop it rather than fire it again and again.
                    self.logger.error(
                        'job #%s %s: cannot compute the next run: %s', job.id, job.job_name, describe_error(error)
                    )
                    next_run = None
                async with session.begin():
                    recorded = await repository.mark_succeeded(session, job, next_run)
                if recorded:
                    result.succeeded += 1
                else:
                    self.logger.warning(
                        'job #%s %s changed while firing (cancelled?); outcome not recorded', job.id, job.job_name
                    )
        return result

    async def _dispatch(self, job: ScheduledJobTable) -> None:
        if job.channel:
            if self.publisher is None:
                raise ScheduleError(f'job {job.job_name} publishes to {job.channel} but the poller has no publisher')
            await self.publisher.publish(
                channel=job.channel,
                message=job.payload or {},
                ordering_key=job.ordering_key,
                headers=job.headers or None,
            )
            return
        callback = self._callbacks.get(job.job_name)
        if callback is None:
            raise ScheduleError(f'job {job.job_name} has no channel and no registered callback')
        await callback(job)

    # ------------------------------------------------------------------ #
    # Loops
    # ------------------------------------------------------------------ #

    async def _worker_loop(self, index: int, waker: _Waker) -> None:
        c = self.config
        sleep_ms = float(c.initial_poll_interval_ms)
        if c.concurrent_workers > 1 and index > 0:
            await waker.sleep(c.initial_poll_interval_ms * index / c.concurrent_workers)
        drain_at = max(1, math.floor(c.batch_size * c.drain_threshold_ratio))
        while self._running:
            try:
                result = await self.process_batch()
                self._last_error = None
                self._last_success_at = time.monotonic()
                if result.claimed >= drain_at:
                    continue
                sleep_ms = next_idle_sleep_ms(
                    c.poll_strategy,
                    fixed_ms=c.fixed_poll_interval_ms,
                    min_ms=c.min_poll_interval_ms,
                    max_ms=c.max_poll_interval_ms,
                    growth_factor=c.backoff_growth_factor,
                    previous_ms=sleep_ms,
                    found=result.claimed,
                )
                await waker.sleep(sleep_ms)
            except Exception as error:  # noqa: BLE001 - the loop must not die
                self._last_error = describe_error(error)
                self.logger.error('scheduler worker %s: %s', index, self._last_error)
                await waker.sleep(1000)

    async def _maintenance_loop(self, waker: _Waker) -> None:
        c = self.config
        repository = self.service.repository
        while self._running:
            await waker.sleep(min(c.claim_timeout_ms, c.metrics_log_interval_ms))
            if not self._running:
                return
            try:
                async with self.session_factory() as session:
                    async with session.begin():
                        reset = await repository.reset_stale(session, c.claim_timeout_ms)
                    if reset > 0:
                        self.logger.warning('scheduler: rescheduled %s job(s) left RUNNING by a crashed poller', reset)
                    if c.enable_metrics:
                        async with session.begin():
                            stats = await repository.stats(session)
                        self.logger.info('scheduler: %s', stats)
            except Exception as error:  # noqa: BLE001
                self.logger.warning('scheduler maintenance failed: %s', describe_error(error))


__all__ = ['ScheduledJobCallback', 'SchedulePollResult', 'SchedulerPoller']
