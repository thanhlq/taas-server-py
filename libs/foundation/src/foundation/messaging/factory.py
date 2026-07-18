from typing import Any

from foundation.state import get_service, register_service

from .types import (
    IMessageRoutingService,
    IMessagingQueueService,
    IMessagingService,
    IMessagingStreamService,
    MessagingType,
)


class MessagingFactory:
    """A convenient factory for getting of messaging services."""

    # decorator: IMessagingDecorators

    @staticmethod
    def init_factory(messaging_service: IMessagingService, decorator: Any):
        register_service(IMessagingService, messaging_service)
        # MessagingFactory.decorator = decorator
        """Initialize the factory by registering messaging services in the service locator."""
        # Register messaging services in the service locator
        # This is where you would instantiate and register your concrete messaging service implementations
        # For example:
        # get_service_locator().register(IMessagingPubSubService, KafkaMessagingService())
        # get_service_locator().register(IMessagingQueueService, SqsMessagingService())
        # get_service_locator().register(IMessagingStreamService, FastStreamMessagingService())
        pass  # Replace with actual registration logic

    @staticmethod
    def get_messaging_routing_service() -> IMessageRoutingService:
        """Return an instance of the messaging routing service."""
        return get_service(IMessageRoutingService)

    @staticmethod
    def get_messaging_service(type: MessagingType = MessagingType.PUBSUB):
        if type == MessagingType.PUBSUB:
            return get_service(IMessagingService)
        elif type == MessagingType.QUEUE:
            return get_service(IMessagingQueueService)
        elif type == MessagingType.STREAM:
            return get_service(IMessagingStreamService)
