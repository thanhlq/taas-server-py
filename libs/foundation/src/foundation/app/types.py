from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from foundation.http import BaseController
from foundation.messaging.events.event_handler import EventStep

if TYPE_CHECKING:
    from foundation.messaging.types import BaseEvent


class ApiApplicationModuleT(ABC):
    """
    If a module want to be integrated into the an api application it should implement this interface.
    """

    @abstractmethod
    def get_api_controllers(self) -> list[BaseController | type[BaseController]]: ...

    @abstractmethod
    def get_event_flows(self) -> dict[str, tuple[EventStep, ...]]: ...

    @abstractmethod
    def get_topic_for_event(self, event_cls: type['BaseEvent']) -> str: ...
    """ Return the appropriate (i.e. Kafka) topic for an event type. """
