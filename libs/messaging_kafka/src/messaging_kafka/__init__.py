from typing import Optional

from foundation.config import get_settings
from foundation.messaging.config.messaging_settings import (
    MessagingSettings,
)
from foundation.messaging.types import (
    MessagingServiceT,
)
from foundation.resiliant.retry import retry

from .aiokafka_messaging import AiokafkaMessagingService as KafkaMessagingService
from .decorator import messaging


async def create_pubsub_service(settings: MessagingSettings) -> MessagingServiceT:
    """Create pub/sub service based on configuration."""

    kafka = KafkaMessagingService()
    if settings.CONSUMER_ENABLED:
        await kafka.start_producer()
        await kafka.start_consumer()
    else:
        await kafka.start_producer()

    return kafka


@retry.decorator(name='initialize_messaging_service')
async def initialize_messaging_service(
    settings: MessagingSettings,
) -> MessagingServiceT:
    """Initialize async services that require await."""

    # locator = get_service_locator()
    pubsub_service = await create_pubsub_service(settings)
    # locator.register(IMessagingService, pubsub_service)
    return pubsub_service


__all__ = [
    'initialize_messaging_service',
    'KafkaMessagingService',
    'messaging',
]
