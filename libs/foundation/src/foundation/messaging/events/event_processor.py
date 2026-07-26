"""
🔄 Event Processor

Centralized event processing with retry logic, error handling, and observability.
Can be used by any pubsub implementation (Kafka, RabbitMQ, Redis, etc.)
"""

import time
from typing import Optional

from foundation.exceptions.report_error import report_error
from foundation.messaging.types import BaseEvent, EventMetadata, ProcessingResult
from foundation.observability.log_factory import LogFactory
from foundation.observability.tracing_factory import TracingFactory
from foundation.resiliant.retry import Retry

from .event_handler import BaseEventHandler, handlerRegistry
from .event_processor_config import EventProcessorConfig, get_event_processor_config

# from .safety.exp_backoff_retry import ExponentialBackoffRetry as Retry


class EventProcessor:
    """
    Centralized event processor with retry logic and observability.

    Features:
        - Automatic retry with exponential backoff
        - OpenTelemetry span creation and exception recording
        - Handler registry integration
        - Statistics tracking
        - Trace context propagation

    Usage:
        # With default configuration
        processor = EventProcessor()
        result = await processor.process_event(event, traceparent='00-...')

        # With custom configuration
        config = EventProcessorConfig(max_retries=5, retry_backoff_ms=2000)
        processor = EventProcessor(config=config)
        result = await processor.process_event(event)

        # From settings
        config = EventProcessorConfig.from_settings()
        processor = EventProcessor(config=config)
    """

    def __init__(
        self,
        config: Optional[EventProcessorConfig] = None,
        stats: Optional[dict] = None,
    ):
        """
        Initialize event processor.

        Args:
            config: Event processor configuration. If None, uses default config from settings.
            stats: Optional statistics dict to track retries. If None, internal stats are used.
        """
        self._config = config or get_event_processor_config()
        self.logger = LogFactory().get_logger(self.__class__.__name__)
        self._internal_stats = {
            'messages_retried': 0,
        }
        self.stats = stats or self._internal_stats

        # Initialize retry policy with config
        self.retry_policy = Retry(name=self._config.retry_policy_name)

    @property
    def config(self) -> EventProcessorConfig:
        """Get the current event processor configuration."""
        return self._config

    def new_event_metadata(
        self,
        event: BaseEvent,
        handler: BaseEventHandler,
        traceparent: str | None = None,
    ) -> EventMetadata:
        return EventMetadata(
            handler_name=handler.handler_name,
            traceparent=traceparent,
        )

    async def process_event(
        self,
        event: BaseEvent,
        traceparent: Optional[str] = None,
        handler: Optional[BaseEventHandler] = None,
    ) -> ProcessingResult:
        """
        Process event with retry logic and observability.

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

        meta = self.new_event_metadata(event, handler, traceparent)

        start_time = time.time()
        handler_name = meta.handler_name
        # event.handler_name = handler_name

        # Define the processing function
        async def process_event_with_handler():
            if self.config.enable_tracing:
                self.logger.debug(
                    f'Processing event [{event.event_type}] with handler: {handler_name}, '
                    f'retry_count={event.retry_count}'
                )
            else:
                self.logger.debug(
                    f'Processing event [{event.event_type}] with handler: {handler_name}'
                )

            ContextTracer = TracingFactory().get_context_tracer()

            # Start span BEFORE handler execution so exceptions are captured
            # Only create span if tracing is enabled
            if self.config.enable_tracing:
                span_context = ContextTracer(handler_name, traceparent)
            else:
                # No-op context manager
                from contextlib import nullcontext

                span_context = nullcontext()

            with span_context as span:
                if self.config.enable_tracing and span:
                    span.set_attribute('handler_name', handler_name)
                    span.set_attribute('event_id', event.event_id)
                    span.set_attribute('event_type', event.event_type)
                    span.set_attribute('retry_count', event.retry_count)

                try:
                    result = await handler.handle_event(event, meta)
                    result.processing_time_ms = (time.time() - start_time) * 1000
                    result.handler_name = handler_name

                    if not result.success:
                        # Handler returned failure without exception - convert to exception for retry
                        event.retry_count += 1
                        if self.config.enable_metrics:
                            self.stats['messages_retried'] += 1
                        ex = Exception(result.error or 'Handler returned failure')
                        if self.config.enable_tracing and span:
                            span.record_exception(ex)

                    return result

                except Exception as e:
                    # Increment retry count and re-raise
                    event.retry_count += 1
                    if self.config.enable_metrics:
                        self.stats['messages_retried'] += 1
                    # self.logger.error(
                    #     f'Handler exception: handler={handler_name}, '
                    #     f'event_id={event.event_id}, error={str(e)}',
                    # )
                    report_error(
                        e,
                        title='Unexpected Event Processing Error',
                        extra_context={
                            'event_id': event.event_id,
                            'event_type': event.event_type,
                            'handler': handler_name,
                            'retry_count': event.retry_count,
                        },
                        logger=self.logger,
                    )
                    if self.config.enable_tracing and span:
                        span.record_exception(e)
                    raise e

        # Execute with retry policy
        # Note: execute_async() returns an awaitable coroutine, await it directly
        try:
            if self.config.retry_enabled:
                return await self.retry_policy.execute_async(
                    func=process_event_with_handler
                )  # type: ignore
            else:
                return await process_event_with_handler()
        except Exception as e:
            self.logger.debug('Event processing failed after retries: %r', e)
            # Exception already recorded in span
            # Return structured result for DLQ processing
            return ProcessingResult(
                success=False,
                event_id=event.event_id,
                processing_time_ms=(time.time() - start_time) * 1000,
                error=str(e),
                retry_count=event.retry_count,
                handler_name=handler_name,
                message='Failed',
            )

    def get_stats(self) -> dict:
        """Get processor statistics."""
        return self.stats.copy()

    def get_config(self) -> EventProcessorConfig:
        """Get processor configuration."""
        return self.config

    async def cleanup(self) -> None:
        """Drain in-flight work before shutdown.

        This processor handles each message synchronously within
        :meth:`process_event`, so there is no background task pool to await —
        the method exists to satisfy the messaging service's shutdown contract.
        """
        return None
