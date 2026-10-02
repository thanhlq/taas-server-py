"""
Outbox poller — loops :class:`OutboxProcessor` steps over ONE outbox table (same loop
as ``OutboxPoller`` of ``@taas/resiliant``).

Pure poller: no process lifecycle, health endpoint or signal handling — a worker app
(``apps/outbox_worker``) builds one per outbox and drives :meth:`run` / :meth:`stop`.

* ``concurrent_workers`` loops (rows split by SKIP LOCKED), staggered at start;
* a poll that claimed ``>= batch_size × drain_threshold_ratio`` rows polls again at once;
* otherwise it sleeps: ``fixed``, or decorrelated jitter (``adaptive`` / ``notify``);
  while the target circuit is not closed it sleeps at least the cool-down (capped);
* ``notify``: a dedicated connection ``LISTEN``s on ``notify_channel`` (writers ``NOTIFY``
  on commit) and wakes the loops; ``wake()`` does the same in-process;
* metrics + backlog stats are logged every ``metrics_log_interval_ms``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from foundation.cli import cli
from foundation.messaging.types import MessagingServiceT
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.outbox import IOutboxDispatcher, OutboxConfig
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models.outbox import MessagingOutboxTable
from resiliant.sql import describe_error, next_idle_sleep_ms

from .dispatchers import default_dispatchers
from .outbox_processor import OutboxProcessor
from .outbox_repository import OutboxRepository

ERROR_PAUSE_SECONDS = 1.0


class _Waker:
    """An interruptible sleep (``Waker`` of ``@taas/resiliant`` runtime)."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def wake(self) -> None:
        self._event.set()

    async def sleep(self, ms: float) -> None:
        if ms <= 0:
            return
        try:
            await asyncio.wait_for(self._event.wait(), timeout=ms / 1000)
        except TimeoutError:
            pass
        finally:
            self._event.clear()


def _listen_dsn(config: OutboxConfig) -> str | None:
    """libpq DSN of the LISTEN connection: ``notify_dsn`` or the app's ``DATABASE_URL``."""
    if config.notify_dsn:
        return config.notify_dsn
    try:
        from foundation.config import get_settings
        from sqlalchemy.engine.url import make_url

        url = make_url(get_settings().db.URL).set(drivername='postgresql')
        return url.render_as_string(hide_password=False)
    except Exception:  # noqa: BLE001
        return None


