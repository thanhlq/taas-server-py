"""
🌀 Event Handlers

Handler registry and base classes for event processing.
"""
import dataclasses
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from logging import Logger
from typing import Dict, Optional, TypeVar, cast

from foundation import BaseService
from foundation.messaging.types import BaseEvent, EventMetadata, ProcessingResult
from foundation.observability.log_factory import LogFactory

EventT = TypeVar('EventT', bound=BaseEvent)


@dataclass(frozen=True)
class EventStep:
    """A single hop in a business flow.

    Attributes:
        event: The event class that triggers this step.
        handlers: Handler classes registered for ``event`` in the
            runtime registry.
        emits: Event classes the handlers are expected to publish next.
            Empty tuple means a terminal step.
        note: One-sentence human description of what happens here.
    """

    event: type[BaseEvent]
    handlers: tuple[type[BaseEventHandler], ...]
    emits: tuple[type[BaseEvent], ...] = field(default_factory=tuple)
    note: str = ''


class BaseEventHandler[EventT: BaseEvent](BaseService, ABC):
    """
    Base class for event handlers.

    All event handlers should inherit from this class and implement
    the handle_event() method for their specific event type.

    With the flat-event (Option 2) design, ``EventT`` should be a typed
    ``BaseEvent`` subclass (e.g. ``UserRegisteredEvent``).  ``get_payload``
    returns the event itself when it is already the right type, falling back
    to field-based reconstruction for backward compatibility.
    """

    # ---------------------------------------------------------------------------
    # METADATA
    # ---------------------------------------------------------------------------

    handler_name: str
    event_class: type[EventT]


    """ Needed for retry logic i.e. invoke only failed handlers """

    def __init__(
        self,
        event_class: type[EventT] | None = None,
        handler_name: str | None = None,
        **kwargs,
    ):
        # super().__init__(**kwargs)
        self.event_class: type[EventT] = event_class or cast(type[EventT], BaseEvent)
        self.handler_name = handler_name or self.__class__.__name__

    @property
    def handler_id(self) -> str:
        """Unique identifier for this handler."""
        return f'{self.handler_name}'

    def build_idempotency_key(self, event: BaseEvent) -> str:
        """Build a unique key for this handler and event.

        This key is used to ensure that the same event is not processed
        multiple times by the same handler.
        """
        return f'{self.handler_id}:{event.event_id}'

    @property
    def logger(self) -> Logger:
        if self._logger is None:
            self._logger = LogFactory().get_logger(self.handler_name)
        return self._logger

    def get_event(self, event: BaseEvent) -> EventT:
        """Return the typed payload for *event*.

        When the messaging layer decodes messages with the event-type registry,
        *event* will already be an instance of ``event_class`` — in that case
        we simply return it.

        Otherwise (e.g. in unit tests or when no registry entry exists) we
        reconstruct the typed event from the flat fields present on *event*.
        """
        if isinstance(event, self.event_class):
            return cast(EventT, event)

        # Fallback: reconstruct typed event from the fields available on event.
        valid_fields = {f.name for f in dataclasses.fields(self.event_class)}
        data = {k: v for k, v in dataclasses.asdict(event).items() if k in valid_fields}
        return self.event_class(**data)

    async def handle(self, event: BaseEvent, meta: EventMetadata,  **kwargs) -> ProcessingResult:
        # metadata = EventMetadata(
        #     event_id=event.event_id,
        #     event_type=event.event_type,
        #     timestamp=event.timestamp,
        #     retry_count=event.retry_count,
        #     source=event.source,
        #     correlation_id=event.correlation_id,
        #     user_id=event.user_id,
        #     handler_name=self.handler_name,
        # )
        return await self.handle_event(
            event=self.get_event(event), meta=meta, **kwargs
        )

    @abstractmethod
    async def handle_event(
        self, event: EventT, meta: EventMetadata, **kwargs
    ) -> ProcessingResult:
        """
        Handle the event.

        Args:
            event: Typed event (``BaseEvent`` subclass) — all domain fields
                   are accessible directly on the object.
            metadata: Synthesised ``EventMetadata`` view (backward compat).

        Returns:
            Processing result with success/failure status
        """
        pass

    async def validate(self, event: BaseEvent, meta: EventMetadata,  **kwargs) -> bool:
        """
        Validate event before processing.

        Args:
            event: Event to validate
            metadata: Synthesised ``EventMetadata`` view (backward compat).

        Returns:
            True if valid, False otherwise
        """
        return True


class HandlerRegistry:
    """
    Registry for event handlers.

    Maintains a mapping of event types to their handler instances.
    """

    def __init__(self):
        self._handlers: Dict[str, BaseEventHandler] = {}
        self.logger = LogFactory().get_logger(self.__class__.__name__)

    def register(
        self,
        event_type: str,
        handler: BaseEventHandler,
    ) -> None:
        self._handlers[event_type] = handler
        self.logger.debug(
            f'🌀 Registered EVENT handler [event={event_type}, handler={handler.__class__.__name__}]'
        )

    def unregister(self, event_type: str) -> None:
        """
        Unregister handler for an event type.

        Args:
            event_type: Event type identifier
        """
        if event_type in self._handlers:
            del self._handlers[event_type]
            self.logger.info(f'🗑️ Handler unregistered, event_type={event_type}')
        else:
            self.logger.warning(
                f'⚠️ No handler found to unregister for event_type={event_type}'
            )

    def get_handler(self, event_type: str) -> Optional[BaseEventHandler]:
        """
        Get handler for an event type.

        Args:
            event_type: Event type identifier

        Returns:
            Handler instance or None if not found
        """
        return self._handlers.get(event_type)

    def list_handlers(self) -> list[str]:
        """Get list of registered event types."""
        return list(self._handlers.keys())

    @property
    def handler_count(self) -> int:
        """Get number of registered handlers."""
        return len(self._handlers)


# Global registry instance
handlerRegistry = HandlerRegistry()
