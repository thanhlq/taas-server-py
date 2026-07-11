"""
🔄 Event Processor Fast

Centralized event processing with retry logic, error handling, observability,
and optional parallel execution for high-throughput scenarios.
Can be used by any pubsub implementation (Kafka, RabbitMQ, Redis, etc.)
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, Optional, Set, Union

from core.conf.settings import get_app_settings
from core.events.types import BaseEvent, ProcessingResult
from core.observability.error_reporter import report_error
from core.observability.log_factory import LogFactory
from core.safety.retry import Retry

from ..db.sa.db_manager import MainDBManager
from ..messaging.idempotency import IdempotencyConfig, IdempotencyService
from ..messaging.idempotency.types import DuplicateEventError
from ..messaging.retry import DLQConfig, DLQService
from ..observability.trace_factory import TracingFactory
from ..utils.debug import debug_exception
from .event_handler import BaseEventHandler, handlerRegistry
from .event_processor_config import EventProcessorConfig
from .event_processor_handler import execute_handler_with_tracing

if TYPE_CHECKING:
    from ..messaging.types import MessageServiceStats


class EventProcessorFast:
    """
    Centralized event processor with retry logic, observability, and optional parallel execution.

    Features:
        - Automatic retry with exponential backoff
        - OpenTelemetry span creation and exception recording
        - Handler registry integration
        - Statistics tracking
        - Trace context propagation
        - Optional parallel execution with configurable concurrency limit

    Usage:
        # Sequential processing (default)
        processor = EventProcessorFast()
        result = await processor.process_event(event, traceparent='00-...')

        # Parallel processing with custom concurrency
        config = EventProcessorConfig(
            enable_parallel_execution=True,
            max_concurrent_tasks=20
        )
        processor = EventProcessorFast(config=config)
        results = await processor.process_events_batch([event1, event2, ...])

        # Cleanup
        await processor.cleanup()
    """

    def __init__(
        self,
        config: Optional[EventProcessorConfig] = None,
        stats: Union['MessageServiceStats', dict, None] = None,
        session_factory: Optional[Any] = None,
        idempotency_config: Optional[IdempotencyConfig] = None,
    ):
        """
        Initialize event processor.

        Args:
            config: Event processor configuration. If None, uses default config from settings.
            stats: Optional statistics dict to track retries. If None, internal stats are used.
            session_factory: Optional async session factory for DLQ and idempotency operations.
                           If provided, failed events will be saved to DLQ and idempotency
                           keys will be persisted when enable_dlq / enable_idempotency are True.
            idempotency_config: Optional idempotency configuration override. When omitted,
                           IdempotencyConfig.from_settings() is used if enable_idempotency=True.
        """
        self.config = config or EventProcessorConfig.from_settings()
        self.logger = LogFactory().get_logger(self.__class__.__name__)
        self._internal_stats = {
            'messages_retried': 0,
            'active_tasks': 0,
            'messages_dlq': 0,
        }
        self.stats = stats or self._internal_stats

        # Initialize retry policy with config
        if self.config.retry_enabled:
            self.retry_policy = Retry(
                name=self.config.retry_policy_name, max_attempts=self.config.max_retries
            )

        # Parallel execution support
        self.processing_tasks: Set[asyncio.Task] = set()

        # DLQ support
        self.session_factory: Any = (
            session_factory
            or MainDBManager.get_instance().session_factory()  # Callable that returns async session context manager
        )
        self.dlq_service: Optional[DLQService] = None
        if self.config.enable_dlq:
            dlq_config = DLQConfig.from_settings(get_app_settings())
            self.dlq_service = DLQService(config=dlq_config)

        # Idempotency support
        self.idempotency_service: Optional[IdempotencyService] = None
        if self.config.enable_idempotency:
            _idem_cfg = idempotency_config or IdempotencyConfig.from_settings(
                get_app_settings()
            )
            self.idempotency_service = IdempotencyService(_idem_cfg)

        if self.config.enable_dlq or self.config.enable_idempotency:
            self.logger.info(
                f'⚡ EventProcessorFast initialized '
                f'dlq={self.config.enable_dlq} '
                f'idempotency={self.config.enable_idempotency} '
                f'parallel_execution={self.config.enable_parallel_execution} '
                f'max_concurrent_tasks={self.config.max_concurrent_tasks}'
            )
        else:
            self.logger.info(
                f'⚡ EventProcessorFast initialized with parallel_execution='
                f'{self.config.enable_parallel_execution}, '
                f'max_concurrent_tasks={self.config.max_concurrent_tasks}'
            )

    @TracingFactory.instrument  # type ignore
    async def process_event(
        self,
        event: BaseEvent,
        traceparent: Optional[str] = None,
        handler: Optional[BaseEventHandler] = None,
    ) -> ProcessingResult:
        """
        Process event with retry logic and observability.

        When idempotency is enabled (config.enable_idempotency=True), duplicate
        deliveries of the same (handler_name, event_id) pair are detected early
        and returned immediately without executing the handler.  Only genuinely
        successful handler executions mark the idempotency key — failures
        propagate as exceptions so the key is never recorded, keeping the event
        eligible for retry.

        Args:
            event: Event to process
            traceparent: Optional W3C traceparent header for distributed tracing
            handler: Optional handler instance. If None, will lookup from registry.

        Returns:
            ProcessingResult with success status, timing, and error details
        """
        # Get handler from registry if not provided
        if handler is None:
            handler = handlerRegistry.get_handler(event.event_type)

        if not handler:
            self.logger.warning(
                f'No handler found for event type: {event.event_type}, event_id: {event.event_id}',
            )
            return ProcessingResult(
                success=False,
                event_id=event.event_id,
                processing_time_ms=0,
                error=f'No handler for event type: {event.event_type}',
                message='Handler not found',
            )

        start_time = time.time()
        handler_name = handler.__class__.__name__
        event.handler_name = handler_name

        try:
            if self.idempotency_service is not None:
                # Idempotency guard wraps the retry block.
                # - On entry: exits early (raises DuplicateEventError) if already processed.
                # - On clean exit: marks the key as processed atomically.
                # - On exception: does NOT mark — event stays retryable.
                self.logger.debug(
                    f'Processing event with IDEMPOTENCY guard: event_id={event.event_id} handler={handler_name}'
                )
                async with self.session_factory() as idempotency_session:
                    async with self.idempotency_service.guard(
                        session=idempotency_session,
                        event_id=event.event_id,
                        handler_name=handler_name,
                        event_type=event.event_type,
                        correlation_id=getattr(event, 'correlation_id', None),
                        tenant_id=getattr(event, 'tenant_id', None),
                        raise_on_duplicate=True,
                    ):
                        result = await self._run_with_retry(
                            event, handler, handler_name, traceparent, start_time
                        )
                    await idempotency_session.commit()
            else:
                self.logger.debug(
                    f'Processing event without idempotency guard: event_id={event.event_id} handler={handler_name}'
                )
                result = await self._run_with_retry(
                    event, handler, handler_name, traceparent, start_time
                )
            return result

        except DuplicateEventError as dup:
            # Event was already successfully processed — skip silently.
            self.logger.info(
                f'Duplicate event skipped idempotency_key={dup.idempotency_key} '
                f'event_id={event.event_id} '
                f'handler={handler_name}'
            )
            return ProcessingResult(
                success=True,
                event_id=event.event_id,
                processing_time_ms=0,
                message='Duplicate event - already processed',
            )

        except Exception as e:
            if event.retry_count == 0:
                debug_exception(e)
            else:
                # Shorter error message for retries to avoid log bloat, since the full exception is already recorded in the span.
                self.logger.error(
                    f'Error processing event (retry_count={event.retry_count}): '
                    f'event_id={event.event_id} '
                    f'handler={handler_name} '
                    f'error={str(e)[:200] if str(e) else "Unknown error"}'
                )
            # Exception already recorded in span
            # Create structured result for DLQ processing
            result = ProcessingResult(
                success=True,  # So that kafka will not retry again (disable kafka dlq)
                event_id=event.event_id,
                processing_time_ms=(time.time() - start_time) * 1000,
                error=str(e),
                retry_count=event.retry_count,
                handler_name=handler_name,
                message='Failed',
            )

            # Save to DLQ if enabled
            if self.config.enable_dlq:
                try:
                    await self._save_to_dlq(event, result)
                except Exception as dlq_error:
                    report_error(
                        dlq_error,
                        title='DLQ Save Error',
                        extra_context={
                            'event_id': event.event_id,
                        },
                        logger=self.logger,
                    )

            return result

    async def _run_with_retry(
        self,
        event: BaseEvent,
        handler: BaseEventHandler,
        handler_name: str,
        traceparent: Optional[str],
        start_time: float,
    ) -> ProcessingResult:
        """
        Execute handler through the retry policy.  Raises on final failure so
        that callers (idempotency guard, DLQ handler) can handle the exception
        correctly without accidentally marking a failed event as processed.
        """
        if self.config.retry_enabled:
            return await self.retry_policy.execute_async(
                func=lambda: execute_handler_with_tracing(
                    event=event,
                    handler=handler,
                    handler_name=handler_name,
                    traceparent=traceparent,
                    config=self.config,
                    stats=self.stats,
                    logger=self.logger,
                    start_time=start_time,
                )
            )  # type: ignore
        else:
            return await execute_handler_with_tracing(
                event=event,
                handler=handler,
                handler_name=handler_name,
                traceparent=traceparent,
                config=self.config,
                stats=self.stats,
                logger=self.logger,
                start_time=start_time,
            )

    def get_stats(self) -> dict:
        """Get processor statistics."""
        stats = self.stats.copy()
        stats['active_tasks'] = len(self.processing_tasks)
        return stats

    def get_config(self) -> EventProcessorConfig:
        """Get processor configuration."""
        return self.config

    async def process_events_batch(
        self,
        events: list[BaseEvent],
        traceparent: Optional[str] = None,
    ) -> list[ProcessingResult]:
        """
        Process multiple events with optional parallel execution.

        If parallel execution is enabled, processes events concurrently
        while respecting the max_concurrent_tasks limit.

        Args:
            events: List of events to process
            traceparent: Optional W3C traceparent header for distributed tracing

        Returns:
            List of ProcessingResults in the same order as input events

        Example:
            >>> events = [event1, event2, event3]
            >>> results = await processor.process_events_batch(events)
            >>> for result in results:
            ...     print(f"Event {result.event_id}: {result.success}")
        """
        if not self.config.enable_parallel_execution:
            # Sequential processing
            single_results: list[ProcessingResult] = []
            for event in events:
                result = await self.process_event(event, traceparent)
                single_results.append(result)
            return single_results

        # Parallel processing with concurrency limit
        results: list[Optional[ProcessingResult]] = [None] * len(events)
        pending_indices = list(range(len(events)))

        while pending_indices:
            # Determine how many tasks we can start
            available_slots = self.config.max_concurrent_tasks - len(
                self.processing_tasks
            )
            batch_size = min(available_slots, len(pending_indices))

            if batch_size > 0:
                # Start new tasks
                batch_indices = pending_indices[:batch_size]
                pending_indices = pending_indices[batch_size:]

                for idx in batch_indices:
                    task = asyncio.create_task(
                        self._process_event_for_batch(
                            events[idx], idx, results, traceparent
                        )
                    )
                    self.processing_tasks.add(task)
                    task.add_done_callback(self.processing_tasks.discard)

            # Wait for at least one task to complete
            if self.processing_tasks:
                done, _ = await asyncio.wait(
                    self.processing_tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Handle any exceptions from completed tasks
                for task in done:
                    try:
                        await task
                    except Exception as e:
                        report_error(
                            e,
                            title='Batch Processing Task Error',
                            logger=self.logger,
                        )

        # Wait for any remaining tasks
        if self.processing_tasks:
            await asyncio.gather(*self.processing_tasks, return_exceptions=True)

        # Type assertion: all results should be filled at this point
        return results  # type: ignore

    async def _process_event_for_batch(
        self,
        event: BaseEvent,
        index: int,
        results: list[Optional[ProcessingResult]],
        traceparent: Optional[str],
    ) -> None:
        """
        Internal method to process event and store result in list.

        Args:
            event: Event to process
            index: Index in results list
            results: Results list to store the result
            traceparent: Optional traceparent header
        """
        try:
            result = await self.process_event(event, traceparent)
            results[index] = result
        except Exception as e:
            report_error(
                e,
                title='Unexpected Batch Processing Error',
                extra_context={
                    'event_id': event.event_id,
                },
                logger=self.logger,
            )
            # Create error result
            results[index] = ProcessingResult(
                success=False,
                event_id=event.event_id,
                processing_time_ms=0,
                error=str(e),
                message='Batch processing error',
            )

    # @TracingFactory.instrument
    async def _save_to_dlq(
        self,
        event: BaseEvent,
        result: ProcessingResult,
    ) -> None:
        """
        Save failed event to database DLQ.

        Args:
            event: Failed event
            result: Processing result with error details
        """
        # Type guards to ensure we have necessary components
        if self.session_factory is None or self.dlq_service is None:
            self.logger.warning(
                'DLQ is enabled but session_factory or dlq_service is not configured. Skipping DLQ save.'
            )
            return

        async with self.session_factory() as session:  # type: ignore
            try:
                source_destination = f'{getattr(event, "source", "unknown")}->{getattr(event, "destination", "unknown")}'
                dlq_id = await self.dlq_service.save_event(
                    session=session,
                    event=event,
                    error=result.error or 'Unknown error',
                    handler_name=result.handler_name or 'unknown',
                    source_destination=source_destination,
                    traceparent=getattr(event, 'traceparent', None),
                )
                await session.commit()

                self.stats['messages_dlq'] += 1

                self.logger.warning(
                    f'Event saved to DLQ: dlq_id={dlq_id}, '
                    f'event_id={event.event_id}, '
                    f'handler={result.handler_name}, '
                    f'retry_count={event.retry_count}, '
                    f'error={result.error[:100] if result.error else "Unknown"}'
                )
            except Exception as e:
                await session.rollback()
                raise e

    async def cleanup(self) -> None:
        """
        Cleanup processor resources and wait for pending tasks.

        Call this method during shutdown to ensure all tasks complete gracefully.

        Example:
            >>> processor = EventProcessorFast()
            >>> # ... process events ...
            >>> await processor.cleanup()
        """
        if self.processing_tasks:
            self.logger.info(
                f'Waiting for {len(self.processing_tasks)} processing tasks to complete'
            )

            try:
                await asyncio.gather(*self.processing_tasks, return_exceptions=True)
            except Exception as e:
                report_error(
                    e,
                    title='Event Processor Cleanup Error',
                    logger=self.logger,
                )

            self.processing_tasks.clear()

        self.logger.info('EventProcessorFast cleanup completed')
