from typing import Optional

from core.events.types import BaseEvent, ProcessingResult

from .event_handler import BaseEventHandler
from .event_processor import EventProcessor


# Convenience function for one-off event processing
async def process_event(
    event: BaseEvent,
    traceparent: Optional[str] = None,
    handler: Optional[BaseEventHandler] = None,
) -> ProcessingResult:
    """
    Process a single event with retry logic.

    Convenience function that creates a processor instance and processes the event.
    For repeated processing, create an EventProcessor instance and reuse it.

    Args:
        event: Event to process
        traceparent: Optional W3C traceparent header for distributed tracing
        handler: Optional handler instance. If None, will lookup from registry.

    Returns:
        ProcessingResult with success status, timing, and error details

    Example:
        >>> from core.common.event_processor import process_event
        >>> result = await process_event(event, traceparent='00-...')
        >>> if result.success:
        >>>     print(f"Processed in {result.processing_time_ms}ms")
    """
    processor = EventProcessor()
    return await processor.process_event(event, traceparent, handler)
