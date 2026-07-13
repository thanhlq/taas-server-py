from typing import Any

from foundation.state import register_service

from .message_routing_service import MessageRoutingService
from .types import (
    IMessagingPubSubService,
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
    def get_messaging_service(type: MessagingType = MessagingType.PUBSUB):
        if type == MessagingType.PUBSUB:
            return get_service_locator().get(IMessagingPubSubService)
        elif type == MessagingType.QUEUE:
            return get_service_locator().get(IMessagingQueueService)
        elif type == MessagingType.STREAM:
            return get_service_locator().get(IMessagingStreamService)
        else:
            return get_service_locator().get(IMessagingService)

    # @staticmethod
    # def get_stream_messaging_service() -> IMessagingStreamService:
    #     return get_service_locator().get(IMessagingStreamService)

    # @staticmethod
    # def get_queue_messaging_service() -> IMessagingQueueService:
    #     return get_service_locator().get(IMessagingQueueService)

    # @staticmethod
    # def get_pubsub_messaging_service() -> IMessagingPubSubService:
    #     return get_service_locator().get(IMessagingPubSubService)

    @staticmethod
    def get_message_routing_service() -> IOutboxService:
        return MessageRoutingService()
