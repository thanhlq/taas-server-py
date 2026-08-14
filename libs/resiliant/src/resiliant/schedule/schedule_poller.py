"""
Scheduler poller — the durable-timer relay engine.

Pure poller (same contract as :class:`resiliant.outbox.OutboxPoller`): it owns
the polling loop only; a worker application constructs it and drives it via
:meth:`run` / :meth:`stop`. It reuses the outbox relay's proven mechanics —
``FOR UPDATE SKIP LOCKED`` claiming, staggered concurrent workers, adaptive
back-off, and stale-claim recovery — applied to time-based jobs.

When a job is due it is *dispatched* in one of two ways:

* **channel** — if the job has a ``channel``, its payload is published to the
  broker (so the fire becomes a normal Kafka event other services consume);
* **callback** — otherwise the callback registered under ``job_name`` via
  :meth:`register` is invoked in-process.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Optional

from db.models.resiliant import ScheduledJobTable
from foundation.messaging.types import MessagingServiceT
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.schedule import ScheduleConfig
from foundation.state import get_service
from sqlalchemy.ext.asyncio import AsyncSession

from ._recurrence import compute_next_run
from .schedule_repository import ScheduleRepository

JobCallback = Callable[[ScheduledJobTable], Awaitable[None]]


class SchedulerPoller:
    """Adaptive poller that fires due scheduled jobs."""

    def __init__(
        self,
        config: ScheduleConfig,
        session_factory: Callable[[], AsyncSession],
        publisher: Optional[MessagingServiceT] = None,
        repository: Optional[ScheduleRepository] = None,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self._publisher = publisher
        self.repository = repository or ScheduleRepository(config)
        self.logger = LogFactory().get_logger(self.__class__.__name__)

        self._dispatchers: dict[str, JobCallback] = {}
        self._current_interval_ms = float(config.initial_poll_interval_ms)

        self._running = False
        self._worker_tasks: list[asyncio.Task] = []
        self._maintenance_task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()

    @property
    def publisher(self) -> MessagingServiceT:
        if self._publisher is None:
            self._publisher = get_service(MessagingServiceT)
        return self._publisher

    def register(self, job_name: str, callback: JobCallback) -> None:
        """Register an in-process handler for jobs with no ``channel``."""
        self._dispatchers[job_name] = callback

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        if self._running:
            self.logger.warning('Scheduler poller already running')
            return
        self._running = True
        self.logger.info(
            '⏰ Starting scheduler poller with %s workers (strategy=%s)',
            self.config.concurrent_workers,
            self.config.poll_strategy,
        )
        for i in range(self.config.concurrent_workers):
            self._worker_tasks.append(asyncio.create_task(self._worker_loop(i)))
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

    async def run(self) -> None:
        """Start and block until stopped."""
        await self.start()
        tasks = [*self._worker_tasks]
        if self._maintenance_task:
            tasks.append(self._maintenance_task)
        if not tasks:
            return
        try:
            await asyncio.gather(*tasks, return_exceptions=False)
        except asyncio.CancelledError:
            self.logger.info('Scheduler poller run cancelled')
            raise

    async def stop(self) -> None:
        if not self._running:
            return
        self.logger.info('Stopping scheduler poller...')
        self._running = False
        self._wake_event.set()
        for task in self._worker_tasks:
            task.cancel()
        if self._maintenance_task:
            self._maintenance_task.cancel()
        tasks = [*self._worker_tasks]
        if self._maintenance_task:
            tasks.append(self._maintenance_task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._worker_tasks.clear()
        self._maintenance_task = None
        self.logger.info('Scheduler poller stopped')

    def wake(self) -> None:
        """Trigger an immediate poll cycle (e.g. after inserting a due job)."""
        self._wake_event.set()

    # ------------------------------------------------------------------ #
    # Worker loop
    # ------------------------------------------------------------------ #

    async def _worker_loop(self, worker_id: int) -> None:
        self.logger.info('Scheduler worker %s started', worker_id)
        if self.config.concurrent_workers > 1:
            stagger = (self.config.initial_poll_interval_ms / 1000.0) * (
                worker_id / self.config.concurrent_workers
            )
            if stagger > 0:
                await asyncio.sleep(stagger)

        while self._running:
            try:
                fired = await self._poll_and_fire(worker_id)
                drain_threshold = max(
                    1, int(self.config.batch_size * self.config.drain_threshold_ratio)
                )
                if fired >= drain_threshold:
                    continue
                await self._sleep(self._next_sleep(fired) / 1000.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001 - loop must not die
                self.logger.error(
                    'Scheduler worker %s error: %s', worker_id, exc, exc_info=True
                )
                await asyncio.sleep(1.0)
        self.logger.info('Scheduler worker %s stopped', worker_id)

    def _next_sleep(self, fired: int) -> float:
        cfg = self.config
        if cfg.poll_strategy == 'fixed':
            self._current_interval_ms = float(cfg.fixed_poll_interval_ms)
            return self._current_interval_ms
        # adaptive (decorrelated jitter)
        if fired > 0:
            self._current_interval_ms = float(cfg.min_poll_interval_ms)
        else:
            upper = min(
                float(cfg.max_poll_interval_ms),
                self._current_interval_ms * cfg.backoff_growth_factor,
            )
            lower = float(cfg.min_poll_interval_ms)
            self._current_interval_ms = random.uniform(lower, max(lower, upper))
        return self._current_interval_ms

    async def _sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=seconds)
            self._wake_event.clear()
        except TimeoutError:
            pass

    async def _poll_and_fire(self, worker_id: int) -> int:
        async with self.session_factory() as session:
            jobs = await self.repository.fetch_due_batch(session, self.config.batch_size)
            if jobs:
                self.logger.debug('Worker %s claimed %s due job(s)', worker_id, len(jobs))
            for job in jobs:
                await self._fire(session, job)
            return len(jobs)

    async def _fire(self, session: AsyncSession, job: ScheduledJobTable) -> None:
        """Dispatch one due job, then reschedule / complete it."""
        try:
            await self._dispatch(job)
        except Exception as exc:  # noqa: BLE001 - dispatch failures are expected
            await self.repository.mark_failed(
                session, job.id, f'{type(exc).__name__}: {exc}'
            )
            self.logger.error(
                'Scheduled job %s (%s) dispatch failed: %s',
                job.id,
                job.job_name,
                exc,
            )
            return

        next_run: datetime | None = compute_next_run(
            kind=job.kind,
            from_time=job.next_run_at,
            interval_seconds=job.interval_seconds,
            cron_expr=job.cron_expr,
        )
        await self.repository.mark_succeeded(session, job.id, next_run_at=next_run)

    async def _dispatch(self, job: ScheduledJobTable) -> None:
        """Deliver a due job to its channel or its registered callback."""
        if job.channel:
            await self.publisher.publish(
                channel=job.channel,
                message=job.payload or {},
                headers=job.headers or {},
                ordering_key=job.ordering_key,
            )
            return
        callback = self._dispatchers.get(job.job_name)
        if callback is None:
            raise RuntimeError(
                f'No channel and no registered callback for job_name={job.job_name!r}'
            )
        await callback(job)

    async def _maintenance_loop(self) -> None:
        await asyncio.sleep(30)
        while self._running:
            try:
                async with self.session_factory() as session:
                    await self.repository.reset_stale_running(session)
                    if self.config.enable_metrics:
                        stats = await self.repository.get_stats(session)
                        self.logger.info('Scheduler stats: %s', stats)
                await asyncio.sleep(self.config.metrics_log_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self.logger.error('Scheduler maintenance error: %s', exc, exc_info=True)
                await asyncio.sleep(60)
