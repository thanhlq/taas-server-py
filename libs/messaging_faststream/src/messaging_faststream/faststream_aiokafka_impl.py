"""
🚀 FastStream Kafka Messaging Service

Implements ``IMessagingPubSubService`` using FastStream's ``KafkaBroker``.

Advantages over the pure-aiokafka implementation:

* **First-class test support** — ``TestKafkaBroker`` provides a fully
  in-memory Kafka broker, making unit tests fast and hermetic.
* **Built-in middleware hooks** — OpenTelemetry, Prometheus, and custom
  middlewares integrate cleanly with FastStream's pipeline model.
* **Optional Schema Registry** — Pass a ``SchemaRegistryConfig`` plus per-topic
  Avro schemas to enable Confluent wire-format encoding / decoding.
* **Declarative + dynamic subscriptions** — Static topic subscriptions are
  configured before ``start_consuming()``.  Dynamic ``subscribe()`` calls
  create independent consumers with their own consumer group IDs, exactly
  mirroring the aiokafka implementation.

Architecture
------------

.. code-block:: text

    ┌─────────────────────────────────────────────────────────┐
    │              FastStreamKafkaMessagingService            │
    │                                                         │
    │  ┌─────────────┐  ┌──────────────────────────────────┐ │
    │  │ KafkaBroker │  │  Dispatch Table                  │ │
    │  │  (FastStream│  │  topic → {sub_id: handler, ...}  │ │
    │  │   0.6.7)    │  └──────────────────────────────────┘ │
    │  │             │                                        │
    │  │  producer ──┼─→ broker.publish()                    │
    │  │  subscriber ◄─── main loop (EventProcessorFast)     │ │
    │  │  subscriber ◄─── dynamic subscribe() (direct call) │ │
    │  └─────────────┘                                        │
    │                                                         │
    │  Optional: AsyncSchemaRegistryEncoder (Avro)            │
    └─────────────────────────────────────────────────────────┘

Lifecycle
---------

.. code-block:: python

    service = FastStreamKafkaMessagingService()

    # API / producer-only
    await service.start_producer()
    await service.publish("iam.user.registered", event)

    # Worker / consumer
    await service.start_producer()
    await service.start_consumer()
    await service.start_consuming()   # blocks until stopped

    # With Schema Registry
    sr_config = SchemaRegistryConfig(url="http://localhost:8081")
    service = FastStreamKafkaMessagingService(
        schema_registry_config=sr_config,
        avro_schemas={"iam.user.registered": MY_AVRO_SCHEMA},
    )

Testing
-------

.. code-block:: python

    from faststream.kafka.testing import TestKafkaBroker

    async def test_publish():
        service = FastStreamKafkaMessagingService()
        received = []
        await service.subscribe("test-topic", received.append)

        async with TestKafkaBroker(service.get_broker()) as tb:
            await service.publish("test-topic", test_event)

        assert len(received) == 1
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError
from faststream.kafka import KafkaBroker, KafkaMessage
from foundation.exceptions.report_error import report_error
from foundation.messaging.kafka.base_messaging import BaseMessagingService
from foundation.messaging.events.event_processor import EventProcessor
from foundation.messaging.types import (
    BaseEvent,
    BaseSendableMessage,
    DlqEvent,
    IMessageEncoder,
    IMessagingService,
    MessageHandler,
    MessageServiceStats,
    MessagingProvider,
)
from foundation.messaging.utils.msg_encoder import MsgDecoderError
from foundation.utils.icons import Icons
from foundation.utils.singleton import singleton

from .helper import FastStreamHelper

# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------


@dataclass
class _SubscriptionInfo:
    """Metadata for a dynamic ``subscribe()`` subscription."""

    handler: MessageHandler
    topic: str
    consumer_group: str
    from_beginning: bool
    # The FastStream subscriber object — kept for ``unsubscribe()`` cleanup
    subscriber: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@singleton
class FastStreamKafkaMessagingService(BaseMessagingService, IMessagingService):
    """
    Kafka messaging service built on FastStream 0.6.x.

    Parameters
    ----------
    schema_registry_config:
        When provided, Avro encoding / decoding via the Confluent Schema
        Registry is enabled.  All topics that carry Avro messages must also
        have a schema registered via *avro_schemas* or by calling
        ``register_topic_schema()`` before the first message is sent.
    avro_schemas:
        Mapping of ``topic_name → avro_schema_dict`` used when
        ``schema_registry_config`` is set.
    """

    def __init__(
        self,
        *,
        avro_schemas: Optional[dict[str, dict]] = None,
    ) -> None:
        super().__init__(avro_schemas=avro_schemas)

        # ------------------------------------------------------------------
        # FastStream broker — created eagerly so subscribers can be
        # registered before start() is called (required for TestKafkaBroker).
        # ------------------------------------------------------------------
        self._broker = KafkaBroker(
            bootstrap_servers=self.messaging_config.kafka_bootstrap_servers,
        )
        self._broker_started: bool = False

        # aiokafka admin client for topic management (create / delete / list).
        # Initialised in start_producer().
        self._admin_client: Optional[AIOKafkaAdminClient] = None

        # ------------------------------------------------------------------
        # Subscription state
        # ------------------------------------------------------------------
        # Main-loop topic dispatch: topic → {sub_id: SubscriptionInfo}
        # Used by dynamic subscribe() callers.
        # NOTE: The "main loop" topics (start_consumer) go through
        # EventProcessorFast, *not* this table.
        self._subscriptions: dict[str, _SubscriptionInfo] = {}

        # Topics requested via start_consumer(); registered as main-loop
        # FastStream subscribers when start_consuming() is called.
        self.configured_topics: set[str] = set()

        # FastStream subscriber objects for main-loop topics (one per topic).
        self._main_subscribers: dict[str, Any] = {}

        # ------------------------------------------------------------------
        # Stats & processors
        # ------------------------------------------------------------------
        self.stats = MessageServiceStats(
            uptime_seconds=0,
            requests_handled=0,
            errors_occurred=0,
            messages_published=0,
            messages_processed=0,
            messages_failed=0,
            messages_retried=0,
            messages_dlq=0,
        )
        self.event_processor = EventProcessor(stats=self.stats)
        self.running: bool = False

        self.logger.info(
            f'{Icons.FASTSTREAM} ⚙️ FastStreamMessagingService initialised | '
            f'encoder={self.msg_encoder} | '
            f'driver={str(self.get_provider())} | '
            f'subs_auto_offset_reset={self.subs_auto_offset_reset} | '
            f'schema_registry={"enabled" if self.schema_registry_config else "disabled"}'
        )

    # -----------------------------------------------------------------------
    # IMessagingService — introspection
    # -----------------------------------------------------------------------

    def is_consumer_enabled(self) -> bool:
        """Return True if the consumer is enabled and running."""
        return self.messaging_config.kafka_consumer_enable and self.running

    def get_provider(self) -> MessagingProvider:
        """Return the messaging provider identifier."""
        return MessagingProvider.KAFKA_FASTSTREAM

    def get_msg_encoder(self) -> IMessageEncoder:
        """Return the synchronous message encoder (JSON / msgpack)."""
        return self.msg_encoder

    def get_broker(self) -> KafkaBroker:
        """Expose the underlying ``KafkaBroker`` for testing.

        Use with ``TestKafkaBroker``::

            async with TestKafkaBroker(service.get_broker()) as tb:
                await service.publish("topic", event)
        """
        return self._broker

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self):
        """Start producer and optionally consumer depending on settings."""
        await self.start_producer()
        if self.messaging_config.kafka_consumer_enable:
            await self.start_consumer()
            self.logger.info('Kafka service started with PRODUCER and CONSUMER ➡️⬅️')
        else:
            self.logger.info('Kafka service started with PRODUCER only ➡️')

    async def start_producer(self) -> None:
        """
        Establish the broker connection for publishing.

        Calls ``broker.connect()`` which creates the underlying aiokafka
        producer and makes ``broker.publish()`` available.  Does **not**
        start subscriber consumer tasks — call ``start_consuming()`` for that.

        Also starts the aiokafka admin client used by
        ``create_channel`` / ``delete_channel`` / ``list_channels``.
        """
        try:
            self.logger.info(
                f'📨 ➡️  Connecting FastStream broker: {self.messaging_config.kafka_bootstrap_servers}'
            )
            await self._broker.connect()

            self._admin_client = AIOKafkaAdminClient(
                bootstrap_servers=self.messaging_config.kafka_bootstrap_servers_list,
            )
            await self._admin_client.start()

            self.running = True
            self.logger.info('📨➡️ 🟢  FastStream broker connected — producer ready')
        except Exception as exc:
            report_error(
                exc, title='FastStream Producer Start Error', logger=self.logger
            )
            raise

    async def start_consumer(self) -> None:
        """
        Record the topics that should be consumed in the main worker loop.

        The FastStream subscriber objects are **not** created here — that
        happens in ``start_consuming()`` / ``start_consuming_sequential()``
        so that the correct ``max_workers`` value can be applied.

        Raises:
            RuntimeError: When called before ``start_producer()``.
        """
        if not self.running:
            raise RuntimeError('Call start_producer() before start_consumer().')
        self.configured_topics.update(self.messaging_config.kafka_topics)
        self.logger.info(
            f'📨 ⬅️  Consumer configured: topics={self.messaging_config.kafka_topics} '
            f'group_id={self.messaging_config.consumer_group_id}'
        )

    async def start_consuming(self) -> None:
        """
        Register concurrent main-loop subscribers and run until stopped.

        Registers one FastStream subscriber per configured topic using
        ``MAX_CONCURRENT_TASKS`` as the concurrency limit.  Messages are
        dispatched through ``EventProcessorFast`` for retry / DLQ support.

        This method **blocks** until ``astop()`` sets ``self.running = False``.

        Must be called after ``start_producer()`` and ``start_consumer()``.
        """
        await self._run_consuming(max_workers=self.messaging_config.max_concurrent_tasks)

    async def start_consuming_sequential(self) -> None:
        """
        Register sequential main-loop subscribers and run until stopped.

        Identical to ``start_consuming()`` but uses ``max_workers=1`` so
        messages are processed strictly one at a time.  Use when event
        ordering is critical.
        """
        await self._run_consuming(max_workers=1)

    async def _run_consuming(self, max_workers: int) -> None:
        """Internal: register main-loop subscribers, start broker, keep alive."""
        if not self._broker:
            raise RuntimeError('Call start_producer() first.')

        self.logger.info(
            f'🔄 Starting FastStream consumption: '
            f'topics={list(self.configured_topics)} max_workers={max_workers}'
        )

        # Register one FastStream subscriber per configured topic.
        for topic in self.configured_topics:
            self._register_main_subscriber(topic, max_workers=max_workers)

        try:
            # broker.start() launches subscriber background tasks.
            # It is idempotent if broker.connect() was already called.
            await self._broker.start()
            self._broker_started = True

            # Keep the coroutine alive — FastStream handles consumption internally.
            while self.running:
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            self.logger.info('Consumption task cancelled')
        except Exception as exc:
            report_error(exc, title='FastStream Consumption Error', logger=self.logger)
            raise

    async def stop(self) -> None:
        """Gracefully shut down all broker connections and clean up resources."""
        try:
            await self._do_stop()
            self.logger.info('📨 👋 FastStream Kafka service stopped')
        except Exception as exc:
            report_error(exc, title='FastStream Service Stop Error', logger=self.logger)

    async def _do_stop(self) -> None:
        self.logger.info('Stopping FastStream Kafka service …')
        self.running = False

        # Wait for EventProcessor to drain in-flight tasks.
        if self.event_processor:
            try:
                await asyncio.wait_for(
                    self.event_processor.cleanup(),
                    timeout=self.messaging_config.graceful_shutdown_timeout,
                )
            except TimeoutError:
                self.logger.warning(
                    f'EventProcessor.cleanup() timed out after '
                    f'{self.messaging_config.graceful_shutdown_timeout}s'
                )
            except Exception as exc:
                report_error(
                    exc,
                    title='EventProcessor Cleanup Error',
                    logger=self.logger,
                )

        # Stop admin client.
        if self._admin_client:
            await self._admin_client.close()
            self._admin_client = None

        # Close the broker (stops all subscribers + producer).
        # Guarded with a timeout because aiokafka's LeaveGroupRequest can hang
        # up to request_timeout_ms (40 s default) × retries if the coordinator
        # is slow or unreachable during shutdown.
        try:
            self.logger.warning(
                f'Stopping FastStream broker with a timeout of {self.messaging_config.graceful_shutdown_timeout}s...'
            )
            await asyncio.wait_for(
                self._broker.stop(),
                timeout=self.messaging_config.graceful_shutdown_timeout,
            )
            self._broker_started = False
        except TimeoutError:
            self.logger.warning(
                f'Broker stop timed out after {self.messaging_config.graceful_shutdown_timeout}s '
                f'(LeaveGroup requests may not have completed — safe to ignore)'
            )
            self._broker_started = False
        except Exception as exc:
            report_error(exc, title='FastStream Broker Close Error', logger=self.logger)

        self.logger.info(f'FastStream stopped | stats={self.stats}')

    # -----------------------------------------------------------------------
    # Publishing
    # -----------------------------------------------------------------------
    async def publish(
        self,
        channel: str,
        message: BaseSendableMessage,
        *,
        key: bytes | str | Any | None = None,
        timestamp_ms: int | None = None,
        headers: dict[str, str] | None = None,
        partition: Optional[int] = None,
        correlation_id: str | None = None,
        reply_to: str = '',
        no_confirm: bool = False,
        **kwargs,
    ) -> asyncio.Future[KafkaMessage | None] | None:
        """
        Publish *message* to *channel* (Kafka topic).

        Encodes the event (JSON / msgpack / Avro depending on configuration),
        injects distributed-tracing headers, and publishes via the FastStream
        broker.

        Args:
            channel: Target Kafka topic name.
            message: ``BaseEvent`` or ``dict`` to publish.
            partition_key: Optional routing key for partition assignment.
            headers: Additional headers merged with tracing headers.
            **kwargs: Reserved for future use.
        """
        # tracer: ITracingManager = TracingFactory().get_tracing_manager()
        # ContextTracer = TracingFactory().get_context_tracer()
        # with ContextTracer(f'kafka.publish.{channel}') as span:

        # In case of publish from outbbox, the correlation_id may be passed in headers instead of kwargs, so we pop it from headers if not found in kwargs.
        correlation_id = (
            correlation_id or headers.pop('correlation_id') if headers else None
        )
        if not correlation_id:
            correlation_id = kwargs.get('correlation_id')
        traceparent = (
            headers.pop('traceparent') if headers and 'traceparent' in headers else None
        )
        if not traceparent:
            traceparent = kwargs.get('traceparent')

        try:

            _msg_data = message.as_dict() if isinstance(message, BaseEvent) else message

            # Build trace + custom headers
            publish_headers: dict[str, str] = FastStreamHelper.build_publish_headers(
                traceparent=traceparent,
                extra=headers,
            )

            # Key must be bytes for aiokafka
            key_bytes: bytes | None = None
            if key and isinstance(key, str):
                key_bytes = key.encode('utf-8')
            elif key and isinstance(key, bytes):
                key_bytes = key

            _msg_data_encoded = await self._encode_message(channel, _msg_data)

            if isinstance(_msg_data_encoded, bytes):
                # so kafka does try to decode it as JSON, we set content-type to application/octet-stream
                publish_headers['content-type'] = 'application/octet-stream'

            await self._broker.publish(
                _msg_data_encoded,
                topic=channel,
                headers=publish_headers,
                key=key_bytes,
                correlation_id=correlation_id,
            )

            self.stats.messages_published += 1

            if self._debug:
                if isinstance(message, BaseEvent):
                    self.logger.debug(
                        f'{Icons.FASTSTREAM} ➡️  Published event [BaseEvent]: topic={channel} '
                        f'event_type={message.event_type} event_id={message.event_id} '
                        f'correlation_id={correlation_id}'
                    )
                elif isinstance(message, dict):
                     self.logger.debug(
                        f'{Icons.FASTSTREAM} ➡️  Published message [dict]: topic={channel} '
                        f'correlation_id={correlation_id} payload={message}'
                    )
                else:
                    self.logger.debug(
                        f'{Icons.FASTSTREAM} ➡️  Published message [unknown]: topic={channel}, message: {message}'
                    )
        except Exception as exc:
            report_error(
                exc,
                title='FastStream Publish Error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            raise

    # -----------------------------------------------------------------------
    # Dynamic subscriptions
    # -----------------------------------------------------------------------

    async def subscribe(
        self,
        channel: str,
        handler: MessageHandler,
        consumer_group: Optional[str] = None,
        from_beginning: bool = False,
        **kwargs: Any,
    ) -> str:
        """
        Dynamically subscribe to *channel* with *handler*.

        Creates a dedicated FastStream subscriber with a unique consumer group
        so that each subscription receives **all** messages on the topic
        independently (fan-out pattern).

        If the broker is already running (i.e. ``start_consuming()`` was
        called) the new subscriber is started immediately.  Otherwise it will
        be started automatically when ``start_consuming()`` is next called.

        Args:
            channel: Kafka topic name to subscribe to.
            handler: Async callable invoked with each decoded ``BaseEvent``.
            consumer_group: Override the consumer group ID.  When ``None`` a
                unique group ID is generated from the base group + a UUID.
            from_beginning: When ``True`` reset the offset to the earliest
                available message.  Defaults to ``False`` (latest).

        Returns:
            A unique subscription ID.  Pass it to ``unsubscribe()`` to cancel.
        """
        sub_id = str(uuid.uuid4())
        group_id = consumer_group or self.messaging_config.consumer_group_id
        auto_offset = 'earliest' if from_beginning else self.subs_auto_offset_reset

        # Why this func is not invoked?
        async def _direct_handler(raw: bytes, message: KafkaMessage) -> None:
            try:
                # In tests (TestKafkaBroker) the payload may already be decoded;
                # in production it is raw bytes.
                event = await self._decode_message(channel, raw)
                await handler(event)
            except MsgDecoderError as exc:
                report_error(
                    exc,
                    title='FastStream Subscribe Decode Error',
                    extra_context={'topic': channel, 'sub_id': sub_id},
                    logger=self.logger,
                )
            except Exception as exc:
                report_error(
                    exc,
                    title='FastStream Subscribe Handler Error',
                    extra_context={'topic': channel, 'sub_id': sub_id},
                    logger=self.logger,
                )

        # Create the FastStream subscriber with a unique consumer group.
        subscriber = self._broker.subscriber(
            channel,
            group_id=group_id,
            auto_offset_reset=auto_offset,
        )
        subscriber(_direct_handler)

        # If the broker is already started, launch the subscriber now.
        if self._broker_started:
            try:
                await subscriber.start()
            except Exception as exc:
                self.logger.warning(
                    f'Could not start dynamic subscriber immediately: {exc!r}. '
                    'It will be started on the next broker.start() call.'
                )

        sub_info = _SubscriptionInfo(
            handler=handler,
            topic=channel,
            consumer_group=group_id,
            from_beginning=from_beginning,
            subscriber=subscriber,
        )
        self._subscriptions[sub_id] = sub_info
        self.stats.active_subscriptions = len(self._subscriptions)
        self.logger.info(
            f'⬅️  Subscribed: topic={channel} sub_id={sub_id} group_id={group_id}'
        )
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """
        Cancel and clean up a dynamic subscription.

        Stops the underlying FastStream subscriber so the consumer group
        leaves the Kafka broker cleanly.

        Args:
            subscription_id: ID returned by a previous ``subscribe()`` call.

        Raises:
            KeyError: When the subscription ID is not found.
        """
        if subscription_id not in self._subscriptions:
            raise KeyError(f'Subscription not found: {subscription_id!r}')

        sub_info = self._subscriptions.pop(subscription_id)
        self.stats.active_subscriptions = len(self._subscriptions)

        subscriber = sub_info.subscriber
        if subscriber is not None and self._broker_started:
            try:
                await subscriber.close()
            except Exception as exc:
                self.logger.warning(
                    f'Error stopping subscriber for {subscription_id}: {exc!r}'
                )

        self.logger.info(
            f'⬅️  Unsubscribed: topic={sub_info.topic} sub_id={subscription_id}'
        )

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
        if not self._admin_client:
            raise RuntimeError('Call start_producer() first.')
        try:
            topic = NewTopic(
                name=channel,
                num_partitions=num_partitions,
                replication_factor=replication_factor,
            )
            await self._admin_client.create_topics([topic])
            self.logger.info(f'📋 Created topic: {channel}')
            return True
        except TopicAlreadyExistsError:
            self.logger.debug(f'Topic already exists: {channel}')
            return True
        except Exception as exc:
            report_error(
                exc,
                title='FastStream Create Topic Error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            return False

    async def delete_channel(self, channel: str, **kwargs: Any) -> bool:
        """
        Delete a Kafka topic (channel).

        Args:
            channel: Topic name to delete.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        if not self._admin_client:
            raise RuntimeError('Call start_producer() first.')
        try:
            await self._admin_client.delete_topics([channel])
            self.logger.info(f'🗑️  Deleted topic: {channel}')
            return True
        except Exception as exc:
            report_error(
                exc,
                title='FastStream Delete Topic Error',
                extra_context={'topic': channel},
                logger=self.logger,
            )
            return False

    async def list_channels(self, **kwargs: Any) -> list[str]:
        """
        List all available Kafka topics.

        Returns:
            List of topic names, excluding internal Kafka topics
            (those starting with ``_``).
        """
        if not self._admin_client:
            raise RuntimeError('Call start_producer() first.')
        try:
            metadata = await self._admin_client.list_topics()
            return [t for t in metadata if not t.startswith('_')]
        except Exception as exc:
            report_error(
                exc,
                title='FastStream List Topics Error',
                logger=self.logger,
            )
            return []

    # -----------------------------------------------------------------------
    # Stats
    # -----------------------------------------------------------------------

    def get_stats(self) -> MessageServiceStats:
        """Return a snapshot of current service statistics."""
        self.stats.running = self.running
        self.stats.active_subscriptions = len(self._subscriptions)
        return self.stats

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _encode_message(
        self, topic: str, message: BaseSendableMessage
    ) -> Union[bytes, str, Any]:
        """Encode *message* to bytes.

        Uses ``AsyncSchemaRegistryEncoder`` when Schema Registry is configured,
        otherwise falls back to the synchronous ``MsgEncoder``.
        """
        # msg_dict = message.as_dict()

        # if self._schema_registry_encoder is not None:
        #     return await self._schema_registry_encoder.encode_event(topic, msg_dict)

        # encoded = self.msg_encoder.encode_msg(msg_dict)
        # if isinstance(encoded, str):
        #     return encoded.encode('utf-8')
        # return encoded

        return await self.msg_encoder.encode_msg(
            message, channel=topic, sr_encoder=self._schema_registry_encoder
        )

    async def _decode_message(self, topic: str, raw: bytes) -> BaseEvent:
        """Decode raw Kafka bytes to a ``BaseEvent``.

        Uses ``AsyncSchemaRegistryEncoder`` when Schema Registry is configured,
        otherwise falls back to the synchronous ``MsgEncoder``.
        """
        # if self._schema_registry_encoder is not None:
        #     import dataclasses as _dc
        #     data: dict[str, Any] = await self._schema_registry_encoder.decode(
        #         topic, raw
        #     )
        #     # Only decode bytes fields further (e.g. msgpack-encoded sub-objects
        #     # like `payload` or `tenant`).  Plain string fields decoded by Avro
        #     # (event_type, email, username, …) must NOT be passed to
        #     # decode_payload — that would call msgpack.unpackb() on a plain
        #     # Python string and raise a TypeError.
        #     all_data: dict[str, Any] = {
        #         k: (
        #             self.msg_encoder.decode_payload(v)
        #             if isinstance(v, bytes)
        #             else v
        #         )
        #         for k, v in data.items()
        #     }
        #     event_type: str = all_data.get('event_type', '')
        #     event_cls = self._event_type_registry.get(event_type, BaseEvent)
        #     valid_fields = {f.name for f in _dc.fields(event_cls)}
        #     filtered = {k: v for k, v in all_data.items() if k in valid_fields}
        #     return event_cls(**filtered)

        return await self.msg_encoder.decode_msg(raw, channel=topic, sr_encoder=self._schema_registry_encoder)  # type: ignore

    async def _decode_dlq_message(self, topic: str, raw: bytes) -> DlqEvent:
        return await self.msg_encoder.decode_msg(raw, channel=topic, sr_encoder=self._schema_registry_encoder)  # type: ignore

    def _register_main_subscriber(self, topic: str, max_workers: int) -> None:
        """Register a FastStream subscriber for the main EventProcessor loop.

        This subscriber dispatches messages through ``EventProcessorFast``
        which handles retry, DLQ, idempotency, and observability.  It is
        separate from the direct-handler subscribers created by ``subscribe()``.

        Calling this method twice for the same topic is a no-op.

        Args:
            topic: Kafka topic to subscribe to.
            max_workers: Maximum concurrent message processing coroutines.
        """
        if topic in self._main_subscribers:
            self.logger.warning(
                f'Main subscriber already registered for topic={topic} — skipping'
            )
            return

        # Capture topic in closure.
        async def _main_handler(msg: bytes | dict, message: KafkaMessage) -> None:
            try:
                await self._process_message(topic, msg, message)
            except Exception as exc:
                report_error(
                    exc,
                    title='FastStream Main Handler Error',
                    extra_context={'topic': topic},
                    logger=self.logger,
                )

        subscriber = self._broker.subscriber(
            topic,
            group_id=self.messaging_config.consumer_group_id,
            auto_offset_reset=self.messaging_config.kafka_auto_offset_reset,
            # This option is deprecated and will be removed in 0.7.0 release
            # auto_commit=self.messaging_config.kafka_enable_auto_commit,
            # max_workers=max_workers,
        )
        subscriber(_main_handler)
        self._main_subscribers[topic] = subscriber
        self.logger.debug(
            f'Registered main-loop subscriber: topic={topic} max_workers={max_workers}'
        )

    async def _process_message(
        self,
        topic: str,
        raw: bytes | dict | None,
        message: KafkaMessage,
    ) -> None:
        """Process a single Kafka message through the EventProcessor pipeline.

        Handles:
        * Message decoding (JSON / msgpack / Avro).
        * Trace-context extraction and propagation.
        * Retry logic via ``EventProcessorFast``.
        * Dead Letter Queue on ``MAX_RETRIES`` exhaustion.
        * Statistics updates.

        Args:
            topic: The Kafka topic the message was received on.
            raw: Raw message bytes from the broker, or ``None`` if the message is null.
            message: FastStream ``KafkaMessage`` wrapper (used for headers).
        """
        if raw is None:
            self.logger.warning(f'Skipping null message on topic={topic}')
            return

        traceparent = FastStreamHelper.find_traceparent(message)

        # Decode
        try:
            if isinstance(raw, bytes):
                event = await self._decode_message(topic, raw)
                # print(f"▶▶▶▶▶▶▶▶▶ Received BYTES message on topic {topic}: {raw}")
            elif isinstance(raw, dict): # type: ignore
                # If set the kafka header content-type to application/octet-stream, FastStream will not try to decode the message as JSON and pass it as dict to the handler.
                # So this code will not be reached / but still keep it here just in case
                # print(f"▶▶▶▶▶▶▶▶▶ Received DICT message on topic {topic}: {raw}")
                event = self.msg_encoder.reconstruct_event(raw)
            else:
                # SERIOUSLY? BIG FAILURE -> HOW TO SAFEGUARD THIS?  We don't want to raise an exception here and trigger a retry loop on an unprocessable message, but we also want to log this as a critical error since it indicates a fundamental problem with the message format or the broker.
                raise MsgDecoderError(
                    f'Unsupported message type: {type(raw)} (expected bytes or dict)'
                )
        except MsgDecoderError as exc:
            report_error(
                exc,
                title='FastStream Message Decode Error',
                extra_context={'topic': topic},
                logger=self.logger,
            )
            self.stats.messages_failed += 1
            return

        # Dispatch through EventProcessor (retry + observability)
        result = await self.event_processor.process_event(event, traceparent)

        if result.success:
            self.stats.messages_processed += 1
            self.logger.info(
                f'⬅️  Processed: event_id={getattr(event, "event_id", "n/a")} '
                f'event_type={getattr(event, "event_type", "n/a")} '
                f'topic={topic} '
                f'processing_time_ms={getattr(result, "processing_time_ms", "n/a")}'
            )
        elif self.messaging_config.dlq_enabled:
            self.stats.messages_failed += 1
            if getattr(event, 'retry_count', 0) >= self.messaging_config.max_retries:
                await self.send_to_dlq(event, result.error, traceparent)
                self.stats.messages_dlq += 1
            else:
                self.stats.messages_retried += 1
        else:
            self.stats.messages_failed += 1
            self.logger.warning(
                f'⬅️  Processing failed and DLQ disabled: event_id={getattr(event, "event_id", "n/a")} '
                f'event_type={getattr(event, "event_type", "n/a")} '
                f'topic={topic} '
                f'error={result.error!r}'
            )

    async def _publish_dlq_event(
        self,
        dlq_event: DlqEvent,
        *,
        traceparent: Optional[str] = None,
        correlation_id: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ):
        encoded = await self._encode_message(self.messaging_config.dlq_topic, dlq_event)
        dlq_headers: dict[str, str] = FastStreamHelper.build_publish_headers(
            traceparent=traceparent,
            extra=headers,
        )
        await self._broker.publish(
            encoded,
            topic=self.messaging_config.dlq_topic,
            headers=dlq_headers,
            correlation_id=correlation_id,
        )
