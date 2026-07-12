"""
Event processing module.

This module provides event processing infrastructure including:
- EventProcessor: Main event processing with retry logic
- EventProcessorConfig: Configuration for event processing
- Event types and handlers

Note:
    ``EventProcessorFast`` (parallel/high-throughput variant) and the
    flow-registration helpers are still being migrated off the legacy
    ``core.*`` package and are therefore not re-exported here yet. Import them
    from their submodules directly once migrated.
"""

from foundation.messaging.types import BaseEvent, ProcessingResult

from .event_handler import BaseEventHandler, handlerRegistry
from .event_processor import EventProcessor
from .event_processor_config import EventProcessorConfig

__all__ = [
    'EventProcessor',
    'EventProcessorConfig',
    'BaseEvent',
    'ProcessingResult',
    'BaseEventHandler',
    'handlerRegistry',
]