class OutboxPoller:
    def __init__(
        self,
        config: OutboxConfig,
        session_factory: Callable[[], AsyncSession],
        publisher: MessagingServiceT | None = None,
        repository: OutboxRepository[Any] | None = None,
        dispatchers: list[IOutboxDispatcher] | None = None,
        name: str = 'messaging',
        processor: OutboxProcessor | None = None,
    ) -> None:
        self.config = config
        self.name = name
        self.processor = processor or OutboxProcessor(
            name=name,
            repository=repository or OutboxRepository(MessagingOutboxTable, config),
            session_factory=session_factory,
            dispatchers=dispatchers or default_dispatchers(publisher),
            config=config,
        )
        self.repository = self.processor.repository
        self.metrics = self.processor.metrics
        self.logger = LogFactory().get_logger(f'OutboxPoller[{name}]')
        self._running = False
        self._wakers: list[_Waker] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._listen_task: asyncio.Task[None] | None = None
        self._stats_waker = _Waker()
        self.last_error: str | None = None
        self._last_success = time.monotonic()
        cli.info_table(
            'OutboxPoller startup info',
            {
                'outbox': name,
                'table': self.repository.table_name,
                'targets': ', '.join(
                    str(getattr(t, 'value', t)) for t in self.processor.router.targets
                ),
                'concurrent_workers': config.concurrent_workers,
                'batch_size': config.batch_size,
                'poll_strategy': config.poll_strategy,
                'min/initial/max_poll_interval_ms': (
                    f'{config.min_poll_interval_ms}/{config.initial_poll_interval_ms}/{config.max_poll_interval_ms}'
                ),
                'max_retries': config.max_retries,
                'preserve_ordering': config.preserve_ordering,
                'breaker': f'{config.breaker_failure_threshold} records, cool-down {config.breaker_cooldown_ms}ms',
                'notify_channel': config.notify_channel,
            },
        )

    def is_running(self) -> bool:
        return self._running

    def is_healthy(self, unhealthy_after_seconds: float = 60) -> bool:
        """Running, and not failing for longer than ``unhealthy_after_seconds``."""
        if not self._running:
            return False
        return not (
            self.last_error
            and time.monotonic() - self._last_success > unhealthy_after_seconds
        )

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        c = self.config
        self.logger.info(
            f'📤 relay {self.name}: {c.concurrent_workers} worker(s), batch {c.batch_size}, strategy {c.poll_strategy}'
        )
        for index in range(c.concurrent_workers):
            waker = _Waker()
            self._wakers.append(waker)
            self._tasks.append(asyncio.create_task(self._worker_loop(index, waker)))
        if c.poll_strategy == 'notify':
            self._listen_task = asyncio.create_task(self._listen_loop())
            self._tasks.append(self._listen_task)
        if c.enable_metrics:
            self._tasks.append(asyncio.create_task(self._metrics_loop()))

    async def run(self) -> None:
        """Start, then block until stopped."""
        await self.start()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.wake()
        self._stats_waker.wake()
        if self._listen_task is not None:
            self._listen_task.cancel()  # blocked in notifies(): cancel instead of waiting
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._listen_task = None
        self._tasks.clear()
        self._wakers.clear()
        if self.metrics:
            self.logger.info(f'Final metrics: {self.metrics.to_dict()}')
        self.logger.info(f'relay {self.name} stopped')

    def wake(self) -> None:
        """Poll now — call right after writing records in this process."""
        for waker in self._wakers:
            waker.wake()

    async def _worker_loop(self, index: int, waker: _Waker) -> None:
        c = self.config
        sleep_ms: float = c.initial_poll_interval_ms
        if c.concurrent_workers > 1 and index > 0:
            await waker.sleep(c.initial_poll_interval_ms * index / c.concurrent_workers)
        drain_at = max(1, int(c.batch_size * c.drain_threshold_ratio))
        while self._running:
            try:
                result = await self.processor.process_batch()
                self._last_success = time.monotonic()
                self.last_error = None
                if result.claimed >= drain_at and result.circuit == 'closed':
                    continue
                sleep_ms = next_idle_sleep_ms(
                    c.poll_strategy,
                    fixed_ms=c.fixed_poll_interval_ms,
                    min_ms=c.min_poll_interval_ms,
                    max_ms=c.max_poll_interval_ms,
                    growth_factor=c.backoff_growth_factor,
                    previous_ms=sleep_ms,
                    found=result.published,
                )
                if result.circuit != 'closed':
                    sleep_ms = max(
                        sleep_ms, min(c.breaker_cooldown_ms, c.max_poll_interval_ms)
                    )
                await waker.sleep(sleep_ms)
            except asyncio.CancelledError:
                break
            except Exception as error:  # noqa: BLE001
                self.last_error = describe_error(error)
                self.logger.error(
                    f'relay {self.name} worker {index}: {self.last_error}'
                )
                await waker.sleep(ERROR_PAUSE_SECONDS * 1000)

    async def _listen_loop(self) -> None:
        """LISTEN on ``notify_channel`` over a dedicated psycopg connection; reconnect with backoff."""
        import psycopg

        dsn = _listen_dsn(self.config)
        if not dsn:
            self.logger.error(
                f'relay {self.name}: notify strategy without a database URL, polling only'
            )
            return
        channel = self.config.notify_channel
        backoff = 1.0
        while self._running:
            try:
                async with await psycopg.AsyncConnection.connect(
                    dsn, autocommit=True
                ) as conn:
                    await conn.execute(f'LISTEN "{channel}"')
                    self.logger.info(f'relay {self.name}: listening on "{channel}"')
                    backoff = 1.0
                    async for _ in conn.notifies():
                        self.wake()
                        if not self._running:
                            break
            except asyncio.CancelledError:
                break
            except Exception as error:  # noqa: BLE001
                self.logger.warning(
                    f'relay {self.name}: LISTEN connection error: {error}; retry in {backoff:.0f}s'
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _metrics_loop(self) -> None:
        while self._running:
            await self._stats_waker.sleep(self.config.metrics_log_interval_ms)
            if not self._running:
                break
            try:
                stats = await self.processor.stats()
                metrics = self.metrics.to_dict() if self.metrics else {}
                self.logger.info(f'relay {self.name} stats: {stats} metrics: {metrics}')
            except Exception as error:  # noqa: BLE001
                self.logger.warning(
                    f'relay {self.name}: stats failed: {describe_error(error)}'
                )


__all__ = ['OutboxPoller']
