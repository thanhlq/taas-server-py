"""
Outbox poller for fetching and publishing events.

Pure poller: it owns the polling / publishing loop only. It does **not**
manage a process lifecycle, health checks or signal handling — a separate
worker application (see ``apps/outbox_worker``) is expected to construct an
:class:`OutboxPoller` and drive it via :meth:`run` / :meth:`stop`.

The poller reuses the transactional-outbox building blocks already provided by
this library:

* :class:`resiliant.outbox.OutboxRepository` — batched fetch / mark helpers
* :class:`foundation.resiliant.outbox.OutboxConfig` — polling policy
* :class:`foundation.messaging.types.IMessagingService` — broker publisher
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

from db.models.resiliant import OutboxEventTable
from foundation.cli import cli
from foundation.messaging.types import IMessagingService
from foundation.observability.log_factory import LogFactory
from foundation.resiliant.outbox import OutboxConfig
from foundation.state import get_service
from foundation.utils.icons import Icons
from sqlalchemy.ext.asyncio import AsyncSession

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
        publisher: Optional[IMessagingService] = None,
        repository: Optional[OutboxRepository] = None,
    ):
        """
        Initialize outbox poller.

        Args:
            config: Outbox configuration.
            session_factory: Factory for creating database sessions.
            publisher: Message publisher (Kafka, SQS, etc.). Resolved lazily
                from the service locator when omitted.
            repository: Outbox repository. A fresh one is built from ``config``
                when omitted.
        """
        self.config = config
        self.session_factory = session_factory
        self._publisher = publisher
        self.repository = repository or OutboxRepository(config)
        self.logger = LogFactory().get_logger(
            f'{self.__class__.__name__}'
        )

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

        startup_info: dict[str | Any] = {
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

    @property
    def publisher(self) -> IMessagingService:
        """Get the message publisher."""
        if not self._publisher:
            self._publisher = get_service(IMessagingService)
        return self._publisher

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

        self.logger.debug(f'{worker_id} Polling for outbox events...')
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

                # Publish events
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
        event: OutboxEventTable,
    ) -> None:
        """
        Publish a single event.

        Args:
            session: Database session
            event: Outbox event to publish
        """
        start_time = datetime.now()
        msg_data = event.payload

        try:
            # Publish to messaging system
            await self.publisher.publish(
                channel=event.channel,
                message=msg_data,
                headers=event.headers,
                key=event.partition_key,
            )

            # Mark as published
            await self.repository.mark_published(session, event.id)

            publish_duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Record metrics
            if self.metrics:
                self.metrics.record_publish(
                    duration_ms=publish_duration_ms,
                    success=True,
                    moved_to_dlq=False,
                )

            self.logger.debug(
                f'Published event {event.event_type} (id={event.id}) '
                f'to {event.channel} in {publish_duration_ms:.2f}ms'
            )

        except Exception as e:
            # Mark as failed
            error_msg = f'{type(e).__name__}: {str(e)}'
            await self.repository.mark_failed(session, event.id, error_msg)

            publish_duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Check if moved to DLQ
            moved_to_dlq = (event.retry_count + 1) >= event.max_retries

            # Record metrics
            if self.metrics:
                self.metrics.record_publish(
                    duration_ms=publish_duration_ms,
                    success=False,
                    moved_to_dlq=moved_to_dlq,
                )

            self.logger.error(
                f'Failed to publish event {event.event_type} '
                f'(id={event.id}): {error_msg}'
            )

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
                        self.logger.info(f'Outbox metrics: {self.metrics.to_dict()}')

                    # Log stats
                    stats = await self.repository.get_stats(session)
                    self.logger.info(f'Outbox stats: {stats}')

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
