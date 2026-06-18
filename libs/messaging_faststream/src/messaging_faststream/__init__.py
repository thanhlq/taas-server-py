"""
messaging_faststream — FastStream-based Kafka messaging service.

Public API
----------

``FastStreamKafkaMessagingService``
    Implements ``IMessagingPubSubService``.  Drop-in replacement for the
    aiokafka-based ``KafkaMessagingService`` with optional Confluent Schema
    Registry support and first-class test utilities.

``SchemaRegistryConfig``
    Connection settings for the Confluent Schema Registry.

``SchemaRegistryClient``
    Async HTTP client for the Confluent Schema Registry REST API.

``AsyncSchemaRegistryEncoder``
    High-level async encoder that serialises ``BaseEvent`` objects to
    Avro wire-format bytes using the Schema Registry.

``AvroSchemaRegistrySerializer``
    Low-level Avro serializer / deserializer (``fastavro`` + Confluent wire
    format).  Can be used independently of the messaging service.

``ConfluentWireFormat``
    Static utility to encode / decode the Confluent wire-format header
    (magic byte + 4-byte schema ID prefix).

``FastStreamHelper``
    Utility helpers for working with FastStream ``KafkaMessage`` headers
    (traceparent extraction, header building).
"""
from typing import Optional
from core.services.service_registry import get_service_locator
from core.messaging.types import IMessagingService
from core.messaging.base_messaging import SchemaRegistryConfig
from core.conf import AppSetting, get_app_settings
from core.safety.retry import retry

from .faststream_aiokafka_impl import FastStreamKafkaMessagingService
from .helper import FastStreamHelper
from core.messaging.sr.schema_registry_fast import (
    SchemaRegistryEncoder,
    ConfluentWireFormat,
    SchemaNotFoundError,
    SchemaRegistryClient,
    SchemaRegistryError,
)
from .decorator import messaging

async def create_pubsub_service(settings: AppSetting) -> IMessagingService:
    """Create pub/sub service based on configuration."""

    kafka = FastStreamKafkaMessagingService()
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
    # Service
    'FastStreamKafkaMessagingService',
    # Schema Registry
    'SchemaRegistryConfig',
    'SchemaRegistryClient',
    'SchemaRegistryEncoder',
    'ConfluentWireFormat',
    'SchemaRegistryError',
    'SchemaNotFoundError',
    # Helpers
    'FastStreamHelper',
    'initialize_messaging_service',
    'messaging',
]
