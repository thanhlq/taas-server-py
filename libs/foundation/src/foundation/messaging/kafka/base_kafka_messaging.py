from abc import ABC
from typing import Any, Iterable, Literal, Optional, Union

from foundation.messaging.base_messaging import BaseMessagingService
from foundation.messaging.kafka.kafka_security import (
    KafkaSecurityConfig,
    get_kafka_security_config,
)
from foundation.messaging.kafka.kafka_settings import KafkaSettings
from foundation.messaging.kafka.sr.sr_config import build_schema_registry_config
from foundation.messaging.types import MessagingServiceT

from ..types import (
    BaseEvent,
    MessageEncodingType,
)
from .sr import SchemaRegistryEncoder


class BaseKafkaMessagingService[ProducerT, ConsumerT, MessageT](
    BaseMessagingService[ProducerT, ConsumerT, MessageT],
    MessagingServiceT[ProducerT, ConsumerT, MessageT],
    ABC,
):
    """Base kafka messaging service that provides common functionality for all messaging services."""

    _kafka_config: KafkaSettings | None = None
    _kafka_security_config: KafkaSecurityConfig | None = None
    _schema_registry_encoder: Optional[SchemaRegistryEncoder] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def kafka_config(self) -> KafkaSettings:
        """Return the Kafka-specific configuration snapshot."""
        if self._kafka_config is None:
            self._kafka_config = KafkaSettings()
        return self._kafka_config

    @property
    def security_config(self) -> 'KafkaSecurityConfig':
        """Return the Kafka security configuration snapshot."""
        if self._kafka_security_config is None:
            self._kafka_security_config = get_kafka_security_config(self.kafka_config)
        return self._kafka_security_config

    def get_consumer_group_id(self) -> str:
        """Return the consumer group ID from the configuration."""
        return (
            self.kafka_config.KAFKA_CONSUMER_GROUP_ID
        )

    @property
    def schema_registry_enabled(self) -> bool:
        return self.msg_encoder.serialization_format == MessageEncodingType.SCHEMA_REGISTRY_AVRO

    @property
    def schema_registry_encoder(self) -> SchemaRegistryEncoder:
        if not self.schema_registry_enabled:
            raise RuntimeError(
                f'Schema registry is not enabled (current end={self.msg_encoder.serialization_format}). Set MESSAGE_ENCODING=schema-registry-avro in your environment to enable it.'
            )

        if self._schema_registry_encoder is None:
            cfg = build_schema_registry_config(self.kafka_config)
            if cfg.username is None or cfg.password is None:
                self.logger.warning(
                    'Schema registry is enabled but username/password are not set. '
                    'Schema registry encoder may not work properly.'
                )
            self._schema_registry_encoder = SchemaRegistryEncoder(
                registry_config=cfg
                # avro_schemas=avro_schemas,
            )
        return self._schema_registry_encoder

    @property
    def kafka_bootstrap_servers(self) -> Union[str, Iterable[str]]:
        return self.kafka_config.kafka_bootstrap_servers_list

    def _validate_config(self):
        # Validation now lives in BaseMessagingConfig.__post_init__.
        # Kept for backward-compat with subclasses that still call it.
        return

    @property
    def auto_commit(self) -> bool:
        """Return whether the Kafka consumer is configured to auto-commit offsets."""
        return self.kafka_config.KAFKA_ENABLE_AUTO_COMMIT

    @property
    def auto_offset_reset(self) -> Literal['latest', 'earliest', 'none']:
        """
        Return the Kafka consumer's auto-offset-reset policy.
        Faststream and aiokafka both use the same string values for this setting.
        """
        if self.kafka_config.KAFKA_MESSAGE_CONSUMING_FROM_BEGINING is True:
            return 'earliest'
        return 'latest'

    def register_schema(self, channel: str, schema: type[BaseEvent]) -> bool:
        """Register an Avro schema for *channel* at runtime.

        Requires ``schema_registry_config`` to have been provided at
        construction time.

        Args:
            channel: Kafka channel name.
            schema: Event class (subclass of BaseEvent).

        Raises:
            RuntimeError: When the service was not initialised with a
                Schema Registry configuration.
        """

        if self.is_consumer_enabled() is False:
            return False

        self.logger.info(f'registering channel={channel}, schema_cls={schema.__name__}')
        _serialization_format = self.get_message_serialization_format()

        if (
            _serialization_format
            != MessageEncodingType.SCHEMA_REGISTRY_AVRO
        ):
            # Do nothing
            self.logger.debug(
                f'Ignoring register_schema for channel={channel}: '
                f'messaging encoding is {_serialization_format}'
            )
        else:
            from .sr.serializer import schema_cls_to_avro_schema

            self.schema_registry_encoder.register_topic_schema(
                channel, schema_cls_to_avro_schema(schema)
            )

        if channel not in self._subscribed_channels:
            self._subscribed_channels.add(channel)
            self.logger.info(
                f'🧬 Channel [{channel}] registered with schema [{schema.__name__}]'
            )

        return True

    # -----------------------------------------------------------------------
    # Channel management (topic admin)
    # -----------------------------------------------------------------------

    async def create_channel(
        self,
        channel: str,
        num_partitions: int = 1,
        *,
        replication_factor: int = 1,
        retention_hours: int = 168,  # 7 days default,
        fifo: bool = False,  # Only applicable for queues: if True, create FIFO queue with ordering guarantees.
        **kwargs,
    ) -> bool:
        """
        Create a Kafka topic (channel).

        Uses the aiokafka admin client.  Returns ``True`` on success and
        ``True`` when the topic already exists (idempotent).

        Args:
            channel: Topic name.
            num_partitions: Number of partitions (default 1).
            replication_factor: Replication factor (default 1).

        Returns:
            ``True`` if the topic exists or was created; ``False`` on error.
        """
        _admin_client = await self.get_admin_client()
        return await _admin_client.create_channel(
            channel,
            num_partitions=num_partitions,
            replication_factor=replication_factor,
            retention_hours=retention_hours,
            fifo=fifo,
        )

    async def delete_channel(self, channel: str, **kwargs: Any) -> bool:
        """
        Delete a Kafka topic (channel).

        Args:
            channel: Topic name to delete.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        _admin_client = await self.get_admin_client()
        return await _admin_client.delete_channel(channel)

    async def list_channels(self, **kwargs: Any) -> list[str]:
        """
        List all Kafka topics (channels).

        Returns:
            List of topic names.
        """
        _admin_client = await self.get_admin_client()
        return await _admin_client.list_channels()
