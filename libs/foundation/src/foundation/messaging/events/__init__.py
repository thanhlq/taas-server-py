"""
Event processing module.

This module provides event processing infrastructure including:
- EventProcessor: Main event processing with retry logic
- EventProcessorFast: High-performance event processing with parallel execution
- EventProcessorConfig: Configuration for event processing
- Event types and handlers
"""

from .event_handler import BaseEventHandler, handlerRegistry
from .event_processor import EventProcessor
from .event_processor_config import EventProcessorConfig
from .event_processor_fast import EventProcessorFast
from .types import BaseEvent, ProcessingResult

__all__ = [
    'EventProcessor',
    'EventProcessorFast',
    'EventProcessorConfig',
    'BaseEvent',
    'ProcessingResult',
    'BaseEventHandler',
    'handlerRegistry',
]
