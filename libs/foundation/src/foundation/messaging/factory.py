from typing import Any

from foundation.state import get_service, register_service

from .types import (
    IMessagingStreamService,
    MessageRoutingServiceT,
    MessagingQueueServiceT,
    MessagingServiceT,
    MessagingType,
)


class MessagingFactory:
    """A convenient factory for getting of messaging services."""

    # decorator: IMessagingDecorators

    @staticmethod
    def init_factory(messaging_service: MessagingServiceT, decorator: Any):
        register_service(MessagingServiceT, messaging_service)

    @staticmethod
    def get_messaging_routing_service() -> MessageRoutingServiceT:
        """Return an instance of the messaging routing service."""
        return get_service(MessageRoutingServiceT)

    @staticmethod
    def get_messaging_service(type: MessagingType = MessagingType.PUBSUB):
        if type == MessagingType.PUBSUB:
            return get_service(MessagingServiceT)
        elif type == MessagingType.QUEUE:
            return get_service(MessagingQueueServiceT)
        elif type == MessagingType.STREAM:
            return get_service(IMessagingStreamService)
