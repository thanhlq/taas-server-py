from typing import Literal, Optional

from foundation.exceptions.report_error import report_error
from foundation.messaging.config.kafka_settings import (
    KafkaSettings,
    build_messaging_config,
)
from foundation.messaging.config.messaging_config import MessagingConfig
from foundation.messaging.types import IMessagingService
from foundation.messaging.utils.msg_encoder import MsgEncoder
from foundation.observability.tracing_factory import TracingFactory
from foundation.utils import now_in_utc

from .sr import SchemaRegistryConfig, SchemaRegistryEncoder
from .types import BaseEvent, DlqEvent, IMessageEncoder, MessageServiceStats


class BaseMessagingService(IMessagingService):
    """Base kafka messaging service that provides common functionality for all messaging services."""

    messaging_config: MessagingConfig
    """Provider-agnostic, frozen configuration snapshot. Built once in
    ``__init__`` from :class:`AppSetting`; subclasses should read from this
    instead of touching ``self._config`` for messaging knobs."""

    subs_auto_offset_reset: Literal['latest', 'earliest', 'none'] = 'latest'
    subs_auto_commit: bool = False
    subs_max_workers: int = 1
    """ Number of workers to process messages concurrently """

    msg_encoding: str
    _msg_encoder: MsgEncoder | None = None

    _dlq_enabled: bool = False
    """
    Whether to enable Dead Letter Queue (DLQ) for failed messages. If True, failed messages will be sent to
    a DLQ topic for later analysis and reprocessing.
    """
    _dlq_topic: str = 'dlq'

    stats: MessageServiceStats
    """ In-memory stats for monitoring and debugging. Not persisted across restarts. Useful for tracking message processing metrics. """

    schema_registry_enabled: bool = False
    _schema_registry_encoder: Optional[SchemaRegistryEncoder] = None
    schema_registry_config: Optional[SchemaRegistryConfig] = None
    _debug: bool = True

    # Event-type registry: maps event_type string → typed BaseEvent subclass

    def __init__(self, *, avro_schemas: Optional[dict[str, dict]] = None):
        super().__init__()

        self.messaging_config = build_messaging_config(KafkaSettings())

        cfg = self.messaging_config
        self.subs_auto_offset_reset = cfg.kafka_auto_offset_reset
        self.subs_auto_commit = cfg.kafka_enable_auto_commit
        self.subs_max_workers = cfg.max_concurrent_tasks
        self.msg_encoding = cfg.message_encoding

        # ------------------------------------------------------------------
        # Schema Registry
        # ------------------------------------------------------------------
        self.schema_registry_enabled = cfg.schema_registry_enabled
        if self.schema_registry_enabled:
            sr_cfg = cfg.build_schema_registry_config()
            if sr_cfg is None:
                raise ValueError(
                    'MESSAGE_ENCODING is schema-registry-avro but '
                    'KAFKA_SCHEMA_REGISTRY_URL is not configured.'
                )
            self.schema_registry_config = sr_cfg
            self._schema_registry_encoder = SchemaRegistryEncoder(
                registry_config=sr_cfg,
                avro_schemas=avro_schemas,
            )

        # ------------------------------------------------------------------
        # DLQ
        # ------------------------------------------------------------------
        self._dlq_enabled = cfg.dlq_enabled
        self._dlq_topic = cfg.dlq_topic

        # ------------------------------------------------------------------
        # Stats & processors
        # ------------------------------------------------------------------
        self.stats: MessageServiceStats = MessageServiceStats(
            uptime_seconds=0,
            requests_handled=0,
            errors_occurred=0,
            messages_processed=0,
            messages_failed=0,
            messages_retried=0,
            messages_dlq=0,
            messages_published=0,
        )

    def _validate_config(self):
        # Validation now lives in BaseMessagingConfig.__post_init__.
        # Kept for backward-compat with subclasses that still call it.
        return

    @property
    def msg_encoder(self) -> MsgEncoder:
        if self._msg_encoder is None:
            self._msg_encoder = MsgEncoder(config=self.messaging_config)
        return self._msg_encoder

    def get_msg_encoder(self) -> IMessageEncoder:
        return self.msg_encoder

    def get_messaging_encoding_type(self) -> str:
        """Return the configured message encoding type (e.g., json, msgpack, avro)."""
        return self.messaging_config.message_encoding

    def register_event_serializer(
        self, cls: type[BaseEvent], serializer: Optional[str] = None
    ) -> 'IMessagingService':
        self.msg_encoder.register_event_serializer(cls, serializer)
        return self

    async def _publish_dlq_event(
        self,
        dlq_event: DlqEvent,
        *,
        traceparent: Optional[str] = None,
        correlation_id: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        """
        Publish a DLQ event to the configured DLQ topic. To be implemented by subclasses with provider-specific logic.

        Args:
            dlq_event: The DLQ event to publish, containing details about the failed message and error.
            traceparent: Optional W3C traceparent string for distributed tracing correlation.
            correlation_id: Optional correlation ID for tracing and debugging.
            headers: Optional additional headers to include in the DLQ message.

        Returns:
            The result of the publish operation (e.g., Kafka send result).
        """
        if not self._dlq_enabled:
            self.logger.warning('DLQ is disabled. Skipping publish of DLQ event.')
            return None

        else:
            raise NotImplementedError(
                '_publish_dlq_event must be implemented by subclasses to publish DLQ events to the configured DLQ topic.'
            )

    async def send_to_dlq(
        self, event: BaseEvent, error: Optional[str], traceparent: Optional[str] = None
    ) -> None:
        """
        Send failed event to Dead Letter Queue within the same trace context.

        Args:
            event: Failed event
            error: Error message
            traceparent: Optional W3C traceparent header for distributed tracing
        """

        # FIXME: BaseEvent

        ContextTracer = TracingFactory().get_context_tracer()

        # Create span within the same trace context using ContextTracer
        with ContextTracer('send_to_dlq', traceparent) as span:
            span.set_attribute('event_id', event.event_id)
            span.set_attribute('event_type', event.event_type)
            span.set_attribute('retry_count', event.retry_count)
            span.set_attribute('error', error or 'Unknown error')
            span.set_attribute('dlq_topic', self._dlq_topic)
            # span.set_attribute('handler_name', event.handler_name or 'unknown')

            try:
                # dlq_event = {
                #     'original_event': event.as_json(),
                #     'error': error,
                #     'failed_at': now_as_iso(),
                #     'retry_count': event.metadata.retry_count,
                # }
                dlq_event = DlqEvent(
                    original_event=event.as_dict(),
                    error=error or 'Unknown error',
                    failed_at=now_in_utc(),
                    retry_count=event.retry_count,
                    handler_name=event.handler_name,
                )

                # await self.dlq_producer.send(  # type: ignore
                #     self._dlq_topic,
                #     value=dlq_event,
                # )
                await self._publish_dlq_event(
                    dlq_event,
                    traceparent=traceparent,
                    # correlation_id=event.correlation_id,
                )

                self.logger.warning(
                    f'⚠️ Event sent to DLQ: event_id={event.event_id}, error={error}, retry_count={event.retry_count}',
                )

            except Exception as e:
                span.record_exception(e)
                report_error(
                    e,
                    title='Failed to send event to DLQ',
                    extra_context={
                        'event_id': event.event_id,
                        'dlq_topic': self._dlq_topic,
                    },
                    logger=self.logger,
                )
                raise e

    def register_schema(self, channel: str, schema: dict) -> str:
        """Register an Avro schema for *channel* at runtime.

        Requires ``schema_registry_config`` to have been provided at
        construction time.

        Args:
            channel: Kafka channel name.
            schema: Avro schema dict.

        Raises:
            RuntimeError: When the service was not initialised with a
                Schema Registry configuration.
        """
        if self._schema_registry_encoder is None:
            raise RuntimeError(
                'Cannot register Avro schema: service was initialised without '
                'a SchemaRegistryConfig. Pass schema_registry_config= to the '
                'constructor.'
            )
        self._schema_registry_encoder.register_topic_schema(channel, schema)
        return ''
