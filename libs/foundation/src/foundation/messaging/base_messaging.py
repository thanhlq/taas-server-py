from abc import ABC, abstractmethod
from typing import Optional

from foundation import BaseService
from foundation.exceptions.report_error import report_error
from foundation.messaging.config.messaging_settings import MessagingSettings
from foundation.messaging.types import MessagingServiceT
from foundation.messaging.utils.msg_encoder import MsgEncoder
from foundation.observability.tracing_factory import TracingFactory
from foundation.utils import now_in_utc

from .types import (
    BaseEvent,
    DlqEvent,
    MessageEncoderT,
    MessageServiceStats,
    MessagingAdminServiceT,
)


class BaseMessagingService[ProducerT, ConsumerT, MessageT](
    BaseService, MessagingServiceT[ProducerT, ConsumerT, MessageT], ABC
):
    """Base kafka messaging service that provides common functionality for all messaging services."""

    _config: MessagingSettings | None = None
    _subscribed_channels: set[str] = set()
    """ Number of workers to process messages concurrently """

    _msg_encoder: MsgEncoder | None = None

    _producer: ProducerT | None = None
    _producer_started: bool = False
    _consumer: ConsumerT | None = None
    _consumer_started: bool = False
    _consumer_running: bool = False
    """ Indicates whether the consumer is currently running. """
    _admin_client: MessagingAdminServiceT | None = None
    _admin_client_started: bool = False
    _dlq_producer: ProducerT | None = None
    _dlq_producer_started: bool = False

    stats: MessageServiceStats
    """ In-memory stats for monitoring and debugging. Not persisted across restarts. Useful for tracking message processing metrics. """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.config.CONSUMER_CHANNELS and len(self.config.CONSUMER_CHANNELS) > 0:
            self._subscribed_channels.update(self.config.CONSUMER_CHANNELS)
        else:
            self.logger.warning(
                'No consumer channels configured. '
                'Set CONSUMER_CHANNELS in your environment to enable consumption.'
            )

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

    @property
    def config(self) -> MessagingSettings:
        """Return the provider-agnostic, frozen configuration snapshot."""
        if self._config is None:
            self._config = MessagingSettings()
        return self._config

    @property
    def debug(self) -> bool:
        """Return True if debug logging is enabled."""
        return self.config.MESSAGING_DEBUG

    @property
    def consumer_channels(self) -> set[str]:
        return self._subscribed_channels

    def is_consumer_enabled(self) -> bool:
        """Return True if the consumer is enabled and running."""
        return self.config.CONSUMER_ENABLED

    def get_consumer_group_id(self) -> str:
        """Return the consumer group ID from the configuration."""
        return self.config.CONSUMER_GROUP_ID

    @property
    def msg_encoder(self) -> MsgEncoder:
        if self._msg_encoder is None:
            self._msg_encoder = MsgEncoder(config=self._config)
        return self._msg_encoder

    def get_msg_encoder(self) -> MessageEncoderT:
        return self.msg_encoder

    def get_messaging_encoding_type(self) -> str:
        """Return the configured message encoding type (e.g., json, msgpack, avro)."""
        return self.msg_encoder.msg_encoding()

    def get_stats(self) -> MessageServiceStats:
        """Return the current in-memory stats snapshot."""
        return self.stats

    @property
    def producer(self) -> ProducerT:
        if self._producer is None:
            raise RuntimeError(
                'Producer is not initialized. Call start_producer() first.'
            )
        return self._producer

    @property
    def consumer(self) -> ConsumerT:
        if self._consumer is None:
            raise RuntimeError(
                'Consumer is not initialized. Call start_consumer() first.'
            )
        if not self.is_consumer_enabled():
            raise RuntimeError(
                'Consumer is disabled. Set CONSUMER_ENABLE=True in your environment to enable it.'
            )
        return self._consumer

    @property
    def admin_client(self) -> MessagingAdminServiceT:
        if self._admin_client is None:
            raise RuntimeError(
                'Admin client is not initialized. Call start_admin_client() first.'
            )
        return self._admin_client

    @property
    def dlq_enabled(self) -> bool:
        return self.config.DLQ_ENABLED

    @property
    def dlq_topic(self) -> str:
        return self.config.DLQ_TOPIC

    def register_event_serializer(
        self, cls: type[BaseEvent], serializer: Optional[str] = None
    ) -> 'MessagingServiceT':
        self.msg_encoder.register_event_serializer(cls, serializer)
        return self

    async def start(self) -> 'BaseMessagingService':
        await self.start_producer()

        if self.is_consumer_enabled():
            await self.start_consumer()
            self.logger.info('📨 Kafka service started with PRODUCER and CONSUMER ➡️ ⬅️')
        else:
            self.logger.info('📨 Kafka service started with PRODUCER only ➡️')
        return self

    @abstractmethod
    async def start_producer(self) -> None: ...

    @abstractmethod
    async def start_consumer(self) -> None: ...

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
        if not self.dlq_enabled:
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
            span.set_attribute('dlq_topic', self.dlq_topic)
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
                    # handler_name=event.handler_name,
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
                        'dlq_topic': self.dlq_topic,
                    },
                    logger=self.logger,
                )
                raise e
