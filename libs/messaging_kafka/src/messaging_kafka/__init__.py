from typing import Optional

from core.conf.settings import AppSetting, get_app_settings
from core.messaging.types import IMessagingService
from core.safety.retry import retry
from core.services.service_registry import get_service_locator

from .aiokafka_messaging import AiokafkaMessagingService as KafkaMessagingService
from .decorator import messaging

async def create_pubsub_service(settings: AppSetting) -> IMessagingService:
    """Create pub/sub service based on configuration."""

    kafka = KafkaMessagingService()
    if settings.KAFKA_CONSUMER_ENABLE:
        await kafka.start_producer()
        await kafka.start_consumer()
    else:
        await kafka.start_producer()

    return kafka


@retry.decorator(name='initialize_messaging_service')
async def initialize_messaging_service(
    settings: Optional[AppSetting] = None,
) -> IMessagingService:
    """Initialize async services that require await."""
    settings = get_app_settings() if settings is None else settings

    # locator = get_service_locator()
    pubsub_service = await create_pubsub_service(settings)
    # locator.register(IMessagingService, pubsub_service)
    return pubsub_service

__all__ = [
    'initialize_messaging_service',
    'KafkaMessagingService',
    'messaging',
]
