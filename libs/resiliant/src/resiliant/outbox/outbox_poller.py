"""
Outbox poller — claims due records of ONE outbox table and dispatches them.

Pure poller: it owns the polling / publishing loop only. It does **not**
manage a process lifecycle, health checks or signal handling — a separate
worker application (see ``apps/outbox_worker``) is expected to construct an
:class:`OutboxPoller` and drive it via :meth:`run` / :meth:`stop`.

The poller reuses the transactional-outbox building blocks already provided by
this library:

* :class:`resiliant.outbox.OutboxRepository` — batched claim / mark helpers,
  bound to the outbox table (any ``OutboxRecordMixin`` model)
* :class:`resiliant.outbox.dispatchers.OutboxDispatchRouter` — delivers each record
  to the dispatcher of its ``target`` (messaging, …)
* :class:`foundation.resiliant.outbox.OutboxConfig` — polling policy

One poller per registered outbox (see ``resiliant.outbox.factory.build_outbox_pollers``).
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from foundation.cli import cli
from foundation.messaging.types import MessagingServiceT
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.outbox import IOutboxDispatcher, OutboxConfig, OutboxStatus
from foundation.utils.icons import Icons
from sqlalchemy.ext.asyncio import AsyncSession

from resiliant.models.outbox import MessagingOutboxTable, OutboxRecordMixin

from .dispatchers import OutboxDispatchRouter, default_dispatchers
from .outbox_metrics import OutboxMetrics
from .outbox_repository import OutboxRepository


@dataclass
class OutboxPollerState:
    """Runtime state for the outbox poller (adaptive polling)."""

    current_interval_ms: float = 500.0
    consecutive_empty_polls: int = 0
    consecutive_full_polls: int = 0
    total_polls: int = 0
    total_events_processed: int = 0
    last_poll_time: Optional[float] = None

    def reset_interval(self, config: OutboxConfig) -> None:
        """Reset to initial interval."""
        self.current_interval_ms = float(config.initial_poll_interval_ms)
        self.consecutive_empty_polls = 0
        self.consecutive_full_polls = 0


class OutboxPoller:
    """
    Adaptive outbox poller with batch processing and concurrent workers.

    Features:
    - Adaptive polling (faster when busy, slower when idle)
    - Batch processing for high throughput
    - SKIP LOCKED for concurrent workers
    - Automatic retry with exponential backoff (via the repository)
    - Comprehensive metrics tracking
    - Stale event recovery
    """

    def __init__(
        self,
        config: OutboxConfig,
        session_factory: Callable[[], AsyncSession],
        publisher: Optional[MessagingServiceT] = None,
        repository: Optional[OutboxRepository[Any]] = None,
        dispatchers: Optional[list[IOutboxDispatcher]] = None,
        name: str = 'messaging',
    ):
        """
        Initialize outbox poller.

        Args:
            config: Outbox configuration.
            session_factory: Factory for creating database sessions.
            publisher: Broker publisher for the default messaging dispatcher
                (resolved from the service locator when omitted).
            repository: Repository of the outbox table to poll. Defaults to the
                messaging outbox.
            dispatchers: One per target; defaults to the built-in dispatchers.
            name: Outbox name (logs / metrics).
        """
        self.config = config
        self.session_factory = session_factory
        self.name = name
        self.repository = repository or OutboxRepository(MessagingOutboxTable, config)
        self.router = OutboxDispatchRouter(dispatchers or default_dispatchers(publisher))
        self.logger = LogFactory().get_logger(f'{self.__class__.__name__}[{name}]')

        # Runtime state
        self.state = OutboxPollerState(
            current_interval_ms=float(config.initial_poll_interval_ms)
        )
        self.metrics = OutboxMetrics() if config.enable_metrics else None

        # Control flags
        self._running = False
        self._worker_tasks: list[asyncio.Task] = []
        self._maintenance_task: Optional[asyncio.Task] = None

        # Wake-up signal for early polling (set by wake() or NOTIFY listener)
        self._wake_event: asyncio.Event = asyncio.Event()
        self._notify_task: Optional[asyncio.Task] = None

        startup_info: dict[str, Any] = {
            'outbox': name,
            'table': self.repository.table_name,
            'targets': ', '.join(t.value for t in self.router.targets),
            'concurrent_workers': config.concurrent_workers,
            'batch_size': config.batch_size,
            'poll_strategy': config.poll_strategy,
            'initial_poll_interval_ms': config.initial_poll_interval_ms,
            'min_poll_interval_ms': config.min_poll_interval_ms,
            'max_poll_interval_ms': config.max_poll_interval_ms,
            'backoff_growth_factor': config.backoff_growth_factor,
            'drain_threshold_ratio': config.drain_threshold_ratio,
            'notify_channel': config.notify_channel,
            'notify_dsn': config.notify_dsn,
            'enable_metrics': config.enable_metrics,
            'metrics_log_interval_seconds': config.metrics_log_interval_seconds,
        }
        cli.info_table('OutboxPoller startup info', startup_info)
        # self.logger.info(f'Outbox poller initialized: {startup_info}')

    async def start(self) -> None:
        """Start the outbox poller with concurrent workers."""
        if self._running:
            self.logger.warning('Outbox poller already running')
            return

        self._running = True
        self.logger.info(
            f'📤 Starting outbox poller with {self.config.concurrent_workers} workers '
            f'(strategy={self.config.poll_strategy})'
        )

        # Start worker tasks
        for i in range(self.config.concurrent_workers):
            task = asyncio.create_task(self._worker_loop(worker_id=i))
            self._worker_tasks.append(task)

        # Start maintenance task
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())

        # Start NOTIFY listener if configured (Postgres LISTEN/NOTIFY).
        if self.config.poll_strategy == 'notify' and self.config.notify_dsn:
            self._notify_task = asyncio.create_task(self._notify_listener_loop())

        self.logger.info('Outbox poller started successfully')

    async def run(self) -> None:
        """
        Run the outbox poller until stopped.

        This is the main entry point that blocks until the poller is stopped.
        Use this method when you want to await the poller's completion.
        """
        await self.start()

        # Wait for all tasks to complete
        tasks_to_wait = [*self._worker_tasks]
        if self._maintenance_task:
            tasks_to_wait.append(self._maintenance_task)
        if self._notify_task:
            tasks_to_wait.append(self._notify_task)

        if not tasks_to_wait:
            return

        try:
            await asyncio.gather(*tasks_to_wait, return_exceptions=False)
        except asyncio.CancelledError:
            self.logger.info('Outbox poller run cancelled')
            raise

    async def stop(self) -> None:
        """Stop the outbox poller gracefully."""
        if not self._running:
            return

        self.logger.info('Stopping outbox poller...')
        self._running = False

        # Wake any sleeping workers so they observe the shutdown flag promptly
        self._wake_event.set()

        # Cancel all worker tasks
        for task in self._worker_tasks:
            task.cancel()

        # Cancel maintenance task
        if self._maintenance_task:
            self._maintenance_task.cancel()

        # Cancel notify listener
        if self._notify_task:
            self._notify_task.cancel()

        # Wait for tasks to complete
        tasks_to_wait = [*self._worker_tasks]
        if self._maintenance_task:
            tasks_to_wait.append(self._maintenance_task)
        if self._notify_task:
            tasks_to_wait.append(self._notify_task)

        if tasks_to_wait:
            await asyncio.gather(*tasks_to_wait, return_exceptions=True)

        self._worker_tasks.clear()
        self._maintenance_task = None
        self._notify_task = None

        # Log final metrics
        if self.metrics:
            self.logger.info(f'Final metrics: {self.metrics.to_dict()}')

        self.logger.info('Outbox poller stopped')

    async def _worker_loop(self, worker_id: int) -> None:
        """
        Main worker loop for polling and publishing events.

        Sleep behavior is selected by `config.poll_strategy`:
          - 'fixed':    sleep `fixed_poll_interval_ms` every cycle
          - 'adaptive': decorrelated jitter backoff between min/max
          - 'notify':   adaptive backoff + wake on Postgres NOTIFY / wake()

        In all strategies, when a full batch is fetched we skip the sleep and
        loop again ('drain mode') to clear the backlog as fast as possible.

        Args:
            worker_id: Worker identifier for logging
        """
        self.logger.info(
            f'Worker {worker_id} started (strategy={self.config.poll_strategy})'
        )

        # Stagger workers so they don't all hit the DB at the same instant
        if self.config.concurrent_workers > 1:
            stagger = (
                self.config.initial_poll_interval_ms / 1000.0
            ) * (worker_id / self.config.concurrent_workers)
            if stagger > 0:
                await asyncio.sleep(stagger)

        while self._running:
            try:
                fetched = await self._poll_and_publish(worker_id)

                # Drain mode: full batch -> immediately poll again, no sleep
                drain_threshold = max(
                    1,
                    int(self.config.batch_size * self.config.drain_threshold_ratio),
                )
                if fetched >= drain_threshold:
                    continue

                sleep_seconds = self._compute_next_sleep(fetched) / 1000.0
                await self._sleep_or_wake(sleep_seconds)

            except asyncio.CancelledError:
                self.logger.info(f'Worker {worker_id} cancelled')
                break
            except Exception as e:
                self.logger.error(
                    f'Worker {worker_id} error in poll loop: {e}',
                    exc_info=True,
                )
                # Back off on error
                await asyncio.sleep(1.0)

        self.logger.info(f'Worker {worker_id} stopped')

    def _compute_next_sleep(self, fetched: int) -> float:
        """
        Compute next sleep interval (ms) based on the configured strategy
        and the most recent poll outcome.
        """
        cfg = self.config
        state = self.state

        if cfg.poll_strategy == 'fixed':
            state.current_interval_ms = float(cfg.fixed_poll_interval_ms)
            return state.current_interval_ms

        # 'adaptive' and 'notify' share the same backoff math; 'notify' just
        # additionally relies on _wake_event to short-circuit the sleep.
        if fetched > 0:
            # Reset toward min when there's work
            state.current_interval_ms = float(cfg.min_poll_interval_ms)
        else:
            # Decorrelated jitter: next = U(min, min(max, prev * growth))
            upper = min(
                float(cfg.max_poll_interval_ms),
                state.current_interval_ms * cfg.backoff_growth_factor,
            )
            lower = float(cfg.min_poll_interval_ms)
            if upper < lower:
                upper = lower
            state.current_interval_ms = random.uniform(lower, upper)

        return state.current_interval_ms

    async def _sleep_or_wake(self, seconds: float) -> bool:
        """
        Sleep up to `seconds`, returning early if `_wake_event` is set.

        Returns True if woken early, False if the timeout elapsed.
        """
        if seconds <= 0:
            return False

        # Only the 'notify' strategy honors the wake event for early wake-up.
        # Other strategies still respect it for fast shutdown via stop().
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=seconds)
            self._wake_event.clear()
            return True
        except TimeoutError:
            return False

    def wake(self) -> None:
        """
        Trigger an immediate poll cycle.

        Producer code running in the same process can call this right after
        inserting a new outbox row to avoid waiting for the next poll tick.
        Safe to call from any asyncio task.
        """
        self._wake_event.set()

    async def _notify_listener_loop(self) -> None:
        """
        LISTEN on `config.notify_channel` and set the wake event on each NOTIFY.

        Uses a dedicated asyncpg connection (separate from SQLAlchemy pool)
        because LISTEN must hold a session for its lifetime.
        """
        try:
            import asyncpg  # type: ignore
        except ImportError:
            self.logger.error(
                'poll_strategy="notify" requires asyncpg; falling back to adaptive'
            )
            return

        channel = self.config.notify_channel
        dsn = self.config.notify_dsn
        backoff = 1.0

        while self._running:
            conn = None
            try:
                conn = await asyncpg.connect(dsn=dsn)

                def _on_notify(_conn, _pid, _channel, _payload):
                    self._wake_event.set()

                await conn.add_listener(channel, _on_notify)
                self.logger.info(f'NOTIFY listener attached to channel "{channel}"')
                backoff = 1.0

                # Idle until cancelled or the connection drops
                while self._running:
                    await asyncio.sleep(60)
                    # Lightweight keepalive
                    try:
                        await conn.execute('SELECT 1')
                    except Exception:
                        break

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.warning(
                    f'NOTIFY listener error: {e}; reconnecting in {backoff:.1f}s'
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if conn is not None:
                    try:
                        await conn.close()
                    except Exception:
                        pass

        self.logger.info('NOTIFY listener stopped')

    async def _poll_and_publish(self, worker_id: int) -> int:
        """Poll for events and publish them. Returns number of events fetched."""
        start_time = datetime.now()
        fetched_count = 0

        # self.logger.debug(f'{worker_id} Polling for outbox events...')
        try:
            # Create database session
            async with self.session_factory() as session:
                # Fetch pending events (also marks them PROCESSING + commits)
                events = await self.repository.fetch_pending_batch(
                    session, self.config.batch_size
                )
                fetched_count = len(events)

                self.logger.debug(
                    f'{worker_id} Polling for outbox events, found {Icons.MESSAGE_PUBLISHED if fetched_count > 0 else ''} {fetched_count}'
                )

                poll_duration_ms = (datetime.now() - start_time).total_seconds() * 1000

                # Update state
                self.state.total_polls += 1
                self.state.total_events_processed += fetched_count

                # Record metrics
                if self.metrics:
                    self.metrics.record_poll(
                        duration_ms=poll_duration_ms,
                        batch_size=fetched_count,
                        success=True,
                    )
                    self.metrics.current_poll_interval_ms = (
                        self.state.current_interval_ms
                    )

                # Track consecutive empty/full polls (kept for observability)
                if events:
                    self.state.consecutive_empty_polls = 0
                    self.state.consecutive_full_polls += 1
                else:
                    self.state.consecutive_empty_polls += 1
                    self.state.consecutive_full_polls = 0

                # Deliver records
                for event in events:
                    await self._publish_event(session, event)

        except Exception as e:
            self.logger.error(f'Error in poll and publish: {e}', exc_info=True)

            if self.metrics:
                poll_duration_ms = (datetime.now() - start_time).total_seconds() * 1000
                self.metrics.record_poll(
                    duration_ms=poll_duration_ms,
                    batch_size=0,
                    success=False,
                )

        return fetched_count

    async def _publish_event(
        self,
        session: AsyncSession,
        event: OutboxRecordMixin,
    ) -> None:
        """Deliver one claimed record via its target's dispatcher, then mark it
        published — or failed (retried with backoff, dead-lettered at the cap)."""
        start_time = datetime.now()
        self.logger.debug(
            f'Dispatching {event.event_type} (id={event.id}) to {event.target}:{event.channel}'  # type: ignore[attr-defined]
        )

        try:
            await self.router.dispatch(event)  # type: ignore[arg-type]
            await self.repository.mark_published(session, event.id)  # type: ignore[attr-defined]
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            if self.metrics:
                self.metrics.record_publish(duration_ms=duration_ms, success=True, moved_to_dlq=False)
            self.logger.debug(
                # Wording relied on by taas-tests/e2e/user-registration ("healthy run").
                f'Published event {event.event_type} (id={event.id}) to {event.channel} in {duration_ms:.2f}ms'  # type: ignore[attr-defined]
            )

        except Exception as e:
            error_msg = f'{type(e).__name__}: {e}'
            try:
                # Dispatch never writes to ``session``, so no rollback is needed (a
                # rollback would expire the other claimed records of this batch).
                new_status = await self.repository.mark_failed(session, event.id, error_msg)  # type: ignore[attr-defined]
            except Exception:
                self.logger.exception(f'Could not mark record {event.id} as failed')  # type: ignore[attr-defined]
                new_status = None
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            if self.metrics:
                self.metrics.record_publish(
                    duration_ms=duration_ms,
                    success=False,
                    moved_to_dlq=new_status == OutboxStatus.DEAD_LETTER,
                )
            self.logger.error(f'Failed to deliver {event.event_type} (id={event.id}): {error_msg}')  # type: ignore[attr-defined]

    async def _maintenance_loop(self) -> None:
        """
        Background maintenance tasks.

        - Reset stale processing events
        - Log metrics and outbox stats
        """
        self.logger.info('Maintenance loop started')

        # Stagger initial maintenance tasks
        await asyncio.sleep(30)

        while self._running:
            try:
                async with self.session_factory() as session:
                    # Reset stale events
                    reset_count = await self.repository.reset_stale_processing(session)
                    if self.metrics and reset_count > 0:
                        self.metrics.stale_events_reset += reset_count

                    # Log metrics
                    if self.metrics and self.config.enable_metrics:
                        self.logger.info(f'Outbox {self.name} metrics: {self.metrics.to_dict()}')

                    # Log stats
                    stats = await self.repository.get_stats(session)
                    self.logger.info(f'Outbox {self.name} stats: {stats}')

                # Sleep for configured interval
                await asyncio.sleep(self.config.metrics_log_interval_seconds)

            except asyncio.CancelledError:
                self.logger.info('Maintenance loop cancelled')
                break
            except Exception as e:
                self.logger.error(
                    f'Error in maintenance loop: {e}',
                    exc_info=True,
                )
                await asyncio.sleep(60)

        self.logger.info('Maintenance loop stopped')
