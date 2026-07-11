"""
Event Processor Handler Execution

Contains the core handler execution logic with retry, tracing, and error handling.
Extracted for cleaner code organization and reusability.
"""
from core.observability.error_reporter import report_error

import time
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any, Optional, Union

from core.events.types import BaseEvent, ProcessingResult
from core.observability.trace_factory import TracingFactory

from .event_handler import BaseEventHandler
from .event_processor_config import EventProcessorConfig

if TYPE_CHECKING:
    from ..messaging.types import MessageServiceStats


async def execute_handler_with_tracing(
    event: BaseEvent,
    handler: BaseEventHandler,
    handler_name: str,
    traceparent: Optional[str],
    config: EventProcessorConfig,
    stats: Union['MessageServiceStats', dict],
    logger,
    start_time: float,
) -> ProcessingResult:
    """
    Execute handler with tracing, metrics, and error handling.

    Args:
        event: Event to process
        handler: Handler instance to execute
        handler_name: Name of the handler class
        traceparent: Optional W3C traceparent header for distributed tracing
        config: Event processor configuration
        stats: Statistics dict for tracking metrics
        logger: Logger instance
        start_time: Start time for processing time calculation

    Returns:
        ProcessingResult with success status, timing, and error details

    Raises:
        Exception: Handler execution exceptions (for retry logic)
    """
    if config.enable_tracing:
        logger.debug(
            f'Processing event [{event.event_type}] with handler: {handler_name}, '
            f'retry_count={event.retry_count}'
        )
    else:
        logger.debug(
            f'Processing event [{event.event_type}] with handler: {handler_name}'
        )

    ContextTracer = TracingFactory().get_context_tracer()

    # Start span BEFORE handler execution so exceptions are captured
    # Only create span if tracing is enabled
    if config.enable_tracing:
        span_context = ContextTracer(handler_name, traceparent)
    else:
        # No-op context manager
        span_context = nullcontext()

    with span_context as span:
        if config.enable_tracing and span:
            span.set_attribute('handler_name', handler_name)
            span.set_attribute('event_id', event.event_id)
            span.set_attribute('event_type', event.event_type)
            span.set_attribute('retry_count', event.retry_count)

        try:
            result = await handler.handle(event)
            result.processing_time_ms = (time.time() - start_time) * 1000
            result.handler_name = handler_name

            if not result.success:
                # Handler returned failure without exception - convert to exception for retry
                event.retry_count += 1
                if config.enable_metrics:
                    stats['messages_retried'] += 1
                ex = Exception(result.error or 'Handler returned failure')
                if config.enable_tracing and span:
                    span.record_exception(ex)

            return result

        except Exception as e:
            # Increment retry count and re-raise
            event.retry_count += 1
            if config.enable_metrics:
                stats['messages_retried'] += 1
            # logger.error(
            #     f'Handler exception: handler={handler_name}, '
            #     f'event_id={event.event_id}, error={str(e)}',
            # )
            report_error(
                        e,
                        title=f'Unexpected Event Processing Error {event.retry_count}',
                        extra_context={
                            'event_id': event.event_id,
                            'event_type': event.event_type,
                            'handler': handler_name,
                            'retry_count': event.retry_count,
                        },
                        logger=logger,
                    )
            if config.enable_tracing and span:
                span.record_exception(e)
            raise e
